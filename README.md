# TimeTracker bot

A Telegram bot for a 7-day time audit. Every hour or so it asks "What were you doing 14:00-15:00?",
you tap one button, and after a week you see where your time went and how much of it you call waste.
There is also a Mini App dashboard (opens inside Telegram) and a shareable weekly card.

It is one small Python program: the bot, the web server for the dashboard, and a background timer all run
in the same process. Data is stored in a SQLite file.

## Deploy to Railway (about 15 minutes)

You need a Telegram account, a GitHub account and a Railway account.

1. **Create the bot.** In Telegram, open @BotFather and send `/newbot`. Pick a name and a username
   (it must end in `bot`). BotFather replies with a token that looks like `123456:ABC-DEF...`.
   Copy it and keep it secret.
2. **Put the code on GitHub.** Create a new repository and upload this whole folder to it
   (or push it with git). The `.env` file and the `data/` folder are ignored on purpose.
3. **Create the Railway project.** On railway.app click *New Project*, then *Deploy from GitHub repo*,
   and choose your repository. The first build will start. It may fail or crash until the next steps are
   done. That is fine.
4. **Add a Volume.** Open the service, go to *Settings* (or press `Ctrl+K` and search "volume"), add a Volume
   and set the mount path to `/data`. This is where the database lives. Without a volume your data is lost
   on every redeploy.
5. **Set the variables.** Open the *Variables* tab and add:

   | Name | Value |
   |---|---|
   | `BOT_TOKEN` | the token from BotFather |
   | `DB_PATH` | `/data/timetracker.db` |
   | `ANTHROPIC_API_KEY` | optional, from console.anthropic.com. Without it the weekly tips are rule-based |
   | `ADMIN_IDS` | optional, your Telegram user id (use @userinfobot to find it) to allow `/admin_stats` |

6. **Get a public address.** In *Settings* under *Networking* click *Generate Domain*. You get something like
   `https://timetracker-production.up.railway.app`. Add one more variable:
   `PUBLIC_URL` = that address, with no slash at the end.
7. **Redeploy.** Click *Deploy* (or *Redeploy* on the latest deployment). Wait until it shows as active.
   Opening `https://your-domain/health` in a browser should show `ok`.
8. **Try it.** Open your bot in Telegram and send `/start`. Answer the setup questions, and you are in.
   The *Dashboard* button next to the message box opens the Mini App.

Keep the service running on a single instance. The bot uses long polling, so two copies would fight
over the same messages.

### All settings

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `BOT_TOKEN` | yes (not with `WEB_ONLY=1`) | | token from BotFather |
| `PUBLIC_URL` | for the dashboard | | public https address, no trailing slash |
| `ANTHROPIC_API_KEY` | no | | turns on AI insights |
| `ANTHROPIC_MODEL` | no | `claude-haiku-5-5` | model used for insights |
| `DB_PATH` | no | `./data/timetracker.db` | database file (`/data/timetracker.db` on Railway) |
| `ADMIN_IDS` | no | | comma-separated Telegram ids allowed to use `/admin_stats` |
| `PORT` | no | `8080` | Railway sets this by itself |
| `DEV_MODE` | no | `0` | `1` lets the API accept an `X-Dev-User` header. Never use on a public server |
| `WEB_ONLY` | no | `0` | `1` starts only the web server, no bot |
| `CHALLENGE_DAYS` | no | `7` | length of the audit |

## Run it on your computer

You need Python 3.12 or newer.

```bash
pip install -r requirements.txt
```

**Only the dashboard, with fake data (no Telegram needed):**

```bash
export DB_PATH=./data/demo.db
python -m app.seed --user 111 --days 7
WEB_ONLY=1 DEV_MODE=1 python -m app.main
```

Then open <http://localhost:8080/app/?dev_user=111>.
`python -m app.seed` can be run again at any time, it resets that user. Add `--tz Europe/Warsaw` to change
the timezone of the demo user.

**The real bot:**

```bash
export BOT_TOKEN=123456:ABC-DEF...
export PUBLIC_URL=https://your-tunnel.example.com   # optional, needed for the dashboard button
python -m app.main
```

(`.env.example` lists every variable. The app reads environment variables only, it does not load a `.env` file
by itself.)

**Tests:**

```bash
python -m pytest -q
```

## Commands

`/start` set up, `/today`, `/week`, `/log`, `/timer`, `/stop`, `/goals`, `/settings`, `/timezone`,
`/pause`, `/resume`, `/privacy`, `/delete_me`, `/help`, and `/admin_stats` for admins.

You can also send a line like `14:00-15:30 work` or `yesterday 22:00-23:15 gaming` to add time by hand.

## Notes

- All times are stored in UTC and shown in each person's own timezone.
- The data model, check-in rules and API are described in `SPEC.md`.
- Receipt PNGs use DejaVu Sans Mono (`app/assets/fonts/DejaVu-LICENSE.txt`). Brand images for BotFather: `python -m app.brand` writes `app/assets/brand/avatar.png` and `description.png`.
