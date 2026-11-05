"""User-facing texts in the Spent voice: a dry cashier. Clear first, funny second, never guilt."""

BRAND = "Spent"
TAGLINE = "Your day, itemized."

GREETING = (
    "Spent. Your day, itemized.\n\n"
    "I ping you every hour or so: what were you doing? Tap a button, five seconds.\n"
    "Every night I hand you a receipt for the day.\n"
    "Seven days in, you get the full audit.\n\n"
    "Setup first. What time is it for you right now? Send it like 14:05."
)
ASK_TZ_AGAIN = "Can't ring that up. Send the current time in 24h format, like 14:05."
ASK_WAKE = "When do you usually wake up? Pick one, or send your own time like 07:30."
ASK_SLEEP = "And bedtime? Pick one, or send your own time like 23:30."
ASK_CATEGORIES = ("What fills your day? These are the items on your receipt. "
                  "Tap to switch them off or on, or add your own.")
ASK_WASTE = ("Which of these do you call waste? Your call, and only you see it.\n"
             "🔥 = waste")
ASK_INTERVAL = "How often should I check in? 60 minutes works for most people. Shorter means a more exact receipt and more pings."
ASK_CUSTOM = "Send the name of your category, with an emoji if you like. Example: 🎲 Board games"

HOW_TO = (
    "You're set. How the store works:\n"
    "1. I ask what you were doing, say 14:00–15:00. Tap the answer.\n"
    "2. Missed something? Send 14:00-15:30 work (or yesterday 22:00-23:00 gaming).\n"
    "3. ▶️ Start and ⏹ Stop run a live timer. 📊 Dashboard has the numbers.\n\n"
    "Your first receipt prints after your day ends."
)
ALREADY_SET = "You already have a tab here. /settings changes things, /help has the menu."

HELP = (
    "The menu:\n"
    "/today  today's receipt\n"
    "/week  the last 7 days, with a cashier's note\n"
    "/dashboard  open the dashboard\n"
    "/log  add time by hand, e.g. 14:00-15:30 work\n"
    "/timer and /stop  live timer\n"
    "/goals  daily limits for waste categories\n"
    "/settings  interval, wake and sleep times, categories\n"
    "/timezone  change your timezone, e.g. /timezone Europe/Warsaw\n"
    "/pause and /resume  close or reopen the store\n"
    "/privacy  what I keep\n"
    "/delete_me  erase everything"
)

LOG_HELP = (
    "Missed a purchase? Send it like this:\n"
    "14:00-15:30 work\n"
    "yesterday 22:00-23:15 gaming\n"
    "Use now as the end time for something still going: 17:40-now youtube.\n"
    "Or add an entry in the dashboard with a few taps."
)

PRIVACY = (
    "What I keep: your Telegram id and first name, your settings, and the log you create "
    "(what you did, and when).\n\n"
    "It's used to show you your own stats and nothing else. The bot owner sees anonymous totals "
    "(like how many people finished the week), not your log.\n\n"
    "/delete_me wipes it all. I don't keep a copy of the receipts."
)


def ping_question(label: str) -> str:
    """label like '14:00–15:00'."""
    return f"🧾 New line item: what were you doing {label}?"


def ping_expired(label: str) -> str:
    return f"⏭ Skipped {label}. No charge. /log can still add it."
