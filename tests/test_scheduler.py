from app.config import Config
from app.entries import start_timer
from app.scheduler import process_ping, tick
from app.timeutil import iso
from conftest import FakeBot, dt, make_user

CFG = Config()


async def test_tick_sends_ping_with_valid_keyboard(repo):
    user, c = await make_user(repo, tz="+01:00", last_checkin_at="2026-11-04T09:00:00Z",
                              next_ping_at="2026-11-04T10:00:00Z")
    await repo.add_entry(1, c["Work"]["id"], dt(2026, 11, 4, 8), dt(2026, 11, 4, 9), "checkin")
    bot = FakeBot()
    await tick(bot, repo, CFG, dt(2026, 11, 4, 10, 0, 5))
    assert len(bot.sent) == 1
    msg = bot.sent[0]
    assert msg["text"] == "🕐 What were you doing 10:00–11:00?"
    rows = msg["reply_markup"].inline_keyboard
    assert rows[0][0].text.startswith("↩️ Same: 💼 Work")
    assert rows[-1][0].callback_data.endswith(":mix") and rows[-1][1].callback_data.endswith(":skip")
    buttons = [b for r in rows for b in r]
    assert all(len(b.callback_data.encode()) <= 64 for b in buttons)
    assert len(buttons) == 1 + 12 + 2
    u = await repo.get_user(1)
    assert u["next_ping_at"] == "2026-11-04T11:00:05Z"
    ping = (await repo.open_pings(1))[0]
    assert ping["message_id"] == 101 and ping["start_utc"] == "2026-11-04T09:00:00Z"


async def test_next_ping_expires_previous_one(repo):
    user, c = await make_user(repo, last_checkin_at="2026-11-04T09:00:00Z", next_ping_at="2026-11-04T10:00:00Z")
    bot = FakeBot()
    await tick(bot, repo, CFG, dt(2026, 11, 4, 10))
    await repo.update_user(1, next_ping_at="2026-11-04T11:00:00Z")
    await tick(bot, repo, CFG, dt(2026, 11, 4, 11))
    assert len(bot.sent) == 2 and len(bot.edits) == 1
    assert bot.edits[0]["text"].startswith("⏭ Skipped ") and "reply_markup" not in bot.edits[0]
    assert len(await repo.open_pings(1)) == 1


async def test_no_ping_while_timer_and_nothing_outside_window(repo):
    user, c = await make_user(repo, last_checkin_at="2026-11-04T09:00:00Z", next_ping_at="2026-11-04T10:00:00Z")
    await start_timer(repo, 1, c["Work"]["id"], dt(2026, 11, 4, 9, 30))
    bot = FakeBot()
    await tick(bot, repo, CFG, dt(2026, 11, 4, 10))
    assert bot.sent == []
    assert (await repo.get_user(1))["next_ping_at"] == "2026-11-04T11:00:00Z"
    # outside the window (UTC user, window 08:00-23:00): moved to the next morning
    await repo.set_entry_times((await repo.running_entry(1))["id"], dt(2026, 11, 4, 9, 30), dt(2026, 11, 4, 10))
    await repo.update_user(1, next_ping_at="2026-11-04T23:30:00Z")
    await tick(bot, repo, CFG, dt(2026, 11, 4, 23, 30))
    u = await repo.get_user(1)
    assert not any("What were you doing" in m["text"] for m in bot.sent)
    assert u["last_checkin_at"] == "2026-11-05T08:00:00Z"
    assert u["next_ping_at"] == "2026-11-05T09:00:00Z"


async def test_final_ping_scheduled_at_window_end(repo):
    user, c = await make_user(repo, last_checkin_at="2026-11-04T20:10:00Z", next_ping_at="2026-11-04T21:10:00Z",
                              interval=60)
    bot = FakeBot()
    await tick(bot, repo, CFG, dt(2026, 11, 4, 21, 10))
    # window 08:00-23:00 UTC: 21:10 + 60 min = 22:10 -> still before 23:00, so no clamp yet
    assert (await repo.get_user(1))["next_ping_at"] == "2026-11-04T22:10:00Z"
    await repo.update_user(1, next_ping_at="2026-11-04T22:10:00Z")
    await tick(bot, repo, CFG, dt(2026, 11, 4, 22, 10))
    assert (await repo.get_user(1))["next_ping_at"] == "2026-11-04T23:00:00Z"   # exactly the window end
    await tick(bot, repo, CFG, dt(2026, 11, 4, 23, 0, 10))
    assert bot.sent[-1]["text"] == "🕐 What were you doing 22:00–23:00?"


async def test_telegram_errors_do_not_kill_tick(repo):
    user, c = await make_user(repo, uid=1, last_checkin_at="2026-11-04T09:00:00Z", next_ping_at="2026-11-04T10:00:00Z")
    await make_user(repo, uid=2, last_checkin_at="2026-11-04T09:00:00Z", next_ping_at="2026-11-04T10:00:00Z",
                    with_cats=False)
    bot = FakeBot(fail=True)
    await tick(bot, repo, CFG, dt(2026, 11, 4, 10))        # must not raise
    assert (await repo.get_user(1))["next_ping_at"] == "2026-11-04T11:00:00Z"
    assert (await repo.get_user(2))["next_ping_at"] == "2026-11-04T11:00:00Z"


async def test_daily_summary_sent_once_after_window_end(repo):
    user, c = await make_user(repo, start="2026-11-04", next_ping_at="2026-11-05T09:00:00Z")
    await repo.add_entry(1, c["Work"]["id"], dt(2026, 11, 4, 9), dt(2026, 11, 4, 17), "checkin")
    bot = FakeBot()
    await tick(bot, repo, CFG, dt(2026, 11, 4, 23, 10))
    assert bot.sent == []                                   # window ends 23:00, summary at 23:20
    await tick(bot, repo, CFG, dt(2026, 11, 4, 23, 21))
    await tick(bot, repo, CFG, dt(2026, 11, 4, 23, 22))
    assert len(bot.sent) == 1
    assert "Day 1/7" in bot.sent[0]["text"] and "💼 Work 8h" in bot.sent[0]["text"]
    assert (await repo.get_user(1))["last_summary_date"] == "2026-11-04"
