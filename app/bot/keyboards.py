"""Keyboards. Callback data must stay within 64 bytes (all ours are far below)."""
from __future__ import annotations

from aiogram.types import (InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton,
                           ReplyKeyboardMarkup, WebAppInfo)


def cat_label(cat: dict) -> str:
    return f"{cat['emoji'] or '•'} {cat['name']}"


def _check(data: str) -> str:
    assert len(data.encode()) <= 64, data
    return data


def btn(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=_check(data))


def category_rows(cats: list[dict], data_fn) -> list[list[InlineKeyboardButton]]:
    """Active categories, two per row. data_fn(cat) -> callback data."""
    rows, row = [], []
    for c in cats:
        row.append(btn(cat_label(c), data_fn(c)))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    return rows


def ping_keyboard(ping_id: int, cats: list[dict], previous_cat: dict | None) -> InlineKeyboardMarkup:
    rows = []
    if previous_cat:
        rows.append([btn(f"↩️ Same: {cat_label(previous_cat)}", f"p:{ping_id}:c:{previous_cat['id']}")])
    rows += category_rows(cats, lambda c: f"p:{ping_id}:c:{c['id']}")
    rows.append([btn("✂️ Mixed", f"p:{ping_id}:mix"), btn("🙈 Skip", f"p:{ping_id}:skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def change_keyboard(ping_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[btn("✏️ Change", f"p:{ping_id}:chg")]])


def main_reply_keyboard(webapp_url: str) -> ReplyKeyboardMarkup:
    dash = (KeyboardButton(text="📊 Dashboard", web_app=WebAppInfo(url=webapp_url)) if webapp_url
            else KeyboardButton(text="📊 Dashboard"))
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="▶️ Start"), KeyboardButton(text="⏹ Stop")],
                  [KeyboardButton(text="➕ Log"), dash]],
        resize_keyboard=True)
