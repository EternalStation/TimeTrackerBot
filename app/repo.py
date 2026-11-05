"""All SQL lives here. Methods take/return plain dicts; timestamps are ISO strings."""
from __future__ import annotations

import asyncio
from datetime import datetime

import aiosqlite

from .timeutil import iso, utcnow

NON_WASTE_COLORS = ["#4C7DF0", "#2BB3A3", "#7C5CDB", "#3A9BDC", "#5FA35A", "#8A94A6", "#C08B2C", "#2F6D8C", "#A3B86C"]
WASTE_COLORS = ["#F0564A", "#F28C38", "#E8487F", "#D9622B"]

DEFAULT_CATEGORIES = [
    ("Work", "💼", False), ("Study", "📚", False), ("Exercise", "🏃", False),
    ("Chores & cooking", "🍳", False), ("Eating", "🍽", False), ("Commute", "🚌", False),
    ("Friends & family", "👥", False), ("Reading", "📖", False), ("Rest", "😌", False),
    ("Social media", "📱", True), ("YouTube / TV", "📺", True), ("Gaming", "🎮", True),
]
MAX_CATEGORIES = 16


class Repo:
    def __init__(self, conn: aiosqlite.Connection):
        self.conn = conn
        # one lock for read-modify-write sequences (override planning etc.)
        self.lock = asyncio.Lock()

    async def _one(self, sql: str, args=()) -> dict | None:
        async with self.conn.execute(sql, args) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def _all(self, sql: str, args=()) -> list[dict]:
        async with self.conn.execute(sql, args) as cur:
            rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def _exec(self, sql: str, args=()) -> aiosqlite.Cursor:
        cur = await self.conn.execute(sql, args)
        await self.conn.commit()
        return cur

    # ------------------------------------------------------------------ users
    async def get_user(self, user_id: int) -> dict | None:
        return await self._one("SELECT * FROM users WHERE id=?", (user_id,))

    async def create_user(self, user_id: int, chat_id: int, first_name: str | None,
                          now: datetime | None = None) -> None:
        await self._exec(
            "INSERT OR IGNORE INTO users(id, chat_id, first_name, onboarding_step, created_at)"
            " VALUES(?,?,?,?,?)", (user_id, chat_id, first_name, "tz", iso(now or utcnow())))

    async def update_user(self, user_id: int, **fields) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields)
        await self._exec(f"UPDATE users SET {cols} WHERE id=?", (*fields.values(), user_id))

    async def onboarded_users(self) -> list[dict]:
        return await self._all("SELECT * FROM users WHERE onboarding_step IS NULL")

    async def users_due(self, now_iso: str) -> list[dict]:
        return await self._all(
            "SELECT * FROM users WHERE onboarding_step IS NULL AND paused=0"
            " AND (next_ping_at IS NULL OR next_ping_at <= ?)", (now_iso,))

    async def delete_user(self, user_id: int) -> None:
        for table in ("entries", "pings", "goals", "limit_warnings", "insights", "categories"):
            await self.conn.execute(f"DELETE FROM {table} WHERE user_id=?", (user_id,))
        await self.conn.execute("DELETE FROM users WHERE id=?", (user_id,))
        await self.conn.commit()

    # ------------------------------------------------------------------ categories
    async def list_categories(self, user_id: int, active_only: bool = False) -> list[dict]:
        sql = "SELECT * FROM categories WHERE user_id=?"
        if active_only:
            sql += " AND active=1"
        return await self._all(sql + " ORDER BY sort, id", (user_id,))

    async def get_category(self, user_id: int, category_id: int) -> dict | None:
        return await self._one("SELECT * FROM categories WHERE user_id=? AND id=?",
                               (user_id, category_id))

    async def add_category(self, user_id: int, name: str, emoji: str | None, is_waste: bool) -> dict:
        existing = await self.list_categories(user_id)
        same_kind = [c for c in existing if bool(c["is_waste"]) == is_waste]
        palette = WASTE_COLORS if is_waste else NON_WASTE_COLORS
        color = palette[len(same_kind) % len(palette)]
        sort = max([c["sort"] for c in existing], default=-1) + 1
        cur = await self._exec(
            "INSERT INTO categories(user_id, name, emoji, is_waste, color, sort, active)"
            " VALUES(?,?,?,?,?,?,1)", (user_id, name, emoji or "•", int(is_waste), color, sort))
        return await self.get_category(user_id, cur.lastrowid)

    async def update_category(self, category_id: int, **fields) -> None:
        cols = ", ".join(f"{k}=?" for k in fields)
        await self._exec(f"UPDATE categories SET {cols} WHERE id=?", (*fields.values(), category_id))

    # ------------------------------------------------------------------ entries
    async def add_entry(self, user_id: int, category_id: int, start: datetime, end: datetime | None,
                        source: str, ping_id: int | None = None, note: str | None = None,
                        now: datetime | None = None) -> int:
        cur = await self._exec(
            "INSERT INTO entries(user_id, category_id, start_utc, end_utc, source, ping_id, note, created_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (user_id, category_id, iso(start), iso(end) if end else None, source, ping_id, note,
             iso(now or utcnow())))
        return cur.lastrowid

    async def get_entry(self, user_id: int, entry_id: int) -> dict | None:
        return await self._one("SELECT * FROM entries WHERE user_id=? AND id=?", (user_id, entry_id))

    async def entries_between(self, user_id: int, start: datetime, end: datetime) -> list[dict]:
        """Entries overlapping [start, end). A running timer (end_utc NULL) overlaps if it started before `end`."""
        return await self._all(
            "SELECT * FROM entries WHERE user_id=? AND start_utc < ?"
            " AND (end_utc IS NULL OR end_utc > ?) ORDER BY start_utc",
            (user_id, iso(end), iso(start)))

    async def running_entry(self, user_id: int) -> dict | None:
        return await self._one(
            "SELECT * FROM entries WHERE user_id=? AND end_utc IS NULL ORDER BY start_utc DESC LIMIT 1",
            (user_id,))

    async def users_with_running_timer(self) -> list[int]:
        rows = await self._all("SELECT DISTINCT user_id FROM entries WHERE end_utc IS NULL")
        return [r["user_id"] for r in rows]

    async def last_entry(self, user_id: int) -> dict | None:
        return await self._one(
            "SELECT * FROM entries WHERE user_id=? ORDER BY start_utc DESC, id DESC LIMIT 1", (user_id,))

    async def set_entry_times(self, entry_id: int, start: datetime, end: datetime | None) -> None:
        await self._exec("UPDATE entries SET start_utc=?, end_utc=? WHERE id=?",
                         (iso(start), iso(end) if end else None, entry_id))

    async def delete_entry(self, entry_id: int) -> None:
        await self._exec("DELETE FROM entries WHERE id=?", (entry_id,))

    async def delete_entries_by_ping(self, user_id: int, ping_id: int) -> None:
        await self._exec("DELETE FROM entries WHERE user_id=? AND ping_id=?", (user_id, ping_id))

    async def clone_entry(self, template: dict, start: datetime, end: datetime) -> int:
        return await self.add_entry(template["user_id"], template["category_id"], start, end,
                                    template["source"], template["ping_id"], template["note"])

    # ------------------------------------------------------------------ pings
    async def add_ping(self, user_id: int, message_id: int | None, start: datetime, end: datetime,
                       now: datetime | None = None) -> int:
        cur = await self._exec(
            "INSERT INTO pings(user_id, message_id, start_utc, end_utc, status, created_at)"
            " VALUES(?,?,?,?,'open',?)", (user_id, message_id, iso(start), iso(end), iso(now or utcnow())))
        return cur.lastrowid

    async def get_ping(self, ping_id: int) -> dict | None:
        return await self._one("SELECT * FROM pings WHERE id=?", (ping_id,))

    async def set_ping_message(self, ping_id: int, message_id: int | None) -> None:
        await self._exec("UPDATE pings SET message_id=? WHERE id=?", (message_id, ping_id))

    async def set_ping_status(self, ping_id: int, status: str) -> None:
        await self._exec("UPDATE pings SET status=? WHERE id=?", (status, ping_id))

    async def open_pings(self, user_id: int) -> list[dict]:
        return await self._all("SELECT * FROM pings WHERE user_id=? AND status='open'", (user_id,))

    # ------------------------------------------------------------------ goals
    async def list_goals(self, user_id: int) -> list[dict]:
        return await self._all("SELECT * FROM goals WHERE user_id=? AND active=1 ORDER BY id", (user_id,))

    async def get_goal(self, user_id: int, goal_id: int) -> dict | None:
        return await self._one("SELECT * FROM goals WHERE user_id=? AND id=? AND active=1", (user_id, goal_id))

    async def replace_goal(self, user_id: int, category_id: int, limit_min: int,
                           baseline: int | None, now: datetime | None = None) -> dict:
        await self.conn.execute("UPDATE goals SET active=0 WHERE user_id=? AND category_id=?",
                                (user_id, category_id))
        cur = await self.conn.execute(
            "INSERT INTO goals(user_id, category_id, daily_limit_min, baseline_avg_min, created_at, active)"
            " VALUES(?,?,?,?,?,1)", (user_id, category_id, limit_min, baseline, iso(now or utcnow())))
        await self.conn.commit()
        return await self._one("SELECT * FROM goals WHERE id=?", (cur.lastrowid,))

    async def deactivate_goal(self, goal_id: int) -> None:
        await self._exec("UPDATE goals SET active=0 WHERE id=?", (goal_id,))

    # ------------------------------------------------------------------ limit warnings
    async def add_limit_warning(self, user_id: int, category_id: int, local_date: str) -> bool:
        """True if this is the first warning for that category and day."""
        cur = await self._exec(
            "INSERT OR IGNORE INTO limit_warnings(user_id, category_id, local_date) VALUES(?,?,?)",
            (user_id, category_id, local_date))
        return cur.rowcount == 1

    # ------------------------------------------------------------------ insights
    async def add_insight(self, user_id: int, week_end_date: str, text: str, goal_json: str | None,
                          now: datetime | None = None) -> None:
        await self._exec(
            "INSERT INTO insights(user_id, week_end_date, text, goal_json, created_at) VALUES(?,?,?,?,?)",
            (user_id, week_end_date, text, goal_json, iso(now or utcnow())))

    async def latest_insight(self, user_id: int) -> dict | None:
        return await self._one(
            "SELECT * FROM insights WHERE user_id=? ORDER BY id DESC LIMIT 1", (user_id,))

    # ------------------------------------------------------------------ admin
    async def all_users(self) -> list[dict]:
        return await self._all("SELECT * FROM users")

    async def last_activity(self, user_id: int) -> str | None:
        row = await self._one("SELECT MAX(created_at) AS m FROM entries WHERE user_id=?", (user_id,))
        return row["m"] if row else None
