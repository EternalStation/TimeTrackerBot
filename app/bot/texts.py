"""User-facing texts. Plain and short."""

GREETING = (
    "Hi! I'm a 7-day time audit.\n\n"
    "Every hour or so I'll ask what you were doing. You tap one button, it takes about 5 seconds. "
    "After a week you'll see where your time really goes, and how much of it you'd call wasted.\n\n"
    "Let's set it up. First, what time is it for you right now? Send it like 14:05."
)
ASK_TZ_AGAIN = "I need the current time in 24h format, like 14:05."
ASK_WAKE = "When do you usually wake up? Pick one, or send your own time like 07:30."
ASK_SLEEP = "And when do you go to sleep? Pick one, or send your own time like 23:30."
ASK_CATEGORIES = ("What do you spend your day on? Tap to switch categories off or on, "
                  "or add your own.")
ASK_WASTE = ("Which of these feel like wasted time for you? Be honest, only you see this.\n"
             "🔥 = waste")
ASK_INTERVAL = "How often should I check in? 60 minutes works well for most people."
ASK_CUSTOM = "Send the name of your category, with an emoji if you like. Example: 🎲 Board games"

HOW_TO = (
    "You're set. Here's how it works:\n"
    "1. I'll message you with a question like \"What were you doing 14:00-15:00?\". Tap the answer.\n"
    "2. Forgot something? Send 14:00-15:30 work (or yesterday 22:00-23:00 gaming).\n"
    "3. Use ▶️ Start and ⏹ Stop for a live timer, and 📊 Dashboard to see your stats."
)
ALREADY_SET = "You're already set up. Use /settings to change anything, or /help for the command list."

HELP = (
    "/today  today's summary\n"
    "/week  last 7 days with insights\n"
    "/log  add time by hand, e.g. 14:00-15:30 work\n"
    "/timer and /stop  live timer\n"
    "/goals  daily limits for waste categories\n"
    "/settings  interval, wake and sleep times, categories\n"
    "/timezone  change your timezone, e.g. /timezone Europe/Warsaw\n"
    "/pause and /resume  stop or restart check-ins\n"
    "/privacy  what I store\n"
    "/delete_me  erase all your data"
)

LOG_HELP = (
    "To add time by hand, send a message like:\n"
    "14:00-15:30 work\n"
    "yesterday 22:00-23:15 gaming\n"
    "Use now as the end time for something that's still going: 17:40-now youtube.\n"
    "Or use the dashboard to add an entry with a few taps."
)

PRIVACY = (
    "What I store: your Telegram id and first name, your settings, and the activity log you create "
    "(what you did and when).\n\n"
    "It's used only to show you your own stats. The bot owner can see aggregated, anonymous numbers "
    "(for example how many people finished the week), not your individual log.\n\n"
    "/delete_me erases everything about you."
)
