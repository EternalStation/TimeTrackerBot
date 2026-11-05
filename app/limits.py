"""Daily limit warnings (SPEC section 9): at most one per category per local day."""
from __future__ import annotations

import logging
from datetime import datetime

from .entries import day_stats_for, user_tz
from .repo import Repo
from .tg import safe_send
from .timeutil import fmt_dur, local_date, utcnow

log = logging.getLogger("limits")


async def check_limits(bot, repo: Repo, user_id: int, now: datetime | None = None) -> list[str]:
    """Send a warning for every goal whose limit is reached today (including a running timer).

    Returns the texts that were sent. Does nothing without a bot (web-only mode).
    """
    if bot is None:
        return []
    now = now or utcnow()
    user = await repo.get_user(user_id)
    if not user or user["onboarding_step"] is not None:
        return []
    goals = await repo.list_goals(user_id)
    if not goals:
        return []
    today = local_date(now, user_tz(user))
    cats = {c["id"]: c for c in await repo.list_categories(user_id)}
    ds = await day_stats_for(repo, user, today, now, list(cats.values()))
    sent = []
    for g in goals:
        used = ds.minutes_for(g["category_id"])
        cat = cats.get(g["category_id"])
        if not cat or used < g["daily_limit_min"]:
            continue
        if not await repo.add_limit_warning(user_id, g["category_id"], today.isoformat()):
            continue
        text = f"⚠️ {cat['name']}: {fmt_dur(used)} today. Your limit is {fmt_dur(g['daily_limit_min'])}."
        await safe_send(bot, user["chat_id"], text)
        sent.append(text)
    return sent
