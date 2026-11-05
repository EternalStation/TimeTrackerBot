"""30 second loop: pings, daily summaries, weekly reports, live limit checks."""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from .bot import texts
from .bot.keyboards import ping_keyboard
from .entries import day_stats_for, user_tz
from .intervals import awake_window, decide_ping
from .limits import check_limits
from .reports import challenge_day, send_daily_summary, send_weekly_report
from .tg import safe_edit, safe_send
from .timeutil import fmt_hm, iso, local_date, parse_iso, utcnow

log = logging.getLogger("scheduler")

TICK_SECONDS = 30
SUMMARY_DELAY = timedelta(minutes=20)
SUMMARY_MAX_AGE = timedelta(hours=6)     # do not send a summary hours late (e.g. after downtime)


async def process_ping(bot, repo, user: dict, now: datetime) -> str:
    """Handle one user whose next_ping_at has passed. Returns the decision action."""
    uid = user["id"]
    tz = user_tz(user)
    timer = await repo.running_entry(uid) is not None
    last = parse_iso(user["last_checkin_at"]) if user["last_checkin_at"] else None
    dec = decide_ping(now, last, user["ping_interval_min"], user["wake_time"], user["sleep_time"], tz, timer)

    # store the schedule first, so a failure below cannot cause a ping every 30 seconds
    fields = {"next_ping_at": iso(dec.next_ping_at)}
    if dec.last_checkin_at:
        fields["last_checkin_at"] = iso(dec.last_checkin_at)
    await repo.update_user(uid, **fields)
    if dec.action != "ping":
        return dec.action

    for old in await repo.open_pings(uid):
        await repo.set_ping_status(old["id"], "expired")
        s, e = parse_iso(old["start_utc"]), parse_iso(old["end_utc"])
        await safe_edit(bot, user["chat_id"], old["message_id"],
                        texts.ping_expired(f"{fmt_hm(s, tz)}–{fmt_hm(e, tz)}"))

    cats = await repo.list_categories(uid, active_only=True)
    previous = None
    last_entry = await repo.last_entry(uid)
    if last_entry:
        previous = next((c for c in cats if c["id"] == last_entry["category_id"]), None)
    ping_id = await repo.add_ping(uid, None, dec.start, dec.end, now)
    text = texts.ping_question(f"{fmt_hm(dec.start, tz)}–{fmt_hm(dec.end, tz)}")
    msg = await safe_send(bot, user["chat_id"], text, reply_markup=ping_keyboard(ping_id, cats, previous))
    if msg is not None:
        await repo.set_ping_message(ping_id, msg.message_id)
    return "ping"


async def process_summaries(bot, repo, cfg, user: dict, now: datetime, bot_username: str = "") -> None:
    if not user["challenge_start"]:
        return
    tz = user_tz(user)
    today = local_date(now, tz)
    for d in (today, today - timedelta(days=1)):
        _, window_end = awake_window(d, user["wake_time"], user["sleep_time"], tz)
        due = window_end + SUMMARY_DELAY
        if now < due:
            continue
        if now - due > SUMMARY_MAX_AGE:
            return
        iso_d = d.isoformat()
        if user["last_summary_date"] and user["last_summary_date"] >= iso_d:
            return
        if iso_d < user["challenge_start"]:
            return
        await repo.update_user(user["id"], last_summary_date=iso_d)
        if iso_d == user["challenge_start"]:
            ds = await day_stats_for(repo, user, d, now)
            if ds.tracked_minutes == 0:
                return          # joined late on day 1 and logged nothing: no empty summary
        await send_daily_summary(bot, repo, cfg, user, d, now, bot_username)
        n = challenge_day(user, d)
        last_weekly = user["last_weekly_report_date"]
        if n and n >= cfg.challenge_days and n % cfg.challenge_days == 0 \
                and (not last_weekly or last_weekly < iso_d):
            await repo.update_user(user["id"], last_weekly_report_date=iso_d)
            await send_weekly_report(bot, repo, cfg, user, d, now, bot_username)
        return


async def tick(bot, repo, cfg, now: datetime | None = None, bot_username: str = "") -> None:
    now = now or utcnow()
    for user in await repo.users_due(iso(now)):
        try:
            await process_ping(bot, repo, user, now)
        except Exception:
            log.exception("ping failed for user %s", user["id"])
    try:
        for uid in await repo.users_with_running_timer():
            try:
                await check_limits(bot, repo, uid, now)
            except Exception:
                log.exception("limit check failed for user %s", uid)
    except Exception:
        log.exception("live limit checks failed")
    try:
        users = await repo.onboarded_users()
    except Exception:
        log.exception("could not load users")
        return
    for user in users:
        try:
            await process_summaries(bot, repo, cfg, user, now, bot_username)
        except Exception:
            log.exception("summary failed for user %s", user["id"])


async def run_scheduler(bot, repo, cfg, bot_username: str = "") -> None:
    log.info("scheduler started")
    while True:
        try:
            await tick(bot, repo, cfg, bot_username=bot_username)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("scheduler tick failed")
        await asyncio.sleep(TICK_SECONDS)
