"""Answers to the hourly check-in message (SPEC section 6)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

from ..entries import delete_ping_entries_and_fill, user_tz
from ..limits import check_limits
from ..repo import Repo
from ..tg import safe_answer, safe_edit
from ..timeutil import fmt_hm, iso, parse_iso, utcnow
from . import texts
from .keyboards import cat_label, change_keyboard, ping_keyboard

router = Router()


@router.callback_query(F.data.startswith("p:"))
async def on_ping_button(cb: CallbackQuery, repo: Repo, bot):
    parts = cb.data.split(":")
    try:
        ping_id, action = int(parts[1]), parts[2]
    except (IndexError, ValueError):
        await safe_answer(cb)
        return
    ping = await repo.get_ping(ping_id)
    user = await repo.get_user(cb.from_user.id)
    if not ping or not user or ping["user_id"] != user["id"]:
        await safe_answer(cb, "That receipt is gone. Can't find the check-in.")
        return
    tz = user_tz(user)
    start, end = parse_iso(ping["start_utc"]), parse_iso(ping["end_utc"])
    label = f"{fmt_hm(start, tz)}–{fmt_hm(end, tz)}"
    chat_id, message_id = cb.message.chat.id, cb.message.message_id
    now = utcnow()

    if action == "c":
        cat = await repo.get_category(user["id"], int(parts[3]))
        if not cat:
            await safe_answer(cb, "That category doesn't exist anymore.")
            return
        await delete_ping_entries_and_fill(repo, user["id"], ping_id, cat["id"], start, end, now)
        await repo.set_ping_status(ping_id, "answered")
        last = parse_iso(user["last_checkin_at"]) if user["last_checkin_at"] else end
        await repo.update_user(user["id"], last_checkin_at=iso(max(last, end)))
        await safe_answer(cb, "Saved")
        await safe_edit(bot, chat_id, message_id, f"✅ {label} · {cat_label(cat)}",
                        reply_markup=change_keyboard(ping_id))
        await check_limits(bot, repo, user["id"], now)
    elif action == "skip":
        await repo.set_ping_status(ping_id, "skipped")
        last = parse_iso(user["last_checkin_at"]) if user["last_checkin_at"] else end
        await repo.update_user(user["id"], last_checkin_at=iso(max(last, end)))
        await safe_answer(cb)
        await safe_edit(bot, chat_id, message_id, f"🙈 Skipped {label}", reply_markup=change_keyboard(ping_id))
    elif action == "mix":
        await safe_answer(cb)
        await cb.message.answer("Split bill? Send each part like 14:00-14:40 work, or add entries in the dashboard.")
    elif action == "chg":
        cats = await repo.list_categories(user["id"], active_only=True)
        await safe_answer(cb)
        await safe_edit(bot, chat_id, message_id, texts.ping_question(label),
                        reply_markup=ping_keyboard(ping_id, cats, None))
    else:
        await safe_answer(cb)
