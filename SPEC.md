# TimeTracker bot: prototype spec (v1)

Telegram bot + Telegram Mini App dashboard. Users run a "7-day time audit": the bot pings them every N minutes, they tap what they were doing, and they see where their time goes and how much of it is "waste". UI language: **English**. Audience for v1: a demo for an influencer + 10–15 friends. Hosting: Railway (one service, always on). AI: Claude API.

## 1. Stack

- Python 3.12+ (dev container has 3.13), single process:
  - `aiogram` 3.x, long polling (no webhook)
  - `aiohttp` web server (aiogram already depends on it) serving the Mini App static files and JSON API on `$PORT`
  - background asyncio loop (tick every 30 s) for pings, summaries, live limit checks
- Storage: SQLite via `aiosqlite`, file at `$DB_PATH` (Railway volume mounted at `/data`). Store all timestamps as UTC ISO-8601 strings. Create the schema on startup (`CREATE TABLE IF NOT EXISTS`).
- `anthropic` SDK (AsyncAnthropic) for weekly insights. Optional: without a key, a rule-based fallback is used.
- `Pillow` for the shareable weekly card PNG. Fonts: Inter (OFL), copy `Inter-Regular.otf` and `Inter-Bold.otf` from `/usr/share/fonts/opentype/inter/` into `app/assets/fonts/` together with the OFL license text. No emoji on the card.
- Frontend: plain HTML/CSS/JS in `app/web/static/` (no build step). Telegram WebApp JS `https://telegram.org/js/telegram-web-app.js`, Chart.js pinned `https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js`.
- Tests: `pytest` + `pytest-asyncio`.

## 2. Config (env vars)

| var | required | default | meaning |
|---|---|---|---|
| `BOT_TOKEN` | yes (except `WEB_ONLY=1`) | — | from BotFather |
| `PUBLIC_URL` | yes for Mini App | — | e.g. `https://timetracker.up.railway.app` (no trailing slash) |
| `ANTHROPIC_API_KEY` | no | — | enables AI insights |
| `ANTHROPIC_MODEL` | no | `claude-haiku-5-5` | model id |
| `DB_PATH` | no | `./data/timetracker.db` | Railway: `/data/timetracker.db` |
| `ADMIN_IDS` | no | — | comma-separated Telegram user ids allowed to use `/admin_stats` |
| `PORT` | no | `8080` | Railway sets it |
| `DEV_MODE` | no | `0` | `1` = API also accepts header `X-Dev-User: <telegram_user_id>` without initData |
| `WEB_ONLY` | no | `0` | `1` = start only the web server (no bot, no scheduler) for local testing |
| `CHALLENGE_DAYS` | no | `7` | audit length |

## 3. Data model (SQLite)

```
users(
  id INTEGER PRIMARY KEY,            -- telegram user id
  chat_id INTEGER NOT NULL,
  first_name TEXT,
  tz TEXT NOT NULL DEFAULT '+00:00', -- either fixed offset "+01:00"/"-05:30" or IANA "Europe/Warsaw"
  wake_time TEXT NOT NULL DEFAULT '08:00',
  sleep_time TEXT NOT NULL DEFAULT '23:00',  -- may be < wake_time (window crosses midnight, e.g. 01:00)
  ping_interval_min INTEGER NOT NULL DEFAULT 60,  -- allowed: 30,45,60,90,120
  paused INTEGER NOT NULL DEFAULT 0,
  onboarding_step TEXT,              -- NULL when onboarded
  challenge_start TEXT,              -- local date YYYY-MM-DD of day 1 (set when onboarding finishes)
  last_checkin_at TEXT,              -- UTC; start of the next un-logged interval
  next_ping_at TEXT,                 -- UTC
  last_summary_date TEXT,            -- local date of the last daily summary sent
  last_weekly_report_date TEXT,
  created_at TEXT NOT NULL
)
categories(id INTEGER PK AUTOINCREMENT, user_id, name TEXT, emoji TEXT, is_waste INTEGER, color TEXT, sort INTEGER, active INTEGER DEFAULT 1)
entries(id INTEGER PK AUTOINCREMENT, user_id, category_id, start_utc TEXT, end_utc TEXT NULL /* NULL = running timer */,
        source TEXT /* 'checkin' | 'manual' | 'timer' */, ping_id INTEGER NULL, note TEXT NULL, created_at TEXT)
pings(id INTEGER PK AUTOINCREMENT, user_id, message_id INTEGER, start_utc TEXT, end_utc TEXT,
      status TEXT /* 'open' | 'answered' | 'skipped' | 'expired' */, created_at TEXT)
goals(id INTEGER PK AUTOINCREMENT, user_id, category_id, daily_limit_min INTEGER, baseline_avg_min INTEGER NULL,
      created_at TEXT, active INTEGER DEFAULT 1)
limit_warnings(user_id, category_id, local_date TEXT, PRIMARY KEY(user_id, category_id, local_date))
insights(id INTEGER PK AUTOINCREMENT, user_id, week_end_date TEXT, text TEXT, goal_json TEXT NULL, created_at TEXT)
```

