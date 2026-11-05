"""/start and the onboarding steps (SPEC section 8). The current step lives in users.onboarding_step."""
from __future__ import annotations

from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command, Filter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..config import Config
from ..intervals import decide_ping
from ..repo import DEFAULT_CATEGORIES, MAX_CATEGORIES, Repo
from ..tg import safe_answer
from ..timeutil import iso, local_date, parse_tz, tz_from_local_time, utcnow
from . import texts
from .common import awaiting, onboarding_state, parse_category_input, parse_hhmm
from .keyboards import btn, main_reply_keyboard

router = Router()
TEXT_STEPS = ("tz", "wake", "sleep", "addcat")


class MidOnboarding(Filter):
    """True for plain text messages from a user who is answering an onboarding question."""

    async def __call__(self, message: Message, repo: Repo) -> bool:
        if not message.text or message.text.startswith("/") or not message.from_user:
            return False
        user = await repo.get_user(message.from_user.id)
        return bool(user and user["onboarding_step"] in TEXT_STEPS)


def _state(uid: int) -> dict:
    if uid not in onboarding_state:
        onboarding_state[uid] = {"items": [
            {"name": n, "emoji": e, "waste": w, "sel": True} for n, e, w in DEFAULT_CATEGORIES]}
    return onboarding_state[uid]


def wake_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn(t, f"ob:wake:{t}") for t in
                                                  ("06:00", "07:00", "08:00", "09:00", "10:00")]])


def sleep_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn(t, f"ob:sleep:{t}") for t in
                                                  ("22:00", "23:00", "00:00", "01:00")]])


