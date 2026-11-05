"""aiohttp app: JSON API for the Mini App (SPEC section 13) and the static files at /app/."""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl

from aiohttp import web

from ..entries import (add_override_entry, average_per_day, day_stats_for, user_tz,
                       week_stats_for)
from ..intervals import clip_span, day_bounds, hm_str, minute_of_day
from ..limits import check_limits
from ..repo import Repo
from ..timeutil import iso, local_date, local_dt, local_midnight, parse_hm, parse_iso, utcnow

log = logging.getLogger("web")

STATIC_DIR = Path(__file__).parent / "static"
INIT_DATA_MAX_AGE = 7 * 24 * 3600


# --------------------------------------------------------------------------- auth

def validate_init_data(init_data: str, bot_token: str, now_ts: float | None = None,
                       max_age: int = INIT_DATA_MAX_AGE) -> dict | None:
    """Telegram Mini App initData check. Returns the `user` object, or None if invalid."""
    if not init_data or not bot_token:
        return None
    try:
        fields = dict(parse_qsl(init_data, keep_blank_values=True))
        received = fields.pop("hash", None)
        if not received:
            return None
        check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
        secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
        expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, received):
            return None
        now_ts = utcnow().timestamp() if now_ts is None else now_ts
        if now_ts - int(fields.get("auth_date", "0")) > max_age:
            return None
        user = json.loads(fields["user"])
        if not isinstance(user, dict) or "id" not in user:
            return None
        return user
    except Exception:
        return None


def err(status: int, code: str, message: str = "") -> web.Response:
    return web.json_response({"error": code, "message": message or code.replace("_", " ")}, status=status)


@web.middleware
async def auth_middleware(request: web.Request, handler):
    path = request.path
    if path.startswith("/app"):
        resp = await handler(request)
        resp.headers.setdefault("Cache-Control", "no-cache")
        return resp
    if not path.startswith("/api/"):
        return await handler(request)
    cfg = request.app["cfg"]
    user_id = None
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        tg_user = validate_init_data(init_data, cfg.bot_token)
        if tg_user:
            user_id = int(tg_user["id"])
    if user_id is None and cfg.dev_mode:
        dev = request.headers.get("X-Dev-User", "").strip()
        if dev.lstrip("-").isdigit():
            user_id = int(dev)
    if user_id is None:
        return err(401, "unauthorized", "Open this page from Telegram.")
    user = await request.app["repo"].get_user(user_id)
    if not user or user["onboarding_step"] is not None:
        return web.json_response({"error": "not_registered", "message": "Send /start to the bot first."},
                                 status=404)
    request["user"] = user
    return await handler(request)


# --------------------------------------------------------------------------- helpers

def _now(request: web.Request) -> datetime:
    clock = request.app.get("clock")
    return clock() if clock else utcnow()


def _parse_date(value: str | None, default: date) -> date | None:
    if not value:
        return default
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def category_json(c: dict) -> dict:
    return {"id": c["id"], "name": c["name"], "emoji": c["emoji"], "is_waste": bool(c["is_waste"]),
            "color": c["color"], "active": bool(c["active"])}


async def _body(request: web.Request) -> dict | None:
    try:
        data = await request.json()
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


async def _goal_json(repo: Repo, user: dict, g: dict, today_ds, week: dict) -> dict:
    cid = g["category_id"]
    avg = next((t["avg_per_day"] for t in week["totals"] if t["category_id"] == cid), 0)
    return {"id": g["id"], "category_id": cid, "daily_limit_min": g["daily_limit_min"],
            "today_used_min": today_ds.minutes_for(cid), "week_avg_min": avg,
            "baseline_avg_min": g["baseline_avg_min"]}


# --------------------------------------------------------------------------- handlers

