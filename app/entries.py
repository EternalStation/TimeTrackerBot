"""Operations on entries shared by the bot and the web API."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from .intervals import DayStats, day_stats, plan_override, subtract_intervals, week_stats
from .repo import Repo
from .timeutil import iso, local_date, local_midnight, parse_iso, parse_tz


def user_tz(user: dict):
    return parse_tz(user["tz"])


def tracking_from(user: dict) -> datetime | None:
    """Time from which untracked minutes are counted (the audit start)."""
    if not user.get("challenge_start"):
        return None
    tz = user_tz(user)
    midnight = local_midnight(date.fromisoformat(user["challenge_start"]), tz)
    created = parse_iso(user["created_at"])
    return max(midnight, created)


def row_to_entry(row: dict) -> dict:
    return {"id": row["id"], "category_id": row["category_id"], "start": parse_iso(row["start_utc"]),
            "end": parse_iso(row["end_utc"]) if row["end_utc"] else None,
            "source": row["source"], "note": row["note"], "ping_id": row["ping_id"]}


async def load_entries(repo: Repo, user: dict, first: date, last: date) -> list[dict]:
    tz = user_tz(user)
    rows = await repo.entries_between(user["id"], local_midnight(first, tz),
                                      local_midnight(last + timedelta(days=1), tz))
    return [row_to_entry(r) for r in rows]


def _waste_ids(cats: list[dict]) -> set[int]:
    return {c["id"] for c in cats if c["is_waste"]}


async def day_stats_for(repo: Repo, user: dict, d: date, now: datetime,
                        cats: list[dict] | None = None) -> DayStats:
    cats = cats if cats is not None else await repo.list_categories(user["id"])
    entries = await load_entries(repo, user, d, d)
    return day_stats(d, user_tz(user), user["wake_time"], user["sleep_time"], entries,
                     _waste_ids(cats), now, tracking_from(user))


async def week_stats_for(repo: Repo, user: dict, end: date, now: datetime,
                         cats: list[dict] | None = None, n_days: int = 7) -> dict:
    cats = cats if cats is not None else await repo.list_categories(user["id"])
    entries = await load_entries(repo, user, end - timedelta(days=2 * n_days - 1), end)
    cs = date.fromisoformat(user["challenge_start"]) if user.get("challenge_start") else None
    return week_stats(end, user_tz(user), user["wake_time"], user["sleep_time"], entries,
                      _waste_ids(cats), now, cs, tracking_from(user), n_days)


async def _apply_override(repo: Repo, user_id: int, start: datetime, end: datetime, now: datetime,
                          exclude_id: int | None = None) -> None:
    rows = await repo.entries_between(user_id, start, end)
    existing = [(r["id"], parse_iso(r["start_utc"]), parse_iso(r["end_utc"]) if r["end_utc"] else None)
                for r in rows if r["id"] != exclude_id]
    plan = plan_override(existing, start, end, now)
    by_id = {r["id"]: r for r in rows}
    for eid in plan.delete:
        await repo.delete_entry(eid)
    for eid, s, e in plan.update:
        await repo.set_entry_times(eid, s, e)
    for template_id, s, e in plan.insert:
        await repo.clone_entry(by_id[template_id], s, e)


async def add_override_entry(repo: Repo, user_id: int, category_id: int, start: datetime, end: datetime,
                             now: datetime, source: str = "manual", note: str | None = None) -> int:
    """Manual entry: wins over anything it overlaps."""
    async with repo.lock:
        await _apply_override(repo, user_id, start, end, now)
        return await repo.add_entry(user_id, category_id, start, end, source, None, note, now)


async def fill_free_time(repo: Repo, user_id: int, category_id: int, start: datetime, end: datetime,
                         ping_id: int | None, now: datetime) -> list[int]:
    """Check-in answer: only the parts of [start, end] not already covered by entries."""
    async with repo.lock:
        rows = await repo.entries_between(user_id, start, end)
        busy = [(parse_iso(r["start_utc"]), parse_iso(r["end_utc"]) if r["end_utc"] else now)
                for r in rows]
        ids = []
        for s, e in subtract_intervals((start, end), busy):
            ids.append(await repo.add_entry(user_id, category_id, s, e, "checkin", ping_id, None, now))
        return ids


async def start_timer(repo: Repo, user_id: int, category_id: int, now: datetime) -> int:
    await stop_timer(repo, user_id, now)
    async with repo.lock:
        return await repo.add_entry(user_id, category_id, now, None, "timer", None, None, now)


async def stop_timer(repo: Repo, user_id: int, now: datetime) -> dict | None:
    """Stops the running timer. Returns {"category_id", "minutes"} or None when nothing was running."""
    async with repo.lock:
        row = await repo.running_entry(user_id)
        if not row:
            return None
        start = parse_iso(row["start_utc"])
        if now <= start:
            await repo.delete_entry(row["id"])
            return {"category_id": row["category_id"], "minutes": 0}
        await _apply_override(repo, user_id, start, now, now, exclude_id=row["id"])
        await repo.set_entry_times(row["id"], start, now)
        user = await repo.get_user(user_id)
        if user:
            last = parse_iso(user["last_checkin_at"]) if user["last_checkin_at"] else now
            await repo.update_user(user_id, last_checkin_at=iso(max(last, now)))
        return {"category_id": row["category_id"], "minutes": int((now - start).total_seconds() // 60)}


async def average_per_day(repo: Repo, user: dict, category_id: int, now: datetime) -> int:
    """Average daily minutes of one category over the last 7 days (goal baseline)."""
    today = local_date(now, user_tz(user))
    week = await week_stats_for(repo, user, today, now)
    for t in week["totals"]:
        if t["category_id"] == category_id:
            return t["avg_per_day"]
    return 0


async def delete_ping_entries_and_fill(repo: Repo, user_id: int, ping_id: int, category_id: int,
                                       start: datetime, end: datetime, now: datetime) -> list[int]:
    """Answer (or re-answer) a ping: drop what this ping created before, then fill free time."""
    await repo.delete_entries_by_ping(user_id, ping_id)
    return await fill_free_time(repo, user_id, category_id, start, end, ping_id, now)
