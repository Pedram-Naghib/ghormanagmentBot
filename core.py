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

from config import BOT_TOKEN
from database import Database

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set. Copy .env.example to .env and fill it in.")

bot = AsyncTeleBot(BOT_TOKEN, parse_mode="HTML")
db = Database()