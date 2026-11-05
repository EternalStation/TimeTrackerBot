"""/admin_stats for ADMIN_IDS (SPEC section 14)."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from ..config import Config
from ..entries import user_tz, week_stats_for
from ..repo import Repo
from ..timeutil import fmt_dur, iso, local_date, utcnow

router = Router()


async def build_admin_stats(repo: Repo, cfg: Config, now=None) -> str:
    now = now or utcnow()
    users = await repo.all_users()
    onboarded = [u for u in users if u["onboarding_step"] is None]
    cur = await repo.conn.execute("SELECT COUNT(DISTINCT user_id) FROM entries WHERE created_at >= ?",
                                  (iso(now - timedelta(hours=24)),))
    active = (await cur.fetchone())[0]

    eligible = completed = 0
    waste_per_day = []
    waste_by_name: dict[str, int] = defaultdict(int)
    for u in onboarded:
        tz = user_tz(u)
        today = local_date(now, tz)
        cats = await repo.list_categories(u["id"])
        names = {c["id"]: c for c in cats}
        if u["challenge_start"]:
            start = date.fromisoformat(u["challenge_start"])
            if start <= today - timedelta(days=cfg.challenge_days):
                eligible += 1
                first = await week_stats_for(repo, u, start + timedelta(days=cfg.challenge_days - 1), now, cats,
                                             cfg.challenge_days)
                if first["days_logged"] >= 5:
                    completed += 1
        week = await week_stats_for(repo, u, today, now, cats)
        if week["tracked_minutes"] > 0:
            waste_per_day.append(week["waste_minutes"] / max(1, week["active_days"]))
        for t in week["totals"]:
            c = names.get(t["category_id"])
            if c and c["is_waste"]:
                waste_by_name[c["name"].strip().lower()] += t["minutes"]

    top = sorted(waste_by_name.items(), key=lambda kv: -kv[1])[:5]
    lines = [f"Users: {len(users)} total, {len(onboarded)} onboarded, {active} active in the last 24h",
             f"Day-{cfg.challenge_days} completion: {completed} of {eligible}"
             + (f" ({round(100 * completed / eligible)}%)" if eligible else ""),
             f"Average waste per day: {fmt_dur(sum(waste_per_day) / len(waste_per_day)) if waste_per_day else 'n/a'}",
             "Top waste categories (last 7 days):"]
    lines += [f"{i}. {name}: {fmt_dur(m)}" for i, (name, m) in enumerate(top, 1)] or ["none yet"]
    return "\n".join(lines)


@router.message(Command("admin_stats"))
async def cmd_admin_stats(message: Message, repo: Repo, cfg: Config):
    if message.from_user.id not in cfg.admin_ids:
        return  # stay silent for everyone else
    await message.answer(await build_admin_stats(repo, cfg))
