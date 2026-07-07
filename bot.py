"""
bot.py
--------
Entry point of the Telegram Group Management Bot.

Run with:
    python bot.py

See README.md for setup instructions.
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from config import BOT_TOKEN
from database import Database
from handlers import admin_commands, antispam, help_command, profile_command, stats_commands
from handlers.tracking import StatsTrackingMiddleware


async def main():
    logging.basicConfig(level=logging.INFO)

    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    # ---- Database ----
    db = Database()
    await db.connect()
    dp["db"] = db  # Injected automatically into any handler with a `db` parameter.

    # ---- Middleware: runs on every message, before any handler below ----
    dp.message.middleware(StatsTrackingMiddleware())

    # ---- Routers ----
    # ORDER MATTERS: more specific handlers (commands) must be registered
    # BEFORE the catch-all anti-spam router, since aiogram stops at the
    # first handler whose filters match.
    dp.include_router(help_command.router)
    dp.include_router(admin_commands.router)
    dp.include_router(stats_commands.router)
    dp.include_router(profile_command.router)
    dp.include_router(antispam.router)  # must stay LAST (catch-all)

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logging.info("Bot starting (polling mode)...")
        await dp.start_polling(bot)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