Category colors: assigned server-side from a fixed palette when a category is created. Non-waste categories get cool/neutral colors, waste categories get warm colors (reds/oranges/pinks), so waste stands out in every chart. Palette (use in order):
- non-waste: `#4C7DF0 #2BB3A3 #7C5CDB #3A9BDC #5FA35A #8A94A6 #C08B2C #2F6D8C #A3B86C`
- waste: `#F0564A #F28C38 #E8487F #D9622B`

## 4. Default categories (onboarding template)

| name | emoji | waste |
|---|---|---|
| Work | 💼 | no |
| Study | 📚 | no |
| Exercise | 🏃 | no |
| Chores & cooking | 🍳 | no |
| Eating | 🍽 | no |
| Commute | 🚌 | no |
| Friends & family | 👥 | no |
| Reading | 📖 | no |
| Rest | 😌 | no |
| Social media | 📱 | yes |
| YouTube / TV | 📺 | yes |
| Gaming | 🎮 | yes |

Max 16 active categories per user. Custom categories: name ≤ 24 chars, emoji optional (default `•`).

## 5. Time rules

- `tz` helper: `+HH:MM`/`-HH:MM` → `datetime.timezone(timedelta(...))`, otherwise `zoneinfo.ZoneInfo`.
- Awake window for a local date D: from `D wake_time` to `sleep_time` (same day, or next day if `sleep_time <= wake_time`).
- Day views split entries at local midnight (clip). Sleep is not tracked; minutes outside the awake window are ignored in "untracked".
- `awake_minutes` for a day = length of the awake window clipped to [window start, min(window end, now)] (so today counts only elapsed time).
- `untracked_minutes` = awake_minutes − minutes covered by entries inside the awake window (never negative).
- `tracked_minutes` = minutes covered by entries (inside the day). `waste_minutes` = tracked minutes in waste categories. `waste_share` = waste/tracked (0 if tracked = 0).
- A day is **logged** if tracked ≥ 50% of awake_minutes.
- Challenge day number = (today_local − challenge_start).days + 1.

## 6. Check-in (ping) logic — the core loop

Scheduler tick every 30 s, for each user with `onboarding_step IS NULL` and `paused = 0` and `next_ping_at <= now`:

1. If a timer is running (entry with `end_utc IS NULL`): don't ping; `next_ping_at = now + interval`. Continue.
2. If `now` is outside the awake window: set `last_checkin_at` = start of the next awake window, `next_ping_at` = that start + interval. Continue.
3. Interval: `start = max(last_checkin_at, current window start)`, `end = now`. If `end − start < 10 min`: `next_ping_at = now + interval`, continue. **Cap**: if `end − start > 2 × interval`, set `start = end − interval` (older time stays untracked; user can fill it via /log or the Mini App).
4. Mark all of the user's `open` pings as `expired` and edit those messages to: `⏭ Skipped HH:MM–HH:MM (fill it in with /log if you want)` (remove keyboard; ignore Telegram errors).
5. Send ping message: `🕐 What were you doing 14:00–15:00?` with inline keyboard:
   - row 1 (only if the user has a previous entry): `↩️ Same: 💼 Work`
   - then active categories, 2 per row: `💼 Work`
   - last row: `✂️ Mixed` · `🙈 Skip`
   Callback data must fit 64 bytes: e.g. `p:<ping_id>:c:<category_id>`, `p:<ping_id>:mix`, `p:<ping_id>:skip`.
