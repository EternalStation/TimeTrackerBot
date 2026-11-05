"""/settings, /timezone, /pause, /resume (SPEC section 14)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject, Filter
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..repo import MAX_CATEGORIES, Repo
from ..tg import safe_answer
from ..timeutil import is_valid_tz, iso, tz_from_local_time, utcnow
from .common import NOT_STARTED, awaiting, parse_category_input, parse_hhmm
from .keyboards import btn, cat_label

router = Router()


class Awaiting(Filter):
    async def __call__(self, message: Message) -> bool:
        return bool(message.text and not message.text.startswith("/") and message.from_user
                    and message.from_user.id in awaiting)


async def menu(repo: Repo, user: dict) -> tuple[str, InlineKeyboardMarkup]:
    paused = bool(user["paused"])
    rows = [
        [btn(f"⏱ Check-in every {user['ping_interval_min']} min", "s:int")],
        [btn(f"🌅 Wake {user['wake_time']}", "s:wake"), btn(f"🌙 Sleep {user['sleep_time']}", "s:sleep")],
        [btn(f"🌍 Timezone {user['tz']}", "s:tz")],
        [btn("🗂 Categories", "s:cats")],
        [btn("▶️ Resume check-ins" if paused else "⏸ Pause check-ins", "s:pause")],
    ]
    return "Settings" + (" (check-ins are paused)" if paused else ""), InlineKeyboardMarkup(inline_keyboard=rows)


async def categories_view(repo: Repo, uid: int) -> tuple[str, InlineKeyboardMarkup]:
    cats = await repo.list_categories(uid)
    rows = []
    for c in cats:
        rows.append([btn(f"{'✅' if c['active'] else '⬜'} {cat_label(c)}", f"s:ca:{c['id']}"),
                     btn("🔥 waste" if c["is_waste"] else "▫️ not waste", f"s:cw:{c['id']}")])
    rows.append([btn("➕ Add category", "s:cadd"), btn("← Back", "s:back")])
    return ("Categories. Left button: show or hide it in check-ins. Right button: count it as waste or not.",
            InlineKeyboardMarkup(inline_keyboard=rows))


async def _user(cb_or_msg, repo: Repo) -> dict | None:
    user = await repo.get_user(cb_or_msg.from_user.id)
    if not user or user["onboarding_step"] is not None:
        return None
    return user


@router.message(Command("settings"))
async def cmd_settings(message: Message, repo: Repo):
    user = await _user(message, repo)
    if not user:
        await message.answer(NOT_STARTED)
        return
    awaiting.pop(user["id"], None)
    text, kb = await menu(repo, user)
    await message.answer(text, reply_markup=kb)


@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    awaiting.pop(message.from_user.id, None)
    await message.answer("Okay, cancelled.")


@router.message(Command("pause"))
async def cmd_pause(message: Message, repo: Repo):
    user = await _user(message, repo)
    if not user:
        await message.answer(NOT_STARTED)
        return
    await repo.update_user(user["id"], paused=1)
    await message.answer("Check-ins are paused. Send /resume when you want them back.")


@router.message(Command("resume"))
async def cmd_resume(message: Message, repo: Repo):
    user = await _user(message, repo)
    if not user:
        await message.answer(NOT_STARTED)
        return
    now = utcnow()
    # restart the interval from now so the first ping does not cover the whole pause
    await repo.update_user(user["id"], paused=0, last_checkin_at=iso(now),
                           next_ping_at=iso(now))
    await message.answer("Check-ins are back on.")


@router.message(Command("timezone"))
async def cmd_timezone(message: Message, repo: Repo, command: CommandObject):
    user = await _user(message, repo)
    if not user:
        await message.answer(NOT_STARTED)
        return
    arg = (command.args or "").strip()
    if not arg:
        awaiting[user["id"]] = "tz"
        await message.answer("What time is it for you right now? Send it like 14:05. "
                             "Or send a zone name like Europe/Warsaw.")
        return
    await _set_tz(message, repo, user["id"], arg)


async def _set_tz(message: Message, repo: Repo, uid: int, text: str) -> bool:
    tz = tz_from_local_time(text, utcnow())
    if not tz and is_valid_tz(text):
        tz = text.strip()
    if not tz:
        await message.answer("I couldn't read that. Send the current time like 14:05, or a zone like Europe/Warsaw.")
        return False
    await repo.update_user(uid, tz=tz)
    awaiting.pop(uid, None)
    await message.answer(f"Timezone set to {tz}.")
    return True


@router.message(Awaiting())
async def awaited_text(message: Message, repo: Repo):
    uid = message.from_user.id
    what = awaiting.get(uid)
    text = message.text.strip()
    if what == "tz":
        await _set_tz(message, repo, uid, text)
    elif what in ("wake", "sleep"):
        hm = parse_hhmm(text)
        if not hm:
            await message.answer("Send it like 07:30, or /cancel.")
            return
        await repo.update_user(uid, **{f"{what}_time": hm})
        awaiting.pop(uid, None)
        await message.answer(f"Saved: {what} {hm}.")
    elif what == "addcat":
        parsed = parse_category_input(text)
        if not parsed:
            await message.answer("The name should be 1 to 24 characters. Try again, or /cancel.")
            return
        active = await repo.list_categories(uid, active_only=True)
        if len(active) >= MAX_CATEGORIES:
            awaiting.pop(uid, None)
            await message.answer(f"You already have {MAX_CATEGORIES} active categories. Hide one first.")
            return
        emoji, name = parsed
        await repo.add_category(uid, name, emoji, False)
        awaiting.pop(uid, None)
        await message.answer(f"Added {emoji} {name}. Use /settings, Categories to mark it as waste.")


@router.callback_query(F.data.startswith("s:"))
async def on_settings(cb: CallbackQuery, repo: Repo):
    user = await _user(cb, repo)
    if not user:
        await safe_answer(cb, NOT_STARTED)
        return
    uid = user["id"]
    parts = cb.data.split(":")
    action = parts[1]
    await safe_answer(cb)

    async def show(text, kb):
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except Exception:
            await cb.message.answer(text, reply_markup=kb)

    if action == "back":
        awaiting.pop(uid, None)
        await show(*await menu(repo, user))
    elif action == "int":
        if len(parts) == 3:
            await repo.update_user(uid, ping_interval_min=int(parts[2]))
            user = await repo.get_user(uid)
            await show(*await menu(repo, user))
        else:
            kb = InlineKeyboardMarkup(inline_keyboard=[[btn(f"{m} min", f"s:int:{m}") for m in (30, 45, 60, 90, 120)]])
            await show("How often should I check in?", kb)
    elif action in ("wake", "sleep"):
        awaiting[uid] = action
        await cb.message.answer(f"Send your {'wake-up' if action == 'wake' else 'sleep'} time like 07:30.")
    elif action == "tz":
        awaiting[uid] = "tz"
        await cb.message.answer("What time is it for you right now? Send it like 14:05.")
    elif action == "pause":
        await repo.update_user(uid, paused=0 if user["paused"] else 1)
        user = await repo.get_user(uid)
        await show(*await menu(repo, user))
    elif action == "cats":
        await show(*await categories_view(repo, uid))
    elif action in ("ca", "cw"):
        cat = await repo.get_category(uid, int(parts[2]))
        if cat:
            if action == "cw":
                await repo.update_category(cat["id"], is_waste=0 if cat["is_waste"] else 1)
            else:
                active = await repo.list_categories(uid, active_only=True)
                if cat["active"] and len(active) <= 1:
                    await safe_answer(cb, "Keep at least one category.", show_alert=True)
                elif not cat["active"] and len(active) >= MAX_CATEGORIES:
                    await safe_answer(cb, f"Maximum is {MAX_CATEGORIES} active categories.", show_alert=True)
                else:
                    await repo.update_category(cat["id"], active=0 if cat["active"] else 1)
        await show(*await categories_view(repo, uid))
    elif action == "cadd":
        awaiting[uid] = "addcat"
        await cb.message.answer("Send the name of the new category, with an emoji if you like. Example: 🎲 Board games")