def categories_keyboard(uid: int) -> InlineKeyboardMarkup:
    items = _state(uid)["items"]
    rows, row = [], []
    for i, it in enumerate(items):
        row.append(btn(f"{'✅' if it['sel'] else '⬜'} {it['emoji']} {it['name']}", f"ob:c:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("➕ Add my own", "ob:add"), btn("Next →", "ob:cn")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def waste_keyboard(uid: int) -> InlineKeyboardMarkup:
    items = _state(uid)["items"]
    rows, row = [], []
    for i, it in enumerate(items):
        if not it["sel"]:
            continue
        row.append(btn(f"{'🔥' if it['waste'] else '▫️'} {it['emoji']} {it['name']}", f"ob:w:{i}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([btn("Next →", "ob:wn")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def interval_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        btn(f"{m} min" + (" ★" if m == 60 else ""), f"ob:i:{m}") for m in (30, 45, 60, 90, 120)]])


@router.message(Command("start"))
async def cmd_start(message: Message, repo: Repo, cfg: Config):
    uid = message.from_user.id
    user = await repo.get_user(uid)
    if user and user["onboarding_step"] is None:
        await message.answer(texts.ALREADY_SET, reply_markup=main_reply_keyboard(cfg.webapp_url))
        return
    awaiting.pop(uid, None)
    onboarding_state.pop(uid, None)
    if not user:
        await repo.create_user(uid, message.chat.id, message.from_user.first_name)
    await repo.update_user(uid, chat_id=message.chat.id, onboarding_step="tz")
    await message.answer(texts.GREETING)


@router.message(MidOnboarding())
async def onboarding_text(message: Message, repo: Repo):
    uid = message.from_user.id
    user = await repo.get_user(uid)
    step = user["onboarding_step"]
    text = message.text.strip()
    if step == "tz":
        tz = tz_from_local_time(text, utcnow())
        if not tz:
            await message.answer(texts.ASK_TZ_AGAIN)
            return
        await repo.update_user(uid, tz=tz, onboarding_step="wake")
        await message.answer(f"Got it, your timezone is UTC{tz}.\n\n{texts.ASK_WAKE}", reply_markup=wake_keyboard())
    elif step in ("wake", "sleep"):
        hm = parse_hhmm(text)
        if not hm:
            await message.answer("Send it like 07:30.")
            return
        if step == "wake":
            await repo.update_user(uid, wake_time=hm, onboarding_step="sleep")
            await message.answer(texts.ASK_SLEEP, reply_markup=sleep_keyboard())
        else:
            await repo.update_user(uid, sleep_time=hm, onboarding_step="cats")
            await message.answer(texts.ASK_CATEGORIES, reply_markup=categories_keyboard(uid))
    elif step == "addcat":
        parsed = parse_category_input(text)
        if not parsed:
            await message.answer("The name should be 1 to 24 characters. Try again.")
            return
        emoji, name = parsed
        _state(uid)["items"].append({"name": name, "emoji": emoji, "waste": False, "sel": True})
        await repo.update_user(uid, onboarding_step="cats")
        await message.answer(f"Added {emoji} {name}.", reply_markup=categories_keyboard(uid))


async def _step_is(cb: CallbackQuery, repo: Repo, *steps: str) -> dict | None:
    user = await repo.get_user(cb.from_user.id)
    if not user or user["onboarding_step"] not in steps:
        await safe_answer(cb, "That step is already done.")
        return None
    return user


@router.callback_query(F.data.startswith("ob:wake:"))
async def pick_wake(cb: CallbackQuery, repo: Repo):
    if not await _step_is(cb, repo, "wake"):
        return
    await repo.update_user(cb.from_user.id, wake_time=cb.data.split(":", 2)[2], onboarding_step="sleep")
    await safe_answer(cb)
    await cb.message.answer(texts.ASK_SLEEP, reply_markup=sleep_keyboard())


@router.callback_query(F.data.startswith("ob:sleep:"))
async def pick_sleep(cb: CallbackQuery, repo: Repo):
    if not await _step_is(cb, repo, "sleep"):
        return
    await repo.update_user(cb.from_user.id, sleep_time=cb.data.split(":", 2)[2], onboarding_step="cats")
    await safe_answer(cb)
    await cb.message.answer(texts.ASK_CATEGORIES, reply_markup=categories_keyboard(cb.from_user.id))


@router.callback_query(F.data.startswith("ob:c:"))
async def toggle_category(cb: CallbackQuery, repo: Repo):
    if not await _step_is(cb, repo, "cats"):
        return
    uid = cb.from_user.id
    items = _state(uid)["items"]
    i = int(cb.data.split(":")[2])
    if 0 <= i < len(items):
        items[i]["sel"] = not items[i]["sel"]
    await safe_answer(cb)
    try:
        await cb.message.edit_reply_markup(reply_markup=categories_keyboard(uid))
    except Exception:
        pass


@router.callback_query(F.data == "ob:add")
async def add_own(cb: CallbackQuery, repo: Repo):
    if not await _step_is(cb, repo, "cats"):
        return
    if len(_state(cb.from_user.id)["items"]) >= MAX_CATEGORIES:
        await safe_answer(cb, f"Maximum is {MAX_CATEGORIES} categories.", show_alert=True)
        return
    await repo.update_user(cb.from_user.id, onboarding_step="addcat")
    await safe_answer(cb)
    await cb.message.answer(texts.ASK_CUSTOM)


@router.callback_query(F.data == "ob:cn")
async def categories_next(cb: CallbackQuery, repo: Repo):
    if not await _step_is(cb, repo, "cats"):
        return
    uid = cb.from_user.id
    items = _state(uid)["items"]
    selected = [it for it in items if it["sel"]]
    if not selected:
        await safe_answer(cb, "Pick at least one category.", show_alert=True)
        return
    if len(selected) > MAX_CATEGORIES:
        await safe_answer(cb, f"Maximum is {MAX_CATEGORIES} categories.", show_alert=True)
        return
    await repo.update_user(uid, onboarding_step="waste")
    await safe_answer(cb)
    await cb.message.answer(texts.ASK_WASTE, reply_markup=waste_keyboard(uid))


@router.callback_query(F.data.startswith("ob:w:"))
async def toggle_waste(cb: CallbackQuery, repo: Repo):
    if not await _step_is(cb, repo, "waste"):
        return
    uid = cb.from_user.id
    items = _state(uid)["items"]
    i = int(cb.data.split(":")[2])
    if 0 <= i < len(items):
        items[i]["waste"] = not items[i]["waste"]
    await safe_answer(cb)
    try:
        await cb.message.edit_reply_markup(reply_markup=waste_keyboard(uid))
    except Exception:
        pass


@router.callback_query(F.data == "ob:wn")
async def waste_next(cb: CallbackQuery, repo: Repo):
    if not await _step_is(cb, repo, "waste"):
        return
    uid = cb.from_user.id
    await repo.conn.execute("DELETE FROM categories WHERE user_id=?", (uid,))
    await repo.conn.commit()
    for it in _state(uid)["items"]:
        if it["sel"]:
            await repo.add_category(uid, it["name"], it["emoji"], it["waste"])
    await repo.update_user(uid, onboarding_step="interval")
    await safe_answer(cb)
    await cb.message.answer(texts.ASK_INTERVAL, reply_markup=interval_keyboard())


@router.callback_query(F.data.startswith("ob:i:"))
async def pick_interval(cb: CallbackQuery, repo: Repo, cfg: Config):
    user = await _step_is(cb, repo, "interval")
    if not user:
        return
    uid = cb.from_user.id
    interval = int(cb.data.split(":")[2])
    now = utcnow()
    tz = parse_tz(user["tz"])
    dec = decide_ping(now, now, interval, user["wake_time"], user["sleep_time"], tz, False)
    await repo.update_user(
        uid, ping_interval_min=interval, onboarding_step=None,
        challenge_start=local_date(now, tz).isoformat(),
        last_checkin_at=iso(dec.last_checkin_at or now), next_ping_at=iso(dec.next_ping_at))
    onboarding_state.pop(uid, None)
    await safe_answer(cb)
    await cb.message.answer(texts.HOW_TO, reply_markup=main_reply_keyboard(cfg.webapp_url))
