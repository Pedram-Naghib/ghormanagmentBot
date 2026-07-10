"""
handlers/antispam.py
----------------------
Centralized restrictions for "Normal" members (see utils/permissions.py for
who counts as Normal vs VIP vs admin in THIS chat).

*** Single place to add new anti-spam rules. *** To add one:
    1. Write `async def _check_something(message) -> bool` (True = acted on it).
    2. Call it inside `apply_normal_member_restrictions()`.

This module MUST be imported LAST in bot.py: pyTelegramBotAPI tests handlers
in the order they were registered and stops at the first match, so this
catch-all has to come after every specific command handler.
"""

import time
from collections import defaultdict, deque
from typing import Deque, Dict

from telebot.types import ChatPermissions, Message

from core import bot, db
from utils import chat_config_cache
from utils.locks import LOCKS, is_lock_enabled
from utils.permissions import is_normal_member
from utils.text import normalize_fa

# In-memory recent-message timestamps, per chat, per user.
# Kept in memory (not the DB) on purpose: this is ephemeral, high-frequency
# rate-limiting data that doesn't need to survive a restart.
_recent_messages: Dict[int, Dict[int, Deque[float]]] = defaultdict(lambda: defaultdict(deque))


def _check_locks(message: Message, locks_row: dict) -> bool:
    """Rule 1: does this message trip any content-type lock that's ON for
    this chat (پنل -> قفل‌ها)? See utils/locks.py for the list and for how
    an unconfigured chat falls back to the pre-panel defaults (link+forward)."""
    return any(is_lock_enabled(locks_row, lock.key) and lock.detector(message) for lock in LOCKS)


def _check_filtered_words(message: Message, filtered_words: list) -> bool:
    """Rule 2: does this message contain any admin-defined filtered word?"""
    if not filtered_words:
        return False
    text = normalize_fa(message.text or message.caption or "")
    if not text:
        return False
    lowered = text.lower()
    return any(normalize_fa(word).lower() in lowered for word in filtered_words)


async def _check_spam_rate(message: Message, settings: dict) -> bool:
    """Rule 3: mute users sending too many messages too fast (per-chat threshold)."""
    limit = settings["spam_message_limit"]
    window = settings["spam_time_window_seconds"]
    mute_minutes = settings["spam_mute_minutes"]

    chat_id = message.chat.id
    user_id = message.from_user.id
    now = time.time()

    timestamps = _recent_messages[chat_id][user_id]
    timestamps.append(now)
    while timestamps and now - timestamps[0] > window:
        timestamps.popleft()

    if len(timestamps) > limit:
        timestamps.clear()
        until = int(now + mute_minutes * 60)
        try:
            await bot.restrict_chat_member(
                chat_id,
                user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            await bot.send_message(
                chat_id,
                f"⛔️ کاربر {message.from_user.full_name} به دلیل ارسال پیام‌های زیاد "
                f"در زمان کوتاه، به مدت {mute_minutes} دقیقه سکوت (Mute) شد.",
            )
        except Exception:
            pass
        return True
    return False


async def apply_normal_member_restrictions(message: Message) -> bool:
    """Centralized entry point for ALL restrictions applied to Normal members.

    Fetches this chat's locks/filtered-words/spam-settings ONCE (cached -
    see utils/chat_config_cache.py) instead of each rule querying the DB
    separately, cutting this from 3 sequential DB round trips per message
    down to ~0-1.
    """
    config = await chat_config_cache.get_chat_config(db, message.chat.id)

    if _check_locks(message, config["locks"]):
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return True

    if _check_filtered_words(message, config["filtered_words"]):
        try:
            await bot.delete_message(message.chat.id, message.message_id)
        except Exception:
            pass
        return True

    if await _check_spam_rate(message, config["settings"]):
        return True

    # <-- Add future restrictions here.

    return False


CATCH_ALL_CONTENT_TYPES = [
    "text", "photo", "video", "document", "audio",
    "voice", "sticker", "animation", "video_note", "contact", "poll",
]


@bot.message_handler(chat_types=["group", "supergroup"], content_types=CATCH_ALL_CONTENT_TYPES)
async def guard_normal_members(message: Message):
    """Catch-all for group messages not matched by any handler registered above."""
    if not message.from_user or message.from_user.is_bot:
        return

    if await is_normal_member(db, message.chat.id, message.from_user.id):
        await apply_normal_member_restrictions(message)