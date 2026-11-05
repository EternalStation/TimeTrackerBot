"""Drives the real aiogram routers with fake updates; Telegram is replaced by a recording session."""
import itertools
from datetime import datetime, timezone

import pytest
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot import common
from app.config import Config
from app.main import build_dispatcher
from app.timeutil import iso, utcnow


class RecordingSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.calls = []
        self._ids = itertools.count(500)

    async def close(self):
        pass

    async def stream_content(self, *a, **k):
        yield b""

    async def make_request(self, bot, method, timeout=None):
        self.calls.append(method)
        if method.__api_method__ == "getMe":
            return User(id=1, is_bot=True, first_name="TT", username="tt_bot")
        if method.__api_method__ in ("sendMessage", "editMessageText"):
            return Message(message_id=next(self._ids), date=datetime.now(timezone.utc),
                           chat=Chat(id=77, type="private"), text="x")
        return True

    def texts(self):
        return [getattr(c, "text", "") for c in self.calls if c.__api_method__ in ("sendMessage", "editMessageText")]

    def last_markup(self):
        for c in reversed(self.calls):
            if getattr(c, "reply_markup", None) is not None:
                return c.reply_markup


USER = User(id=77, is_bot=False, first_name="Ann")
CHAT = Chat(id=77, type="private")
_uid = itertools.count(1)


_DP = {}


def _dispatcher(repo):
    # routers can only be attached to one Dispatcher, so build it once and swap the repo per test
    if "dp" not in _DP:
        _DP["dp"] = build_dispatcher(repo, Config(admin_ids={77}))
    _DP["dp"]["repo"] = repo
    return _DP["dp"]


@pytest.fixture
async def env(repo):
    session = RecordingSession()
    bot = Bot("123456:TEST", session=session)
    dp = _dispatcher(repo)
    common.awaiting.clear()
    common.onboarding_state.clear()
    common.pending_logs.clear()

    class Env:
        pass
    e = Env()
    e.bot, e.dp, e.session, e.repo = bot, dp, session, repo

    async def say(text):
        msg = Message(message_id=next(_uid), date=datetime.now(timezone.utc), chat=CHAT, from_user=USER, text=text)
        await dp.feed_update(bot, Update(update_id=next(_uid), message=msg))

    async def tap(data):
        msg = Message(message_id=900, date=datetime.now(timezone.utc), chat=CHAT, text="menu")
        cb = CallbackQuery(id=str(next(_uid)), from_user=USER, chat_instance="c", data=data, message=msg)
        await dp.feed_update(bot, Update(update_id=next(_uid), callback_query=cb))

    e.say, e.tap = say, tap
    yield e
    await bot.session.close()


async def test_full_onboarding_then_daily_use(env):
    repo = env.repo
    await env.say("hello")                                       # not registered yet
    assert "/start" in env.session.texts()[-1]
    await env.say("/start")
    assert (await repo.get_user(77))["onboarding_step"] == "tz"
    now = utcnow()
    await env.say(f"{(now.hour + 2) % 24:02d}:{now.minute:02d}")
    assert (await repo.get_user(77))["tz"] == "+02:00"
    await env.tap("ob:wake:07:00")
    await env.say("23:30")                                        # typed sleep time
    u = await repo.get_user(77)
    assert (u["wake_time"], u["sleep_time"], u["onboarding_step"]) == ("07:00", "23:30", "cats")
    await env.tap("ob:c:0")                                       # switch Work off
    await env.tap("ob:add")
    await env.say("🎲 Board games")
    await env.tap("ob:cn")
    await env.tap("ob:w:12")                                      # board games (index 12) counts as waste
    await env.tap("ob:wn")
    cats = await repo.list_categories(77)
    assert "Work" not in [c["name"] for c in cats] and len(cats) == 12
    bg = next(c for c in cats if c["name"] == "Board games")
    assert bg["is_waste"] == 1 and bg["emoji"] == "🎲"
    await env.tap("ob:i:30")
    u = await repo.get_user(77)
    assert u["onboarding_step"] is None and u["ping_interval_min"] == 30 and u["next_ping_at"]
    assert u["challenge_start"]

    # manual logging: unique match, ambiguous, error
    await env.say("yesterday 22:00-23:00 board")
    assert "Logged" in env.session.texts()[-1]
    await env.say("yesterday 20:00-21:00 s")                      # Study / Social media / Chores: ambiguous
    assert "Which category" in env.session.texts()[-1]
    token = next(iter(common.pending_logs))
    soc = next(c for c in cats if c["name"] == "Social media")
    await env.tap(f"m:{token}:{soc['id']}")
    assert len(await repo.entries_between(77, datetime(2026, 1, 1, tzinfo=timezone.utc), utcnow())) == 2
    await env.say("15:00-14:00 study")
    assert "before the start" in env.session.texts()[-1]

    # timer
    await env.say("⏹ Stop")
    assert "No timer" in env.session.texts()[-1]
    await env.say("▶️ Start")
    await env.tap(f"t:c:{soc['id']}")
    assert (await repo.running_entry(77))["category_id"] == soc["id"]
    await env.say("/stop")
    assert env.session.texts()[-1].startswith("⏹ 📱 Social media")

    # goals, settings, privacy
    await env.tap(f"g:lim:{soc['id']}:60")
    assert len(await repo.list_goals(77)) == 1
    await env.say("/goals")
    await env.say("/settings")
    await env.tap("s:int:90")
    await env.tap("s:wake")
    await env.say("06:45")
    assert (await repo.get_user(77))["wake_time"] == "06:45"
    await env.tap("s:cats")
    await env.tap(f"s:cw:{soc['id']}")
    await env.say("/timezone Europe/Warsaw")
    assert (await repo.get_user(77))["tz"] == "Europe/Warsaw"
    await env.say("/pause")
    assert (await repo.get_user(77))["paused"] == 1
    await env.say("/resume")
    await env.say("/today")
    await env.say("/week")
    await env.say("/admin_stats")
    assert env.session.texts()[-1].startswith("Users:")
    await env.say("/privacy")
    await env.say("/help")
    await env.say("/delete_me")
    await env.tap("del:yes")
    assert await repo.get_user(77) is None and await repo.list_categories(77) == []


