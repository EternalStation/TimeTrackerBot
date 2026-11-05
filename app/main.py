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