async def health(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def api_me(request: web.Request) -> web.Response:
    repo, cfg, user = request.app["repo"], request.app["cfg"], request["user"]
    today = local_date(_now(request), user_tz(user))
    day_no = None
    if user["challenge_start"]:
        day_no = (today - date.fromisoformat(user["challenge_start"])).days + 1
    cats = await repo.list_categories(user["id"])
    return web.json_response({
        "user": {"first_name": user["first_name"], "tz": user["tz"], "wake_time": user["wake_time"],
                 "sleep_time": user["sleep_time"], "ping_interval_min": user["ping_interval_min"],
                 "paused": bool(user["paused"]), "challenge_day": day_no,
                 "challenge_days": cfg.challenge_days, "today": today.isoformat()},
        "categories": [category_json(c) for c in cats]})


async def api_day(request: web.Request) -> web.Response:
    repo, user = request.app["repo"], request["user"]
    now = _now(request)
    d = _parse_date(request.query.get("date"), local_date(now, user_tz(user)))
    if d is None:
        return err(400, "bad_date", "date must be YYYY-MM-DD")
    cats = await repo.list_categories(user["id"])
    ds = await day_stats_for(repo, user, d, now, cats)
    goals = await repo.list_goals(user["id"])
    return web.json_response({
        "date": d.isoformat(), "awake_start_min": ds.awake_start_min, "awake_end_min": ds.awake_end_min,
        "awake_minutes": ds.awake_minutes, "tracked_minutes": ds.tracked_minutes,
        "untracked_minutes": ds.untracked_minutes, "waste_minutes": ds.waste_minutes,
        "waste_share": ds.waste_share, "totals": ds.totals, "entries": ds.entries,
        "running": ds.running,
        "limits": [{"goal_id": g["id"], "category_id": g["category_id"], "limit_min": g["daily_limit_min"],
                    "used_min": ds.minutes_for(g["category_id"])} for g in goals]})


async def api_week(request: web.Request) -> web.Response:
    repo, user = request.app["repo"], request["user"]
    now = _now(request)
    end = _parse_date(request.query.get("end"), local_date(now, user_tz(user)))
    if end is None:
        return err(400, "bad_date", "end must be YYYY-MM-DD")
    week = await week_stats_for(repo, user, end, now)
    week.pop("active_days", None)
    latest = await repo.latest_insight(user["id"])
    week["insight"] = {"text": latest["text"], "created_at": latest["created_at"]} if latest else None
    return web.json_response(week)


async def api_goals(request: web.Request) -> web.Response:
    repo, user = request.app["repo"], request["user"]
    now = _now(request)
    today = local_date(now, user_tz(user))
    cats = await repo.list_categories(user["id"])
    ds = await day_stats_for(repo, user, today, now, cats)
    week = await week_stats_for(repo, user, today, now, cats)
    goals = [await _goal_json(repo, user, g, ds, week) for g in await repo.list_goals(user["id"])]
    return web.json_response({"goals": goals})


async def api_entry_add(request: web.Request) -> web.Response:
    repo, user = request.app["repo"], request["user"]
    tz = user_tz(user)
    now = _now(request)
    body = await _body(request)
    if body is None:
        return err(400, "bad_request", "Body must be JSON.")
    cid = _int(body.get("category_id"))
    cat = await repo.get_category(user["id"], cid) if cid is not None else None
    if not cat:
        return err(400, "bad_category", "Unknown category.")
    d = _parse_date(body.get("date"), local_date(now, tz))
    if d is None:
        return err(400, "bad_date", "date must be YYYY-MM-DD")
    try:
        start_s, end_s = str(body["start"]), str(body["end"])
        start = local_dt(d, parse_hm(start_s), tz)
        end = (local_midnight(d + timedelta(days=1), tz) if end_s.strip() == "24:00"
               else local_dt(d, parse_hm(end_s), tz))
    except (KeyError, ValueError):
        return err(400, "bad_time", "start and end must be HH:MM")
    if end <= start:
        return err(400, "bad_range", "End must be after start.")
    if start >= now:
        return err(400, "future", "That time has not happened yet.")
    end = min(end, now)
    if end - start < timedelta(seconds=60):
        return err(400, "bad_range", "Entry is too short.")
    note = body.get("note")
    note = str(note)[:500] if note else None
    entry_id = await add_override_entry(repo, user["id"], cat["id"], start, end, now, "manual", note)
    try:
        await check_limits(request.app.get("bot"), repo, user["id"], now)
    except Exception:
        log.exception("limit check failed")
    clipped = clip_span((start, end), day_bounds(d, tz))
    smin, emin = minute_of_day(clipped[0], d, tz), minute_of_day(clipped[1], d, tz)
    return web.json_response({"ok": True, "entry": {
        "id": entry_id, "category_id": cat["id"], "start": hm_str(smin), "end": hm_str(emin),
        "start_min": smin, "end_min": emin, "source": "manual", "note": note}})


async def api_entry_delete(request: web.Request) -> web.Response:
    repo, user = request.app["repo"], request["user"]
    eid = _int(request.match_info["id"])
    row = await repo.get_entry(user["id"], eid) if eid is not None else None
    if not row:
        return err(404, "not_found", "Entry not found.")
    await repo.delete_entry(eid)
    return web.json_response({"ok": True})


async def api_goal_add(request: web.Request) -> web.Response:
    repo, user = request.app["repo"], request["user"]
    now = _now(request)
    body = await _body(request)
    if body is None:
        return err(400, "bad_request", "Body must be JSON.")
    cid = _int(body.get("category_id"))
    limit = _int(body.get("daily_limit_min"))
    cat = await repo.get_category(user["id"], cid) if cid is not None else None
    if not cat:
        return err(400, "bad_category", "Unknown category.")
    if limit is None or not 5 <= limit <= 1440:
        return err(400, "bad_limit", "daily_limit_min must be between 5 and 1440.")
    baseline = await average_per_day(repo, user, cid, now)
    goal = await repo.replace_goal(user["id"], cid, limit, baseline, now)
    cats = await repo.list_categories(user["id"])
    today = local_date(now, user_tz(user))
    ds = await day_stats_for(repo, user, today, now, cats)
    week = await week_stats_for(repo, user, today, now, cats)
    try:
        await check_limits(request.app.get("bot"), repo, user["id"], now)
    except Exception:
        log.exception("limit check failed")
    return web.json_response({"ok": True, "goal": await _goal_json(repo, user, goal, ds, week)})


async def api_goal_delete(request: web.Request) -> web.Response:
    repo, user = request.app["repo"], request["user"]
    gid = _int(request.match_info["id"])
    goal = await repo.get_goal(user["id"], gid) if gid is not None else None
    if not goal:
        return err(404, "not_found", "Goal not found.")
    await repo.deactivate_goal(gid)
    return web.json_response({"ok": True})


async def app_index(request: web.Request) -> web.StreamResponse:
    index = request.app["static_dir"] / "index.html"
    if not index.is_file():
        return web.Response(status=404, text="Mini App files are missing.")
    return web.FileResponse(index)


async def app_redirect(request: web.Request) -> web.StreamResponse:
    raise web.HTTPFound("/app/" + (("?" + request.query_string) if request.query_string else ""))


def create_app(cfg, repo: Repo, bot=None, static_dir: Path | None = None, clock=None) -> web.Application:
    app = web.Application(middlewares=[auth_middleware])
    app["cfg"], app["repo"], app["bot"] = cfg, repo, bot
    app["static_dir"] = Path(static_dir) if static_dir else STATIC_DIR
    if clock:
        app["clock"] = clock
    app.router.add_get("/health", health)
    app.router.add_get("/api/me", api_me)
    app.router.add_get("/api/day", api_day)
    app.router.add_get("/api/week", api_week)
    app.router.add_get("/api/goals", api_goals)
    app.router.add_post("/api/entries", api_entry_add)
    app.router.add_delete("/api/entries/{id}", api_entry_delete)
    app.router.add_post("/api/goals", api_goal_add)
    app.router.add_delete("/api/goals/{id}", api_goal_delete)
    app.router.add_get("/app", app_redirect)
    app.router.add_get("/app/", app_index)
    if app["static_dir"].is_dir():
        app.router.add_static("/app/", app["static_dir"], show_index=False)
    else:
        log.warning("static dir %s not found, /app/ will return 404", app["static_dir"])
    return app
