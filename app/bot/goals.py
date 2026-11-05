"""/goals: daily limits for waste categories (SPEC section 9)."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..entries import average_per_day, day_stats_for, user_tz
from ..limits import check_limits
from ..repo import Repo
from ..tg import safe_answer
from ..timeutil import fmt_dur, local_date, utcnow
from .common import NOT_STARTED
from .keyboards import btn, cat_label, category_rows

router = Router()
LIMITS = [(15, "15m"), (30, "30m"), (45, "45m"), (60, "1h"), (90, "1h30"), (120, "2h"), (180, "3h")]


async def goals_view(repo: Repo, user: dict) -> tuple[str, InlineKeyboardMarkup]:
    now = utcnow()
    cats = {c["id"]: c for c in await repo.list_categories(user["id"])}
    goals = await repo.list_goals(user["id"])
    ds = await day_stats_for(repo, user, local_date(now, user_tz(user)), now, list(cats.values()))
    lines, rows = [], []
    for g in goals:
        cat = cats.get(g["category_id"])
        if not cat:
            continue
        lines.append(f"{cat_label(cat)}: {fmt_dur(ds.minutes_for(cat['id']))} today, limit {fmt_dur(g['daily_limit_min'])}")
        rows.append([btn(f"🗑 Remove {cat['name']}", f"g:del:{g['id']}")])
    text = "Your daily limits:\n" + "\n".join(lines) if lines else "You have no limits yet. Pick a category you want to cut down."
    rows.append([btn("➕ Add a limit", "g:add")])
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("goals"))
async def cmd_goals(message: Message, repo: Repo):
    user = await repo.get_user(message.from_user.id)
    if not user or user["onboarding_step"] is not None:
        await message.answer(NOT_STARTED)
        return
    text, kb = await goals_view(repo, user)
    await message.answer(text, reply_markup=kb)


@router.callback_query(F.data == "g:add")
async def add_goal(cb: CallbackQuery, repo: Repo):
    cats = await repo.list_categories(cb.from_user.id, active_only=True)
    waste = [c for c in cats if c["is_waste"]] or cats
    await safe_answer(cb)
    rows = category_rows(waste, lambda c: f"g:cat:{c['id']}")
    await cb.message.answer("Which category do you want to limit?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


@router.callback_query(F.data.startswith("g:cat:"))
async def pick_limit(cb: CallbackQuery, repo: Repo):
    cat_id = int(cb.data.split(":")[2])
    cat = await repo.get_category(cb.from_user.id, cat_id)
    if not cat:
        await safe_answer(cb)
        return
    await safe_answer(cb)
    row, rows = [], []
    for minutes, label in LIMITS:
        row.append(btn(label, f"g:lim:{cat_id}:{minutes}"))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    await cb.message.answer(f"Daily limit for {cat_label(cat)}?", reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))


async def _create(cb: CallbackQuery, repo: Repo, bot, cat_id: int, minutes: int):
    user = await repo.get_user(cb.from_user.id)
    cat = await repo.get_category(cb.from_user.id, cat_id) if user else None
    if not user or not cat or not 5 <= minutes <= 1440:
        await safe_answer(cb, "I couldn't set that goal.")
        return
    now = utcnow()
    baseline = await average_per_day(repo, user, cat_id, now)
    await repo.replace_goal(user["id"], cat_id, minutes, baseline, now)
    await safe_answer(cb, "Goal set")
    extra = f" Your recent average is {fmt_dur(baseline)}." if baseline else ""
    await cb.message.answer(f"🎯 Goal set: {cat['name']} up to {fmt_dur(minutes)} a day.{extra} I'll flag it if you cross the line.")
    await check_limits(bot, repo, user["id"], now)


@router.callback_query(F.data.startswith("g:lim:"))
async def set_limit(cb: CallbackQuery, repo: Repo, bot):
    _, _, cat_id, minutes = cb.data.split(":")
    await _create(cb, repo, bot, int(cat_id), int(minutes))


@router.callback_query(F.data.startswith("g:set:"))
async def set_suggested(cb: CallbackQuery, repo: Repo, bot):
    _, _, cat_id, minutes = cb.data.split(":")
    await _create(cb, repo, bot, int(cat_id), int(minutes))


@router.callback_query(F.data.startswith("g:del:"))
async def remove_goal(cb: CallbackQuery, repo: Repo):
    goal = await repo.get_goal(cb.from_user.id, int(cb.data.split(":")[2]))
    if goal:
        await repo.deactivate_goal(goal["id"])
    await safe_answer(cb, "Removed")
    user = await repo.get_user(cb.from_user.id)
    if user:
        text, kb = await goals_view(repo, user)
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
