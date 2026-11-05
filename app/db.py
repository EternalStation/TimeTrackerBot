"""SQLite connection and schema (SPEC section 3)."""
from __future__ import annotations

import os

import aiosqlite

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  chat_id INTEGER NOT NULL,
  first_name TEXT,
  tz TEXT NOT NULL DEFAULT '+00:00',
  wake_time TEXT NOT NULL DEFAULT '08:00',
  sleep_time TEXT NOT NULL DEFAULT '23:00',
  ping_interval_min INTEGER NOT NULL DEFAULT 60,
  paused INTEGER NOT NULL DEFAULT 0,
  onboarding_step TEXT,
  challenge_start TEXT,
  last_checkin_at TEXT,
  next_ping_at TEXT,
  last_summary_date TEXT,
  last_weekly_report_date TEXT,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  name TEXT NOT NULL,
  emoji TEXT,
  is_waste INTEGER NOT NULL DEFAULT 0,
  color TEXT,
  sort INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_categories_user ON categories(user_id);
CREATE TABLE IF NOT EXISTS entries(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  category_id INTEGER NOT NULL,
  start_utc TEXT NOT NULL,
  end_utc TEXT,
  source TEXT NOT NULL,
  ping_id INTEGER,
  note TEXT,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entries_user_start ON entries(user_id, start_utc);
CREATE TABLE IF NOT EXISTS pings(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  message_id INTEGER,
  start_utc TEXT NOT NULL,
  end_utc TEXT NOT NULL,
  status TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pings_user ON pings(user_id, status);
CREATE TABLE IF NOT EXISTS goals(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  category_id INTEGER NOT NULL,
  daily_limit_min INTEGER NOT NULL,
  baseline_avg_min INTEGER,
  created_at TEXT NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS limit_warnings(
  user_id INTEGER NOT NULL,
  category_id INTEGER NOT NULL,
  local_date TEXT NOT NULL,
  PRIMARY KEY(user_id, category_id, local_date)
);
CREATE TABLE IF NOT EXISTS insights(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INTEGER NOT NULL,
  week_end_date TEXT NOT NULL,
  text TEXT NOT NULL,
  goal_json TEXT,
  created_at TEXT NOT NULL
);
"""


async def connect(path: str) -> aiosqlite.Connection:
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    conn = await aiosqlite.connect(path)
    conn.row_factory = aiosqlite.Row
    await conn.execute("PRAGMA journal_mode=WAL")
    await conn.execute("PRAGMA synchronous=NORMAL")
    await conn.executescript(SCHEMA)
    await conn.commit()
    return conn
