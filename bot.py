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

from config import BOT_TOKEN, MESSAGE_LOG_RETENTION_DAYS, WEBAPP_HOST, WEBAPP_PORT, WEBHOOK_PATH, WEBHOOK_URL
from core import bot, db
from docs_page import register_docs_route

# Import handler modules so their @bot.message_handler decorators register.
# ORDER MATTERS: pyTelegramBotAPI tests handlers in registration order and
# stops at the first match, so specific commands must be imported BEFORE
# the catch-all anti-spam handler.
from handlers import start_command  # noqa: F401
from handlers import help_command  # noqa: F401
from handlers import admin_commands  # noqa: F401
from handlers import stats_commands  # noqa: F401
from handlers import profile_command  # noqa: F401
from handlers import panel_command  # noqa: F401
from handlers import captcha  # noqa: F401
from handlers import antispam  # noqa: F401  (must stay LAST)
from handlers.tracking import StatsMiddleware

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("bot")


async def _set_command_menu():
    """
    Every command in this bot is now plain Persian text («بن», «پنل»،
    «راهنما», ...) instead of a "/" command - see handlers/*.py. So there's
    nothing left to put in Telegram's "/" command-menu popup; we explicitly
    clear it (delete_my_commands) rather than leave stale "/ban", "/help",
    etc. entries that would look tappable but no longer do anything.

    NOTE: "/start" itself still technically works (see handlers/
    start_command.py for why - it's a platform mechanic, not a real
    command) but is deliberately NOT listed here, since it isn't something
    a person is meant to type by hand.
    """
    try:
        await bot.delete_my_commands()
    except Exception as e:
        logger.warning("Could not clear command menu: %s", e)


ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member", "chat_join_request"]

CLEANUP_INTERVAL_SECONDS = 6 * 60 * 60  # every 6 hours


async def _message_log_cleanup_loop():
    """
    message_logs stores one row PER MESSAGE (needed for «آمار روزانه» and
    for «حذف N»/«حذف کل» to find real message_ids to delete) and would
    otherwise grow forever, unlike the running counters in group_users
    (messages_all_time - what «آمار کل» actually reads, unaffected by this).
    This prunes anything older than MESSAGE_LOG_RETENTION_DAYS on a timer so
    storage stays bounded regardless of how chatty a group gets - see the
    comment on MESSAGE_LOG_RETENTION_DAYS in config.py for the trade-offs.
    """
    while True:
        try:
            deleted = await db.cleanup_old_message_logs(MESSAGE_LOG_RETENTION_DAYS)
            if deleted:
                logger.info("message_logs cleanup: removed %d rows older than %d days", deleted, MESSAGE_LOG_RETENTION_DAYS)
        except Exception as e:
            logger.warning("message_logs cleanup failed: %s", e)
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)


async def run_polling():
    """Local development mode: long-poll Telegram for updates."""
    logger.info("Starting in POLLING mode (local development)...")
    await bot.remove_webhook()
    await bot.infinity_polling(skip_pending=True, allowed_updates=ALLOWED_UPDATES)


async def run_webhook():
    """Production mode: run an aiohttp server and let Telegram push updates to it.

    Assumes you're behind a reverse proxy / PaaS that terminates HTTPS
    (Render, Railway, Fly.io, nginx, Caddy, etc.). If you're exposing this
    process directly with your own self-signed certificate instead, see
    pyTelegramBotAPI's webhook examples for the extra SSL context step.
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
    register_docs_route(app)  # GET /docs -> full human-readable guide (see docs_page.py)

    await bot.remove_webhook()
    await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}", allowed_updates=ALLOWED_UPDATES)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, WEBAPP_HOST, WEBAPP_PORT)
    await site.start()
    logger.info("Webhook server listening on %s:%s", WEBAPP_HOST, WEBAPP_PORT)
    logger.info("Full guide available at %s/docs", WEBHOOK_URL)

    await asyncio.Event().wait()  # keep the process alive


async def main():
    logger.info("Connecting to the database...")
    await db.connect()  # opens the asyncpg pool AND creates tables if missing

    bot.setup_middleware(StatsMiddleware())
    await _set_command_menu()
    asyncio.create_task(_message_log_cleanup_loop())
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
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())