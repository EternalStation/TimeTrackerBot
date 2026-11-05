"""Parsing of free-text log lines like '14:00-15:30 work' or 'yesterday 22:00 - now gaming'."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, time, timedelta, tzinfo

from .timeutil import local_date, local_dt

LOG_RE = re.compile(
    r"^(yesterday\s+)?(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2}|now)\s+(.+)$",
    re.IGNORECASE | re.DOTALL)


@dataclass
class LogResult:
    ok: bool
    start: datetime | None = None
    end: datetime | None = None
    text: str = ""
    error: str = ""


def _hm(s: str) -> time | None:
    h, m = re.split(r"[:.]", s)
    h, m = int(h), int(m)
    return time(h, m) if h <= 23 and m <= 59 else None


def parse_log(text: str, now: datetime, tz: tzinfo) -> LogResult | None:
    """None if the text is not a log line at all; otherwise a result with either times or an error."""
    m = LOG_RE.match(text.strip())
    if not m:
        return None
    day = local_date(now, tz) - (timedelta(days=1) if m.group(1) else timedelta(0))
    t1 = _hm(m.group(2))
    if t1 is None:
        return LogResult(False, error="I can't read that start time. Use 24h format like 14:30.")
    start = local_dt(day, t1, tz)
    if m.group(3).lower() == "now":
        end = now
    else:
        t2 = _hm(m.group(3))
        if t2 is None:
            return LogResult(False, error="I can't read that end time. Use 24h format like 15:30.")
        end = local_dt(day, t2, tz)
    rest = m.group(4).strip()
    if end <= start:
        return LogResult(False, error="The end time is before the start time. Try again, for example 14:00-15:30 work.")
    if start >= now:
        return LogResult(False, error="That time has not happened yet.")
    return LogResult(True, start=start, end=min(end, now), text=rest)


def match_category(cats: list[dict], query: str) -> list[dict]:
    """Case-insensitive: exact name, else name starts with query, else name contains query."""
    q = query.strip().lower()
    if not q:
        return []
    exact = [c for c in cats if c["name"].lower() == q]
    if exact:
        return exact
    starts = [c for c in cats if c["name"].lower().startswith(q)]
    if starts:
        return starts
    return [c for c in cats if q in c["name"].lower()]


def resolve_category(cats: list[dict], text: str) -> tuple[dict | None, str | None]:
    """Returns (category or None if unclear, note). Tries the whole text, then the first word."""
    found = match_category(cats, text)
    if len(found) == 1:
        return found[0], None
    if not found:
        first, _, rest = text.strip().partition(" ")
        found = match_category(cats, first)
        if len(found) == 1:
            return found[0], rest.strip() or None
    return None, None
