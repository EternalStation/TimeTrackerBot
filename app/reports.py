"""Daily summary, weekly report and the texts shared with /today and /week."""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import date, datetime

from aiogram.types import BufferedInputFile, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from .ai import build_ai_input, get_insight
from .card import render_day_receipt, render_week_receipt
from .entries import day_stats_for, user_tz, week_stats_for
from .intervals import DayStats
from .tg import safe_send, safe_send_photo
from .timeutil import fmt_dur, local_date

log = logging.getLogger("reports")


def _cat_label(cat: dict | None) -> str:
    return f"{cat['emoji'] or '•'} {cat['name']}" if cat else "?"


def dashboard_markup(cfg, extra_rows: list[list[InlineKeyboardButton]] | None = None):
    rows = list(extra_rows or [])
    if cfg.webapp_url:
        rows.append([InlineKeyboardButton(text="📊 Open dashboard", web_app=WebAppInfo(url=cfg.webapp_url))])
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


def challenge_day(user: dict, d: date) -> int | None:
    if not user.get("challenge_start"):
        return None
    return (d - date.fromisoformat(user["challenge_start"])).days + 1


def day_text(user: dict, ds: DayStats, cats: dict[int, dict], goals: list[dict], cfg) -> str:
    n = challenge_day(user, ds.date)
    head = f"📅 {ds.date.strftime('%a %d %b')}"
    if n is not None and 1 <= n:
        head += f" · Day {min(n, cfg.challenge_days)}/{cfg.challenge_days}" if n <= cfg.challenge_days else f" · Day {n}"
    lines = [head, f"Tracked {fmt_dur(ds.tracked_minutes)} of {fmt_dur(ds.awake_minutes)} awake", ""]
    if not ds.totals:
        lines.append("Nothing logged for this day.")
    for t in ds.totals[:6]:
        lines.append(f"{_cat_label(cats.get(t['category_id']))} {fmt_dur(t['minutes'])}")
    if len(ds.totals) > 6:
        lines.append(f"+ {len(ds.totals) - 6} more")
    lines.append("")
    share = round(ds.waste_share * 100)
    lines.append(f"🔥 Waste: {fmt_dur(ds.waste_minutes)} ({share}% of tracked)")
    lines.append(f"Untracked: {fmt_dur(ds.untracked_minutes)}")
    for g in goals:
        cat = cats.get(g["category_id"])
        if not cat:
            continue
        used = ds.minutes_for(g["category_id"])
        mark = "✅" if used <= g["daily_limit_min"] else "⚠️"
        lines.append(f"{mark} {cat['name']}: {fmt_dur(used)} / {fmt_dur(g['daily_limit_min'])}")
    return "\n".join(lines)


def week_text(week: dict, cats: dict[int, dict], insight_lines: list[str] | None = None) -> str:
    n = max(1, week["active_days"])
    lines = [f"📆 {week['start']} to {week['end']}",
             f"Tracked {fmt_dur(week['tracked_minutes'])} · logged days {week['days_logged']}/{len(week['days'])}",
             f"🔥 Waste: {fmt_dur(week['waste_minutes'])} ({round(week['waste_share'] * 100)}% of tracked), "
             f"{fmt_dur(week['waste_minutes'] / n)} a day"]
    prev = week.get("prev_waste_minutes")
    if prev:
        diff = week["waste_minutes"] - prev
        lines.append(f"Compared to the week before: {'+' if diff >= 0 else '-'}{fmt_dur(abs(diff))}")
    lines.append("")
    for t in week["totals"][:6]:
        lines.append(f"{_cat_label(cats.get(t['category_id']))} {fmt_dur(t['minutes'])}")
    if insight_lines:
        lines.append("")
        lines.extend(f"• {s}" for s in insight_lines)
    return "\n".join(lines)


def day_receipt_data(user: dict, ds: DayStats, cats: dict[int, dict], goals: list[dict], cfg) -> dict:
    """The same numbers as /api/day (DayStats), reshaped for the receipt renderer."""
    items = []
    for t in ds.totals:
        c = cats.get(t["category_id"])
        if c:
            items.append({"name": c["name"], "minutes": t["minutes"], "is_waste": bool(c["is_waste"])})
    limits = []
    for g in goals:
        c = cats.get(g["category_id"])
        if c:
            limits.append({"name": c["name"], "limit": g["daily_limit_min"],
                           "used": ds.minutes_for(g["category_id"])})
    return {"date": ds.date, "day_n": challenge_day(user, ds.date), "day_total": cfg.challenge_days,
            "items": items, "tracked": ds.tracked_minutes, "untracked": ds.untracked_minutes,
            "waste": ds.waste_minutes, "waste_share": ds.waste_share, "limits": limits,
            "user_id": user["id"]}