6. Save ping row (`open`), `next_ping_at = now + interval`.
7. If the awake window ends before `next_ping_at`, schedule the final ping exactly at window end (`next_ping_at = window_end`), so the last interval of the day gets asked.

Answering a ping:
- Category tap → create `checkin` entries for `[ping.start, ping.end]` **only over free time** (subtract existing entries; may produce several fragments; skip fragments < 1 min). Ping → `answered`. `last_checkin_at = max(last_checkin_at, ping.end)`. Edit message: `✅ 14:00–15:00 · 💼 Work` with button `✏️ Change`.
- `✏️ Change` → shows the category keyboard again; picking replaces the entries with this `ping_id`.
- Expired ping tapped → still allowed (fills free time in its interval) — users often answer late.
- `🙈 Skip` → `skipped`, no entries, `last_checkin_at = max(..., ping.end)`.
- `✂️ Mixed` → reply: "Log the parts like `14:00-14:40 work` or open the dashboard → Add entry." Ping stays open.
- After any entry change → run the limit check (§9).

## 7. Manual logging and timer

- Free-text message matching `^(yesterday\s+)?(\d{1,2}[:.]\d{2})\s*[-–—]\s*(\d{1,2}[:.]\d{2}|now)\s+(.+)$` (case-insensitive) → manual entry. Category matched by case-insensitive name prefix / contains; if 0 or >1 matches → ask with category keyboard (keep pending state in memory or a small `pending` table). End before start → error message. Ranges in the future → clipped to now.
- `/log` without args → instructions with 2 examples and the Mini App button.
- Manual and timer entries **override** overlapping existing entries (trim / split / delete the old ones). Rule: precise beats coarse.
- Timer: reply-keyboard button `▶️ Start` (or `/timer`) → category keyboard → running entry (`end_utc NULL`, source `timer`); any running timer is stopped first. `⏹ Stop` (or `/stop`) → `end_utc = now`, resolve overlaps, `last_checkin_at = max(last_checkin_at, now)`, reply `⏹ 💼 Work · 1h 25m`.
- Persistent reply keyboard (after onboarding): `[▶️ Start] [⏹ Stop]` / `[➕ Log] [📊 Dashboard]` where Dashboard is a `KeyboardButton(web_app=WebAppInfo(url=PUBLIC_URL + "/app/"))`.
- On startup call `set_chat_menu_button` with a `MenuButtonWebApp(text="Dashboard", web_app=WebAppInfo(url=PUBLIC_URL + "/app/"))` (skip if `PUBLIC_URL` is empty).

## 8. Onboarding (`/start`)

