"""Live timer: Start / Stop (SPEC section 7)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..entries import start_timer, stop_timer, user_tz
from ..limits import check_limits
from ..repo import Repo
from ..tg import safe_answer
from ..timeutil import fmt_dur, fmt_hm, utcnow
from .common import NOT_STARTED
from .keyboards import btn, cat_label, category_rows

router = Router()


async def _registered(message: Message, repo: Repo) -> dict | None:
    user = await repo.get_user(message.from_user.id)
    if not user or user["onboarding_step"] is not None:
        await message.answer(NOT_STARTED)
        return None
    return user


@router.message(Command("timer"))
@router.message(F.text == "▶️ Start")
async def ask_category(message: Message, repo: Repo):
    user = await _registered(message, repo)
    if not user:
        return
    cats = await repo.list_categories(user["id"], active_only=True)
    rows = category_rows(cats, lambda c: f"t:c:{c['id']}")
    rows.append([btn("Cancel", "t:x")])
    await message.answer("What are you starting?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data == "t:x")
async def cancel(cb: CallbackQuery):
    await safe_answer(cb)
    try:
        await cb.message.delete()
    except Exception:
        pass


@router.callback_query(F.data.startswith("t:c:"))
async def start(cb: CallbackQuery, repo: Repo):
    user = await repo.get_user(cb.from_user.id)
    cat = await repo.get_category(cb.from_user.id, int(cb.data.split(":")[2])) if user else None
    if not user or not cat:
        await safe_answer(cb, "That category doesn't exist anymore.")
        return
    now = utcnow()
    await start_timer(repo, user["id"], cat["id"], now)
    await safe_answer(cb, "Timer started")
    try:
        await cb.message.edit_text(f"▶️ {cat_label(cat)} started at {fmt_hm(now, user_tz(user))}. Meter's running. Tap ⏹ Stop when you're done.")
    except Exception:
        pass


@router.message(Command("stop"))
@router.message(F.text == "⏹ Stop")
async def stop(message: Message, repo: Repo, bot):
    user = await _registered(message, repo)
    if not user:
        return
    now = utcnow()
    result = await stop_timer(repo, user["id"], now)
    if not result:
        await message.answer("No timer is running. Nothing on the meter.")
        return
    cat = await repo.get_category(user["id"], result["category_id"])
    await message.answer(f"⏹ {cat_label(cat) if cat else ''} · {fmt_dur(result['minutes'])}. Rung up.")
    await check_limits(bot, repo, user["id"], now)
