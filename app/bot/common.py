"""Small helpers shared by the routers, plus in-memory state for multi-step flows."""
from __future__ import annotations

import re
import secrets

# user_id -> what free text we are waiting for in /settings: 'tz' | 'wake' | 'sleep' | 'addcat'
awaiting: dict[int, str] = {}
# onboarding picks, user_id -> {"items": [...]}; rebuilt with defaults if the bot restarted
onboarding_state: dict[int, dict] = {}
# manual entries waiting for a category choice, token -> {"user", "start", "end", "note"}
pending_logs: dict[str, dict] = {}

NOT_STARTED = "Send /start first and I'll set you up."


def new_pending(data: dict) -> str:
    while len(pending_logs) >= 200:
        pending_logs.pop(next(iter(pending_logs)))
    token = secrets.token_hex(4)
    pending_logs[token] = data
    return token


def parse_hhmm(text: str) -> str | None:
    """'7:30' / '07.30' -> '07:30', or None."""
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", text or "")
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    return f"{h:02d}:{mi:02d}"


def parse_category_input(text: str) -> tuple[str, str] | None:
    """'🎮 Board games' or 'Board games' -> (emoji, name). Name up to 24 chars."""
    text = (text or "").strip()
    if not text:
        return None
    emoji = "•"
    first, _, rest = text.partition(" ")
    if rest.strip() and not any(ch.isalnum() for ch in first) and len(first) <= 8:
        emoji, text = first, rest.strip()
    name = text.strip()
    if not name or len(name) > 24:
        return None
    return emoji, name
