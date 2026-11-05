"""Telegram calls that must never kill the caller (blocked bot, message not modified, etc.)."""
from __future__ import annotations

import logging

log = logging.getLogger("tg")


async def safe_send(bot, chat_id: int, text: str, **kwargs):
    if bot is None:
        return None
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except Exception as exc:  # TelegramAPIError, network errors, ...
        log.warning("send_message to %s failed: %s", chat_id, exc)
        return None


async def safe_send_photo(bot, chat_id: int, photo, **kwargs):
    if bot is None:
        return None
    try:
        return await bot.send_photo(chat_id, photo, **kwargs)
    except Exception as exc:
        log.warning("send_photo to %s failed: %s", chat_id, exc)
        return None


async def safe_edit(bot, chat_id: int, message_id: int | None, text: str, **kwargs) -> bool:
    if bot is None or not message_id:
        return False
    try:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, **kwargs)
        return True
    except Exception as exc:
        log.info("edit_message_text %s/%s failed: %s", chat_id, message_id, exc)
        return False


async def safe_answer(callback, text: str | None = None, **kwargs) -> None:
    try:
        await callback.answer(text, **kwargs)
    except Exception as exc:
        log.info("callback answer failed: %s", exc)
