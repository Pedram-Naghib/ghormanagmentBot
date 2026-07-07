"""
core.py
---------
Shared singletons: the bot instance and the database instance.

Every handler module does `from core import bot, db` instead of creating its
own instances, avoiding a circular import between bot.py (which imports the
handler modules to register them) and the handler modules themselves (which
need the bot instance to register handlers on).
"""

from telebot import asyncio_helper
from telebot.async_telebot import AsyncTeleBot

from config import BOT_TOKEN, PROXY_URL
from database import Database

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

# Only route through a proxy if PROXY_URL is actually set - leaving this
# unconditional breaks the bot for anyone without that exact local proxy
# running, and breaks it outright on a server deploy where no such proxy
# exists. Set PROXY_URL in .env only if Telegram is blocked where you run this.
if PROXY_URL:
    asyncio_helper.proxy = PROXY_URL

bot = AsyncTeleBot(BOT_TOKEN, parse_mode="HTML")
db = Database()