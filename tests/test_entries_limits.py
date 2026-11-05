from datetime import timedelta

from app.entries import (add_override_entry, day_stats_for, fill_free_time, start_timer, stop_timer)
from app.limits import check_limits
from app.timeutil import iso, parse_iso
from conftest import FakeBot, dt, make_user

NOW = dt(2026, 11, 4, 18, 0)


async def times(repo, uid=1):
    rows = await repo.entries_between(uid, dt(2026, 11, 4), dt(2026, 11, 5))
    return [(r["category_id"], r["start_utc"][11:16], (r["end_utc"][11:16] if r["end_utc"] else "run"), r["source"]) for r in rows]


async def test_checkin_fills_only_free_time(repo):
    user, c = await make_user(repo)
    work, rest = c["Work"]["id"], c["Rest"]["id"]
    await repo.add_entry(1, work, dt(2026, 11, 4, 14, 10), dt(2026, 11, 4, 14, 20), "manual")
    await repo.add_entry(1, work, dt(2026, 11, 4, 14, 40), dt(2026, 11, 4, 15, 30), "manual")
    ids = await fill_free_time(repo, 1, rest, dt(2026, 11, 4, 14), dt(2026, 11, 4, 15), 5, NOW)
    assert len(ids) == 2
    got = await times(repo)
    assert (rest, "14:00", "14:10", "checkin") in got
    assert (rest, "14:20", "14:40", "checkin") in got
    assert (work, "14:40", "15:30", "manual") in got        # existing entry untouched


async def test_manual_entry_overrides_and_splits(repo):
    user, c = await make_user(repo)
    work, gaming = c["Work"]["id"], c["Gaming"]["id"]
    await repo.add_entry(1, work, dt(2026, 11, 4, 9), dt(2026, 11, 4, 12), "checkin", 7)
    await add_override_entry(repo, 1, gaming, dt(2026, 11, 4, 10), dt(2026, 11, 4, 11), NOW)
    assert await times(repo) == [(work, "09:00", "10:00", "checkin"), (gaming, "10:00", "11:00", "manual"),
                                 (work, "11:00", "12:00", "checkin")]
    # covering everything deletes the old pieces
    await add_override_entry(repo, 1, c["Rest"]["id"], dt(2026, 11, 4, 8), dt(2026, 11, 4, 13), NOW)
    assert await times(repo) == [(c["Rest"]["id"], "08:00", "13:00", "manual")]


async def test_timer_start_stop_and_override(repo):
    user, c = await make_user(repo, last_checkin_at="2026-11-04T12:00:00Z")
    work, yt = c["Work"]["id"], c["YouTube / TV"]["id"]
    await repo.add_entry(1, work, dt(2026, 11, 4, 16), dt(2026, 11, 4, 17, 30), "checkin")
    await start_timer(repo, 1, yt, dt(2026, 11, 4, 17))
    assert (await repo.running_entry(1))["category_id"] == yt
    # a second start stops the first one
    await start_timer(repo, 1, c["Gaming"]["id"], dt(2026, 11, 4, 17, 10))
    got = await times(repo)
    assert (yt, "17:00", "17:10", "timer") in got and (c["Gaming"]["id"], "17:10", "run", "timer") in got
    res = await stop_timer(repo, 1, dt(2026, 11, 4, 17, 40))
    assert res["minutes"] == 30
    assert await stop_timer(repo, 1, dt(2026, 11, 4, 17, 50)) is None
    got = await times(repo)
    # timer entries overrode the 16:00-17:30 work block from 17:00 on
    assert (work, "16:00", "17:00", "checkin") in got
    assert (c["Gaming"]["id"], "17:10", "17:40", "timer") in got
    assert (await repo.get_user(1))["last_checkin_at"] == "2026-11-04T17:40:00Z"


async def test_limit_warning_once_per_day(repo):
    user, c = await make_user(repo)
    sm = c["Social media"]["id"]
    await repo.replace_goal(1, sm, 30, None)
    bot = FakeBot()
    await repo.add_entry(1, sm, dt(2026, 11, 4, 12), dt(2026, 11, 4, 12, 20), "manual")
    assert await check_limits(bot, repo, 1, NOW) == []
    await repo.add_entry(1, sm, dt(2026, 11, 4, 13), dt(2026, 11, 4, 13, 15), "manual")
    sent = await check_limits(bot, repo, 1, NOW)
    assert sent == ["⚠️ Social media: 35m today. Your limit is 30m. Just flagging it."]
    assert len(bot.sent) == 1
    # more social media later the same day: no second warning
    await repo.add_entry(1, sm, dt(2026, 11, 4, 14), dt(2026, 11, 4, 15), "manual")
    assert await check_limits(bot, repo, 1, NOW) == []
    assert len(bot.sent) == 1
    # next local day it can fire again
    await repo.add_entry(1, sm, dt(2026, 11, 5, 12), dt(2026, 11, 5, 13), "manual")
    again = await check_limits(bot, repo, 1, dt(2026, 11, 5, 14))
    assert again == ["⚠️ Social media: 1h today. Your limit is 30m. Just flagging it."]


async def test_limit_warning_triggered_by_running_timer(repo):
    user, c = await make_user(repo)
    sm = c["Social media"]["id"]
    await repo.replace_goal(1, sm, 60, None)
    bot = FakeBot()
    await start_timer(repo, 1, sm, dt(2026, 11, 4, 17, 0))
    assert await check_limits(bot, repo, 1, dt(2026, 11, 4, 17, 50)) == []
    sent = await check_limits(bot, repo, 1, dt(2026, 11, 4, 18, 5))
    assert sent == ["⚠️ Social media: 1h 05m today. Your limit is 1h. Just flagging it."]
    ds = await day_stats_for(repo, await repo.get_user(1), NOW.date(), dt(2026, 11, 4, 18, 5))
    assert ds.minutes_for(sm) == 65


async def test_limit_warning_survives_blocked_bot(repo):
    user, c = await make_user(repo)
    sm = c["Social media"]["id"]
    await repo.replace_goal(1, sm, 10, None)
    await repo.add_entry(1, sm, dt(2026, 11, 4, 12), dt(2026, 11, 4, 13), "manual")
    await check_limits(FakeBot(fail=True), repo, 1, NOW)       # must not raise