def week_receipt_data(user: dict, week: dict, cats: dict[int, dict]) -> dict:
    n = max(1, week["active_days"])
    top = []
    for t in week["totals"]:
        c = cats.get(t["category_id"])
        if c:
            top.append({"name": c["name"], "minutes": t["minutes"], "is_waste": bool(c["is_waste"])})
    return {"start": date.fromisoformat(week["start"]), "end": date.fromisoformat(week["end"]),
            "days": [{"date": date.fromisoformat(d["date"]), "waste_minutes": d["waste_minutes"],
                      "tracked_minutes": d["tracked_minutes"]} for d in week["days"]],
            "top": top, "waste_minutes": week["waste_minutes"],
            "waste_per_day": int(round(week["waste_minutes"] / n)), "user_id": user["id"]}


def day_caption(data: dict, today: date | None) -> str:
    head = "Today's receipt." if today is None or data["date"] == today else f"Receipt for {data['date'].strftime('%a %d %b')}."
    if not data["items"]:
        return f"{head} Nothing rung up."
    if data["waste"] == 0:
        return f"{head} Wasted nothing. Suspicious."
    return f"{head} Wasted {fmt_dur(data['waste'])} ({round(data['waste_share'] * 100)}%)."


async def send_daily_summary(bot, repo, cfg, user: dict, d: date, now: datetime,
                             bot_username: str = "") -> None:
    """Receipt PNG + short caption + dashboard button. Any failure falls back to the text summary."""
    cats = {c["id"]: c for c in await repo.list_categories(user["id"])}
    goals = await repo.list_goals(user["id"])
    ds = await day_stats_for(repo, user, d, now, list(cats.values()))
    try:
        data = day_receipt_data(user, ds, cats, goals, cfg)
        png = await asyncio.to_thread(render_day_receipt, data, bot_username)
        msg = await safe_send_photo(bot, user["chat_id"], BufferedInputFile(png, "receipt.png"),
                                    caption=day_caption(data, local_date(now, user_tz(user))),
                                    reply_markup=dashboard_markup(cfg))
        if msg is not None:
            return
        log.warning("daily receipt was not delivered to %s, sending text", user["id"])
    except Exception:
        log.exception("daily receipt failed for user %s, sending text", user["id"])
    await safe_send(bot, user["chat_id"], day_text(user, ds, cats, goals, cfg),
                    reply_markup=dashboard_markup(cfg))


async def send_weekly_report(bot, repo, cfg, user: dict, end: date, now: datetime,
                             bot_username: str = "", reuse_today: bool = False) -> None:
    """Stats + card + insight. Saves the insight. With reuse_today an insight made today is reused."""
    cats_list = await repo.list_categories(user["id"])
    cats = {c["id"]: c for c in cats_list}
    goals = await repo.list_goals(user["id"])
    week = await week_stats_for(repo, user, end, now, cats_list)

    insight = None
    if reuse_today:
        saved = await repo.latest_insight(user["id"])
        if saved and saved["week_end_date"] == end.isoformat():
            lines = [s[2:].strip() if s.startswith("• ") else s for s in saved["text"].split("\n") if s.strip()]
            goal = json.loads(saved["goal_json"]) if saved["goal_json"] else None
            insight = {"insights": lines, "goal": goal}
    if insight is None:
        insight = await get_insight(cfg, build_ai_input(week, cats_list, goals))
        await repo.add_insight(user["id"], end.isoformat(),
                               "\n".join(f"• {s}" for s in insight["insights"]),
                               json.dumps(insight["goal"]) if insight["goal"] else None, now)

    try:
        png = await asyncio.to_thread(render_week_receipt, week_receipt_data(user, week, cats),
                                      insight["insights"], bot_username)
        await safe_send_photo(bot, user["chat_id"], BufferedInputFile(png, "week.png"),
                              caption=f"Weekly receipt. {len(week['days'])} days, itemized.")
    except Exception:
        log.exception("weekly receipt rendering failed")

    rows = []
    goal = insight.get("goal")
    if goal and goal["category_id"] in cats:
        label = f"🎯 Set goal: {cats[goal['category_id']]['name']} ≤ {fmt_dur(goal['daily_limit_min'])}/day"
        rows.append([InlineKeyboardButton(
            text=label, callback_data=f"g:set:{goal['category_id']}:{goal['daily_limit_min']}")])
    text = week_text(week, cats, insight["insights"])
    if goal and goal.get("reason"):
        text += f"\n\n🎯 {goal['reason']}"
    await safe_send(bot, user["chat_id"], text, reply_markup=dashboard_markup(cfg, rows))
