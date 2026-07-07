"""
bot.py
--------
Entry point. Picks the run mode automatically:

    - WEBHOOK_URL set in .env  -> runs an aiohttp webhook server (for a server/VPS/PaaS).
    - WEBHOOK_URL empty        -> runs long polling (for local development).

Run with:
    python bot.py
"""

import asyncio
import logging

from aiohttp import web

from config import BOT_TOKEN, WEBAPP_HOST, WEBAPP_PORT, WEBHOOK_PATH, WEBHOOK_URL
from core import bot

# Import handler modules so their @bot.message_handler decorators register.
# ORDER MATTERS: pyTelegramBotAPI tests handlers in registration order and
# stops at the first match, so specific commands must be imported BEFORE
# the catch-all anti-spam handler.
from handlers import help_command  # noqa: F401
from handlers import admin_commands  # noqa: F401
from handlers import stats_commands  # noqa: F401
from handlers import profile_command  # noqa: F401
from handlers import antispam  # noqa: F401  (must stay LAST)
from handlers.tracking import StatsMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")


async def run_polling():
    """Local development mode: long-poll Telegram for updates."""
    logger.info("Starting in POLLING mode (local development)...")
    await bot.remove_webhook()
    await bot.infinity_polling(skip_pending=True)


async def run_webhook():
    """Production mode: run an aiohttp server and let Telegram push updates to it.

    Assumes you're behind a reverse proxy / PaaS that terminates HTTPS
    (Render, Railway, Fly.io, nginx, Caddy, etc.) and forwards plain HTTP to
    this process - the common modern setup. If you're exposing this process
    directly to the internet with your own self-signed certificate instead,
    see pyTelegramBotAPI's webhook examples for the extra SSL context step.
    """
    from telebot.types import Update

    logger.info("Starting in WEBHOOK mode -> %s%s", WEBHOOK_URL, WEBHOOK_PATH)

    app = web.Application()

    async def handle_webhook(request: web.Request):
        if request.match_info.get("token") != BOT_TOKEN:
            return web.Response(status=403)
        update = Update.de_json(await request.json())
        await bot.process_new_updates([update])
        return web.Response()

    app.router.add_post("/webhook/{token}", handle_webhook)

    await bot.remove_webhook()
    await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    logger.info("Webhook server listening on %s:%s", WEBAPP_HOST, WEBAPP_PORT)

    await asyncio.Event().wait()  # keep the process alive


async def main():
    bot.setup_middleware(StatsMiddleware())
    try:
        if WEBHOOK_URL:
            await run_webhook()
        else:
            await run_polling()
    finally:
        try:
            await bot.close_session()
        except Exception:
            pass  # nothing to close if no request was ever made


if __name__ == "__main__":
    asyncio.run(main())