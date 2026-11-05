"""/today and /week on demand."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

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
async def dashboard_without_url(message: Message):
    # only reached when PUBLIC_URL is not set (otherwise Telegram opens the Mini App directly)
    await message.answer("The dashboard isn't configured yet. Ask the bot owner to set PUBLIC_URL.")
