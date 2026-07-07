"""
core.py
---------
Shared singletons: the bot instance and the database instance.

Every handler module does `from core import bot, db` instead of creating its
own instances. This avoids a circular import between bot.py (which imports
the handler modules to register them) and the handler modules themselves
(which need the bot instance to register handlers on).
"""

from telebot.async_telebot import AsyncTeleBot
from telebot import asyncio_helper

from config import BOT_TOKEN
from database import Database

# ── Proxy Configuration ───────────────────────────────────
# This routes the bot's traffic through your local VPN/Proxy 
# to prevent the ClientConnectorError / RequestTimeout.
# Adjust the port (e.g., 10809 for HTTP, 10808 for SOCKS5) to match your system.

# asyncio_helper.proxy = 'http://127.0.0.1:10809'
asyncio_helper.proxy = 'socks5://127.0.0.1:10808'
# ──────────────────────────────────────────────────────────

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

bot = AsyncTeleBot(BOT_TOKEN, parse_mode="HTML")
db = Database()