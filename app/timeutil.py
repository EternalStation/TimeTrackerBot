"""Time helpers. All stored timestamps are UTC ISO strings like 2026-11-04T09:30:00Z."""
from __future__ import annotations

import re
from datetime import date, datetime, time, timedelta, timezone, tzinfo
from zoneinfo import ZoneInfo

UTC = timezone.utc
_OFFSET_RE = re.compile(r"^([+-])(\d{1,2}):?(\d{2})$")


def parse_tz(value: str | None) -> tzinfo:
    """'+01:00' / '-05:30' -> fixed offset; anything else -> IANA zone. Falls back to UTC."""
    value = (value or "+00:00").strip()
    m = _OFFSET_RE.match(value)
    if m:
        sign = -1 if m.group(1) == "-" else 1
        delta = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)))
        return timezone(sign * delta)
    try:
        return ZoneInfo(value)
    except Exception:
        return UTC


def is_valid_tz(value: str) -> bool:
    value = value.strip()
    if _OFFSET_RE.match(value):
        return True
    try:
        ZoneInfo(value)
        return True
    except Exception:
        return False


def utcnow() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def parse_hm(s: str) -> time:
    h, m = re.split(r"[:.]", s.strip())
    return time(int(h), int(m))


def fmt_hm(dt: datetime, tz: tzinfo) -> str:
    return dt.astimezone(tz).strftime("%H:%M")


def local_date(dt: datetime, tz: tzinfo) -> date:
    return dt.astimezone(tz).date()


def local_midnight(d: date, tz: tzinfo) -> datetime:
    """Start of local date d, as an aware UTC datetime."""
    return datetime.combine(d, time(0, 0), tzinfo=tz).astimezone(UTC)


def local_dt(d: date, t: time, tz: tzinfo) -> datetime:
    return datetime.combine(d, t, tzinfo=tz).astimezone(UTC)


def fmt_dur(minutes: int | float) -> str:
    """65 -> '1h 05m', 60 -> '1h', 45 -> '45m', 0 -> '0m'."""
    minutes = int(round(minutes))
    h, m = divmod(max(0, minutes), 60)
    if h == 0:
        return f"{m}m"
    if m == 0:
        return f"{h}h"
    return f"{h}h {m:02d}m"


def tz_from_local_time(local_hm: str, now_utc: datetime) -> str | None:
    """User says what time it is for them; return an offset string like '+01:00' (15 min steps)."""
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})\s*$", local_hm)
    if not m:
        return None
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return None
    diff = ((h * 60 + mi) - (now_utc.hour * 60 + now_utc.minute)) % 1440
    if diff >= 14 * 60:                        # real offsets run from -10:00 to +13:45 here
        diff -= 1440
    diff = int(round(diff / 15.0)) * 15
    sign = "-" if diff < 0 else "+"
    diff = abs(diff)
    return f"{sign}{diff // 60:02d}:{diff % 60:02d}"
