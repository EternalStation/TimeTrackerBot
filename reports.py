"""/today and /week on demand."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, WebAppInfo

from ..config import Config
from ..entries import user_tz
from ..repo import Repo
from ..reports import send_daily_summary, send_weekly_report
from ..timeutil import local_date, utcnow
from .common import NOT_STARTED

router = Router()


@router.message(Command("today"))
async def cmd_today(message: Message, repo: Repo, bot, cfg: Config):
    user = await repo.get_user(message.from_user.id)
    if not user or user["onboarding_step"] is not None:
        await message.answer(NOT_STARTED)
        return
    now = utcnow()
    await send_daily_summary(bot, repo, cfg, user, local_date(now, user_tz(user)), now)


@router.message(Command("week"))
async def cmd_week(message: Message, repo: Repo, bot, cfg: Config):
    user = await repo.get_user(message.from_user.id)
    if not user or user["onboarding_step"] is not None:
        await message.answer(NOT_STARTED)
        return
    now = utcnow()
    me = await bot.me()
    await send_weekly_report(bot, repo, cfg, user, local_date(now, user_tz(user)), now,
                             me.username or "", reuse_today=True)


@router.message(F.text == "📊 Dashboard")
@router.message(Command("dashboard"))
async def dashboard_button(message: Message, cfg: Config):
    if not cfg.webapp_url:
        await message.answer("The dashboard isn't configured yet. Ask the bot owner to set PUBLIC_URL.")
        return
    # Inline web_app buttons pass signed initData; reply-keyboard ones don't.
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📊 Open dashboard", web_app=WebAppInfo(url=cfg.webapp_url))]])
    await message.answer("Your stats:", reply_markup=kb)