async def test_ping_answer_buttons(env):
    from conftest import dt, make_user
    repo = env.repo
    user, c = await make_user(repo, uid=77, tz="+00:00")
    work, rest = c["Work"]["id"], c["Rest"]["id"]
    await repo.add_entry(77, work, dt(2026, 11, 4, 14, 10), dt(2026, 11, 4, 14, 20), "manual")
    ping_id = await repo.add_ping(77, 900, dt(2026, 11, 4, 14), dt(2026, 11, 4, 15))
    await env.tap(f"p:{ping_id}:c:{rest}")
    rows = await repo.entries_between(77, dt(2026, 11, 4), dt(2026, 11, 5))
    assert [(r["category_id"], r["start_utc"][11:16]) for r in rows] == [
        (rest, "14:00"), (work, "14:10"), (rest, "14:20")]
    assert (await repo.get_ping(ping_id))["status"] == "answered"
    assert "✅ 14:00–15:00 · 😌 Rest" in env.session.texts()[-1]
    # change the answer: old entries of this ping are replaced
    await env.tap(f"p:{ping_id}:chg")
    await env.tap(f"p:{ping_id}:c:{c['Eating']['id']}")
    rows = await repo.entries_between(77, dt(2026, 11, 4), dt(2026, 11, 5))
    assert sorted(r["category_id"] for r in rows) == sorted([c["Eating"]["id"]] * 2 + [work])
    await env.tap(f"p:{ping_id}:mix")
    assert "14:00-14:40 work" in env.session.texts()[-1]
    other = await repo.add_ping(77, 901, dt(2026, 11, 4, 16), dt(2026, 11, 4, 17))
    await env.tap(f"p:{other}:skip")
    assert (await repo.get_ping(other))["status"] == "skipped"
    # a ping that belongs to someone else is refused
    await env.tap("p:9999:skip")


async def test_bot_profile_setup_is_safe_and_skips_name_when_equal():
    from app.main import BOT_NAME, COMMANDS, DESCRIPTION, SHORT_DESCRIPTION, setup_bot_profile
    assert len(SHORT_DESCRIPTION) <= 120 and len(DESCRIPTION) <= 512
    assert [c for c, _ in COMMANDS] == ["start", "today", "week", "dashboard", "log", "timer", "stop",
                                        "goals", "settings", "pause", "resume", "privacy", "help"]

    class Name:
        def __init__(self, name):
            self.name = name

    class Bot:
        def __init__(self, name, fail=False):
            self.calls, self.name, self.fail = [], name, fail

        async def get_my_name(self):
            if self.fail:
                raise RuntimeError("flood")
            return Name(self.name)

        async def set_my_name(self, name):
            self.calls.append("name")
            if self.fail:
                raise RuntimeError("flood")

        async def set_my_short_description(self, short_description):
            self.calls.append("short")
            if self.fail:
                raise RuntimeError("x")

        async def set_my_description(self, description):
            self.calls.append("desc")

        async def set_my_commands(self, commands):
            self.calls.append(f"cmds{len(commands)}")

    same = Bot(BOT_NAME)
    await setup_bot_profile(same)
    assert same.calls == ["short", "desc", "cmds13"]
    other = Bot("TimeTracker")
    await setup_bot_profile(other)
    assert other.calls[0] == "name"
    broken = Bot("TimeTracker", fail=True)
    await setup_bot_profile(broken)                      # must not raise
    assert "desc" in broken.calls
