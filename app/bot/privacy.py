"""/help, /privacy, /delete_me."""
from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.types import ReplyKeyboardRemove

from ..repo import Repo
from ..tg import safe_answer
from . import texts
from .common import awaiting, onboarding_state
from .keyboards import btn

router = Router()


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(texts.HELP)


@router.message(Command("privacy"))
async def cmd_privacy(message: Message):
    await message.answer(texts.PRIVACY)


@router.message(Command("delete_me"))
async def cmd_delete_me(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[[btn("Yes, delete everything", "del:yes"), btn("Cancel", "del:no")]])
    await message.answer("This erases your settings, categories, entries and goals for good. Are you sure?",
                         reply_markup=kb)


@router.callback_query(F.data.startswith("del:"))
async def confirm_delete(cb: CallbackQuery, repo: Repo):
    await safe_answer(cb)
    if cb.data == "del:yes":
        await repo.delete_user(cb.from_user.id)
        awaiting.pop(cb.from_user.id, None)
        onboarding_state.pop(cb.from_user.id, None)
        await cb.message.answer("Done. Everything is erased, no receipts kept. Send /start if you ever want a new tab.",
                                reply_markup=ReplyKeyboardRemove())
    else:
        await cb.message.answer("Okay, nothing was deleted.")
