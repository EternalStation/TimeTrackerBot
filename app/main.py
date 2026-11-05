"""Entry point: web server + (unless WEB_ONLY=1) the Telegram bot and the scheduler."""
from __future__ import annotations

import asyncio
import logging

from aiohttp import web

from .config import Config
from .db import connect
from .repo import Repo
from .web.server import create_app

log = logging.getLogger("main")


def build_dispatcher(repo: Repo, cfg: Config):
    from aiogram import Dispatcher

    from .bot import admin, checkin, goals, onboarding, privacy, settings, timer
    from .bot import manual
    from .bot import reports as bot_reports

    dp = Dispatcher()
    dp["repo"] = repo
    dp["cfg"] = cfg
    # order matters: onboarding text first, the catch-all free-text handler (manual) last
    for module in (onboarding, settings, checkin, timer, goals, bot_reports, admin, privacy, manual):
        dp.include_router(module.router)
    return dp


BOT_NAME = "Spent"
SHORT_DESCRIPTION = "Your day, itemized. I ask what you did, you tap, and every night you get a receipt."
DESCRIPTION = (
    "Spent: your day, itemized.\n\n"
    "I ping you every hour or so and ask what you were doing. You tap one button. "
    "Every night I print a receipt for your day, and after 7 days you get the full audit: "
    "what you spent your time on, and what you'd call a waste.\n\n"
    "No lectures. No refunds. Tap Start to open a tab."
)
COMMANDS = [
    ("start", "Open a tab"), ("today", "Today's receipt"), ("week", "Weekly receipt"),
    ("dashboard", "Open the dashboard"), ("log", "Add time by hand"), ("timer", "Start a live timer"),
    ("stop", "Stop the timer"), ("goals", "Daily limits for waste"), ("settings", "Interval, hours, categories"),
    ("pause", "Close the store for now"), ("resume", "Reopen the store"), ("privacy", "What I keep"),
    ("help", "The menu"),
]
PROFILE_CALL_TIMEOUT = 10


async def _profile_call(label: str, coro) -> None:
    try:
        await asyncio.wait_for(coro, PROFILE_CALL_TIMEOUT)
        log.info("bot profile: %s ok", label)
    except Exception as exc:
        log.warning("bot profile: %s failed: %s", label, exc)


async def setup_bot_profile(bot) -> None:
    """Name, descriptions and command menu. Never raises, every call is isolated."""
    from aiogram.types import BotCommand

    # Telegram rate-limits set_my_name hard: only call it when the name differs.
    try:
        current = await asyncio.wait_for(bot.get_my_name(), PROFILE_CALL_TIMEOUT)
        needs_name = (getattr(current, "name", "") or "") != BOT_NAME
    except Exception as exc:
        log.warning("bot profile: get_my_name failed: %s", exc)
        needs_name = False
    if needs_name:
        await _profile_call("set_my_name", bot.set_my_name(name=BOT_NAME))
    await _profile_call("set_my_short_description",
                        bot.set_my_short_description(short_description=SHORT_DESCRIPTION))
    await _profile_call("set_my_description", bot.set_my_description(description=DESCRIPTION))
    await _profile_call("set_my_commands", bot.set_my_commands(
        [BotCommand(command=c, description=d) for c, d in COMMANDS]))


async def run(cfg: Config) -> None:
    if not cfg.web_only and not cfg.bot_token:
        raise SystemExit("BOT_TOKEN is not set. Set it, or use WEB_ONLY=1 for the web server only.")
    conn = await connect(cfg.db_path)
    repo = Repo(conn)
    bot = None
    if not cfg.web_only:
        from aiogram import Bot
        bot = Bot(cfg.bot_token)

    app = create_app(cfg, repo, bot)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", cfg.port).start()
    log.info("web server on port %s (web_only=%s, dev_mode=%s)", cfg.port, cfg.web_only, cfg.dev_mode)

    try:
        if cfg.web_only:
            await asyncio.Event().wait()
        else:
            from aiogram.types import MenuButtonWebApp, WebAppInfo

            from .scheduler import run_scheduler
            dp = build_dispatcher(repo, cfg)
            me = await bot.get_me()
            profile_task = asyncio.create_task(setup_bot_profile(bot))   # background: never delays startup
            if cfg.webapp_url:
                try:
                    await bot.set_chat_menu_button(menu_button=MenuButtonWebApp(
                        text="Dashboard", web_app=WebAppInfo(url=cfg.webapp_url)))
                except Exception as exc:
                    log.warning("could not set menu button: %s", exc)
            else:
                log.warning("PUBLIC_URL is not set: the Dashboard button will not open the Mini App")
            scheduler = asyncio.create_task(run_scheduler(bot, repo, cfg, me.username or ""))
            try:
                await dp.start_polling(bot)
            finally:
                scheduler.cancel()
                profile_task.cancel()
    finally:
        await runner.cleanup()
        if bot:
            await bot.session.close()
        await conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(run(Config.from_env()))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