1. Greeting (short, friendly, says it's a 7-day time audit, ~5 sec per check-in).
2. "What time is it for you right now? Send it like `14:05`." → compute offset vs UTC rounded to 15 min → `tz = "+HH:MM"`. (Also `/timezone Europe/Warsaw` accepts IANA later.)
3. Wake time: buttons `06:00 07:00 08:00 09:00 10:00` + "other: send like 07:30".
4. Sleep time: buttons `22:00 23:00 00:00 01:00` + other.
5. Categories: inline toggle keyboard with the template (✅ = selected; all selected by default) + `➕ Add my own` + `Next →`.
6. Waste marking: same keyboard but toggling 🔥 = waste (template defaults pre-marked) + `Next →`. Text: "Which of these feel like wasted time for you? Be honest, only you see this."
7. Ping interval: `30 45 60 90 120 min` (60 recommended).
8. Done: `challenge_start = today local`, `last_checkin_at = now`, `next_ping_at = now + interval` (or next window start), show reply keyboard and a short how-to (3 lines).

## 9. Goals & limits

- `/goals` or Mini App: pick a waste category + daily limit (`15m 30m 45m 1h 1h30 2h 3h`). Store `baseline_avg_min` = average daily minutes of that category over the last 7 days.
- Limit check after every entry change and every tick for running timers: if today's used minutes (including the running timer) ≥ limit and no row in `limit_warnings` for today → send `⚠️ Social media: 1h 05m today. Your limit is 1h.` and insert the warning row.

## 10. Reports

- **Daily summary**: 20 min after the awake window ends (once per local date): totals by category (top 6, `💼 Work 3h 10m`), waste total + share, untracked, limits status, challenge `Day 3/7`, button `📊 Open dashboard` (inline WebApp button).
- **Weekly report**: in the same tick when the challenge day 7 has ended (and then every 7 days): stats for the 7 days + the share card PNG (§11) + AI insight (§12) + inline button `🎯 Set goal: Social media ≤ 1h/day` that creates the suggested goal. Save to `insights`.
- `/today` and `/week` commands send the same summaries on demand (week = last 7 days).

## 11. Share card

1080×1350 PNG, clean light background, Inter font:
- small top label `MY 7-DAY TIME AUDIT`
- big number: total waste hours `18h 40m` + line `of my awake time went to things I call waste`
- line `that's 2h 40m a day`
- horizontal bars for top 5 categories (category color, name, hours) with waste bars marked by a small `WASTE` tag
- footer `tracked with @<bot_username>`
Function: `render_week_card(stats, bot_username) -> bytes`.

## 12. AI weekly insight

- Input: compact JSON of the week (per-category minutes per day, waste flags, avg per day, waste by hour-of-day buckets, untracked minutes, logged days, current goals).
- System prompt: calm practical coach, no moralizing, no guilt, plain English, concrete. Output **JSON only**: `{"insights": ["...", "...", "..."], "goal": {"category_id": 12, "daily_limit_min": 60, "reason": "..."}}`. Each insight ≤ 25 words, at least one insight mentions a specific time of day if the data shows a pattern.
- Timeout 30 s, max_tokens 600. Any error / missing key / invalid JSON → rule-based fallback: biggest waste category by avg/day, `daily_limit_min = max(15, floor_to_15(avg * 0.7))`, 2–3 template insights (biggest waste category, worst day, untracked share).

## 13. Mini App API (JSON)

Auth: every `/api/*` request sends header `X-Telegram-Init-Data: <Telegram.WebApp.initData>`. Server validates per Telegram docs: `secret = HMAC_SHA256(key=b"WebAppData", msg=BOT_TOKEN)`, `hash = hex(HMAC_SHA256(key=secret, msg=data_check_string))`, where data_check_string = all fields except `hash`, sorted by key, `key=value` joined by `\n`. Reject if `auth_date` older than 7 days. User id from the `user` JSON field. `DEV_MODE=1` also accepts `X-Dev-User: <id>`. Unknown user → 404 `{"error":"not_registered"}`. Errors → `{"error": "<code>", "message": "..."}` with 4xx.

Durations are integers in minutes. Times are local `"HH:MM"`; `start_min`/`end_min` are minutes from local midnight of that date (0–1440).

`GET /api/me`
```json
{"user": {"first_name": "Nik", "tz": "+01:00", "wake_time": "08:00", "sleep_time": "23:00",
          "ping_interval_min": 60, "paused": false, "challenge_day": 4, "challenge_days": 7,
          "today": "2026-11-04"},
 "categories": [{"id": 1, "name": "Work", "emoji": "💼", "is_waste": false, "color": "#4C7DF0", "active": true}]}
```

`GET /api/day?date=YYYY-MM-DD` (default today)
```json
{"date": "2026-11-04",
 "awake_start_min": 480, "awake_end_min": 1380,
 "awake_minutes": 600, "tracked_minutes": 480, "untracked_minutes": 120,
 "waste_minutes": 135, "waste_share": 0.28,
 "totals": [{"category_id": 1, "minutes": 240}],
 "entries": [{"id": 55, "category_id": 1, "start": "09:00", "end": "11:00", "start_min": 540, "end_min": 660,
              "source": "checkin", "note": null}],
 "running": {"entry_id": 60, "category_id": 10, "start": "17:40", "start_min": 1060, "minutes": 25},
 "limits": [{"goal_id": 3, "category_id": 10, "limit_min": 60, "used_min": 75}]}
```
`running` is `null` when no timer. `totals` sorted desc by minutes. Running timer minutes are included in totals.

`GET /api/week?end=YYYY-MM-DD` (7 days ending at `end`, default today)
```json
{"start": "2026-10-29", "end": "2026-11-04",
 "days": [{"date": "2026-10-29", "label": "Thu", "tracked_minutes": 700, "untracked_minutes": 140,
           "waste_minutes": 190, "logged": true,
           "totals": [{"category_id": 1, "minutes": 300}]}],
 "totals": [{"category_id": 10, "minutes": 840, "avg_per_day": 120}],
 "tracked_minutes": 4600, "untracked_minutes": 900, "waste_minutes": 1120, "waste_share": 0.24,
 "prev_waste_minutes": 1350,
 "days_logged": 5,
 "waste_by_hour": [0, 0, 0, 0, 0, 0, 0, 5, 10, 0, 0, 0, 30, 20, 0, 0, 0, 0, 0, 25, 60, 80, 70, 40],
 "insight": {"text": "• ...\n• ...", "created_at": "2026-11-04T21:20:00Z"}}
```
`insight` is the latest saved insight or `null`. `prev_waste_minutes` = waste in the 7 days before `start` (null if user started after that).

`GET /api/goals`
```json
{"goals": [{"id": 3, "category_id": 10, "daily_limit_min": 60, "today_used_min": 75,
            "week_avg_min": 95, "baseline_avg_min": 130}]}
```

`POST /api/entries` body `{"category_id": 1, "date": "2026-11-04", "start": "14:00", "end": "15:30", "note": null}` → `{"ok": true, "entry": {...same shape as day entries}}`. Manual override rules (§7). `end <= start` → 400 `bad_range`. Future → clipped to now; fully future → 400.

`DELETE /api/entries/{id}` → `{"ok": true}` (only own entries; deleting a running timer stops nothing else).

`POST /api/goals` body `{"category_id": 10, "daily_limit_min": 60}` → `{"ok": true, "goal": {...}}` (replaces an existing active goal for that category).
`DELETE /api/goals/{id}` → `{"ok": true}`.

`GET /health` → `ok`. Static Mini App served at `/app/` (index.html) and `/app/*`.

## 14. Other commands

- `/settings`: inline menu → interval, wake/sleep, timezone (send local time again), categories (toggle active, toggle waste, add custom), pause/resume.
- `/pause`, `/resume`.
- `/privacy`: what is stored (activity log, settings, Telegram id/name), used only to show you your stats; aggregated anonymous numbers may be shown to the bot owner; `/delete_me` erases everything.
- `/delete_me` → confirm button → delete all rows of the user.
- `/help`: short list of commands.
- `/admin_stats` (ADMIN_IDS only): users total / onboarded / active in last 24 h; **day-7 completion** = among users whose challenge_start ≤ today−7, how many have ≥ 5 logged days in their first 7 days; average waste min/day across users; top 5 waste category names by total minutes (aggregate by name, anonymous).

## 15. Demo data

`python -m app.seed --user <telegram_id> [--days 7]` creates (or resets) a user with default categories and realistic entries for the last N days (work blocks, meals, evening social media/YouTube peaks 20:00–23:00, a few gaps, slightly lower waste on the last days) + one goal + one saved insight. Used for the influencer demo and screenshots.

## 16. Deployment (Railway)

- `requirements.txt`, `Procfile` (`web: python -m app.main`), `railway.json` (startCommand, healthcheck `/health`), `.env.example`, `README.md`.
- README steps: BotFather (`/newbot`, token), GitHub repo, Railway new project from repo, add Volume mounted at `/data`, set env vars, Generate Domain → `PUBLIC_URL`, redeploy, open bot → `/start`. Also how to run locally (`WEB_ONLY=1 DEV_MODE=1` + seed + open `http://localhost:8080/app/?dev_user=<id>`).
