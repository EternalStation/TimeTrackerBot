"""Demo data: python -m app.seed --user <telegram_id> [--days 7] [--tz +01:00]

Creates (or resets) a user with default categories, realistic entries for the last N days,
one goal and one saved insight.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import random
from datetime import datetime, time, timedelta

from .ai import build_ai_input, fallback_insight
from .config import Config
from .db import connect
from .entries import average_per_day, user_tz, week_stats_for
from .repo import DEFAULT_CATEGORIES, Repo
from .timeutil import iso, local_date, local_dt, local_midnight, parse_tz, utcnow

EVENING_CHOICES = [("Social media", 0.30), ("YouTube / TV", 0.28), ("Gaming", 0.10),
                   ("Reading", 0.10), ("Friends & family", 0.10), ("Rest", 0.12)]
WASTE_NAMES = {"Social media", "YouTube / TV", "Gaming"}


def day_blocks(rng: random.Random, weekday: bool, waste_factor: float) -> list[tuple[int, int, str]]:
    """One day as (start_min, end_min, category name), local minutes from midnight, no overlaps."""
    blocks: list[tuple[int, int, str]] = []
    cur = 8 * 60 + rng.randint(0, 20)
    limit = 23 * 60

    def add(name: str, lo: int, hi: int, p: float = 1.0):
        nonlocal cur
        if rng.random() > p:
            return
        dur = rng.randint(lo, hi)
        if name in WASTE_NAMES:
            dur = max(5, int(dur * waste_factor))
        end = min(cur + dur, limit)
        if end - cur >= 5:
            blocks.append((cur, end, name))
        cur = end
        if rng.random() < 0.12:           # a gap nobody logged
            cur += rng.randint(10, 40)

    if weekday:
        add("Eating", 20, 35)
        add("Commute", 20, 35)
        add("Work", 150, 200)
        add("Social media", 8, 20, 0.7)
        add("Work", 60, 90)
        add("Eating", 30, 45)
        add("Social media", 10, 25, 0.8)
        add("Work", 120, 170)
        add("Commute", 25, 40)
        add("Exercise", 40, 60, 0.5)
    else:
        add("Eating", 20, 40)
        add("Chores & cooking", 40, 70)
        add("Exercise", 40, 80, 0.6)
        add("Friends & family", 90, 180)
        add("Eating", 30, 50)
        add("Social media", 20, 50)
        add("Rest", 30, 60)
    add("Chores & cooking", 35, 55)
    add("Eating", 25, 40)
    cur = max(cur, 19 * 60 + 45)
    names = [n for n, _ in EVENING_CHOICES]
    weights = [w for _, w in EVENING_CHOICES]
    while cur < limit - 10:
        add(rng.choices(names, weights)[0], 20, 70)
    return blocks


async def seed_user(repo: Repo, user_id: int, days: int = 7, tz_name: str = "+01:00",
                    now: datetime | None = None) -> None:
    now = now or utcnow()
    tz = parse_tz(tz_name)
    today = local_date(now, tz)
    start_day = today - timedelta(days=days - 1)

    await repo.delete_user(user_id)
    await repo.conn.execute(
        "INSERT INTO users(id, chat_id, first_name, tz, wake_time, sleep_time, ping_interval_min, paused,"
        " onboarding_step, challenge_start, last_checkin_at, next_ping_at, created_at)"
        " VALUES(?,?,?,?,?,?,?,0,NULL,?,?,?,?)",
        (user_id, user_id, "Demo", tz_name, "08:00", "23:00", 60, start_day.isoformat(),
         iso(now), iso(now + timedelta(minutes=60)), iso(local_midnight(start_day, tz))))
    await repo.conn.commit()
    cats = {}
    for name, emoji, waste in DEFAULT_CATEGORIES:
        c = await repo.add_category(user_id, name, emoji, waste)
        cats[name] = c

    rng = random.Random(user_id * 7919 + days)
    for i in range(days):
        d = start_day + timedelta(days=i)
        factor = 1.0 - 0.3 * (i / (days - 1)) if days > 1 else 1.0
        for n, (s, e, name) in enumerate(day_blocks(rng, d.weekday() < 5, factor)):
            start = local_dt(d, time(s // 60, s % 60), tz)
            end = local_dt(d, time(e // 60, e % 60), tz)
            if start >= now:
                continue
            end = min(end, now)
            if end - start < timedelta(minutes=5):
                continue
            source = "manual" if rng.random() < 0.15 else "checkin"
            await repo.add_entry(user_id, cats[name]["id"], start, end, source, None, None, end)

    user = await repo.get_user(user_id)
    avg = await average_per_day(repo, user, cats["Social media"]["id"], now)
    await repo.replace_goal(user_id, cats["Social media"]["id"], 60, avg, now)

    cat_list = await repo.list_categories(user_id)
    week = await week_stats_for(repo, user, today, now, cat_list)
    data = build_ai_input(week, cat_list, await repo.list_goals(user_id))
    insight = fallback_insight(data)
    await repo.add_insight(user_id, today.isoformat(), "\n".join(f"• {s}" for s in insight["insights"]),
                           json.dumps(insight["goal"]) if insight["goal"] else None, now)


async def _main(args) -> None:
    cfg = Config.from_env()
    conn = await connect(args.db or cfg.db_path)
    repo = Repo(conn)
    await seed_user(repo, args.user, args.days, args.tz)
    await conn.close()
    print(f"Seeded user {args.user} with {args.days} days in {args.db or cfg.db_path}")


def main() -> None:
    p = argparse.ArgumentParser(description="Create demo data for the TimeTracker bot")
    p.add_argument("--user", type=int, required=True, help="Telegram user id")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--tz", default="+01:00", help="timezone offset or IANA name")
    p.add_argument("--db", default=None, help="database file (default: DB_PATH)")
    asyncio.run(_main(p.parse_args()))


if __name__ == "__main__":
    main()
