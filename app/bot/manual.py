"""Manual logging from chat: '14:00-15:30 work' (SPEC section 7). Must be registered last:
its free-text handler takes every plain message that no other router wanted."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..config import Config
from ..entries import add_override_entry, user_tz
from ..limits import check_limits
from ..logparse import parse_log, resolve_category
from ..repo import Repo
from ..tg import safe_answer
from ..timeutil import fmt_hm, utcnow
from . import texts
from .common import NOT_STARTED, new_pending, pending_logs
from .keyboards import btn, cat_label, category_rows
from ..reports import dashboard_markup

router = Router()


async def _log_entry(bot, repo: Repo, user: dict, cat: dict, start, end, note) -> str:
    now = utcnow()
    await add_override_entry(repo, user["id"], cat["id"], start, end, now, "manual", note)
    tz = user_tz(user)
    await check_limits(bot, repo, user["id"], now)
    return f"✅ Logged {fmt_hm(start, tz)}–{fmt_hm(end, tz)} · {cat_label(cat)}"


async def handle_log_text(message: Message, text: str, repo: Repo, bot) -> bool:
    """Returns False if the text is not a log line."""
    user = await repo.get_user(message.from_user.id)
    if not user or user["onboarding_step"] is not None:
        await message.answer(NOT_STARTED)
        return True
    result = parse_log(text, utcnow(), user_tz(user))
    if result is None:
        return False
    if not result.ok:
        await message.answer(result.error)
        return True
    cats = await repo.list_categories(user["id"], active_only=True)
    cat, note = resolve_category(cats, result.text)
    if cat:
        await message.answer(await _log_entry(bot, repo, user, cat, result.start, result.end, note))
        return True
    token = new_pending({"user": user["id"], "start": result.start, "end": result.end,
                         "note": result.text[:200]})
    rows = category_rows(cats, lambda c: f"m:{token}:{c['id']}")
    rows.append([btn("Cancel", f"m:{token}:x")])
    tz = user_tz(user)
    await message.answer(
        f"Which category is {fmt_hm(result.start, tz)}–{fmt_hm(result.end, tz)}? "
        f"I couldn't match \"{result.text[:40]}\".",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    return True


@router.callback_query(F.data.startswith("m:"))
async def pick_category(cb: CallbackQuery, repo: Repo, bot):
    _, token, what = cb.data.split(":")
    pending = pending_logs.get(token)
    if not pending or pending["user"] != cb.from_user.id:
        await safe_answer(cb, "That request expired. Send the line again.")
        return
    pending_logs.pop(token, None)
    await safe_answer(cb)
    if what == "x":
        try:
            await cb.message.delete()
        except Exception:
            pass
        return
    user = await repo.get_user(cb.from_user.id)
    cat = await repo.get_category(cb.from_user.id, int(what))
    if not user or not cat:
        return
    text = await _log_entry(bot, repo, user, cat, pending["start"], pending["end"], pending["note"])
    try:
        await cb.message.edit_text(text)
    except Exception:
        pass


@router.message(Command("log"))
@router.message(F.text == "➕ Log")
async def cmd_log(message: Message, repo: Repo, bot, cfg: Config, command: CommandObject = None):
    args = (command.args or "").strip() if command else ""
    if args and await handle_log_text(message, args, repo, bot):
        return
    await message.answer(texts.LOG_HELP, reply_markup=dashboard_markup(cfg))


@router.message(F.text, ~F.text.startswith("/"))
async def free_text(message: Message, repo: Repo, bot):
    if await handle_log_text(message, message.text, repo, bot):
        return
    await message.answer("Didn't catch that. To add an item, send something like 14:00-15:30 work. /help has the menu.")
