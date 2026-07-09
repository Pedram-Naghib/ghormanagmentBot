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
from utils.locks import LOCKS, is_lock_enabled
from utils.permissions import is_normal_member
from utils.text import normalize_fa

# In-memory recent-message timestamps, per chat, per user.
# Kept in memory (not the DB) on purpose: this is ephemeral, high-frequency
# rate-limiting data that doesn't need to survive a restart.
_recent_messages: Dict[int, Dict[int, Deque[float]]] = defaultdict(lambda: defaultdict(deque))


async def _check_locks(message: Message) -> bool:
    """
    Rule 1: delete messages tripping any content-type lock that's ON for
    this chat (پنل -> قفل‌ها). See utils/locks.py for the list and for how
    an unconfigured chat falls back to the pre-panel defaults (link+forward).
    """
    locks_row = await db.get_chat_locks(message.chat.id)
    for lock in LOCKS:
        if is_lock_enabled(locks_row, lock.key) and lock.detector(message):
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception:
                pass
            return True
    return False


async def _check_filtered_words(message: Message) -> bool:
    """Rule 2: delete messages containing any admin-defined filtered word."""
    text = normalize_fa(message.text or message.caption or "")
    if not text:
        return False
    words = await db.list_filtered_words(message.chat.id)
    if not words:
        return False
    lowered = text.lower()
    for word in words:
        if normalize_fa(word).lower() in lowered:
            try:
                await bot.delete_message(message.chat.id, message.message_id)
            except Exception:
                pass
            return True
    return False


async def _check_spam_rate(message: Message) -> bool:
    """Rule 2: mute users sending too many messages too fast (per-chat threshold)."""
    settings = await db.get_chat_settings(message.chat.id)
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
    """Centralized entry point for ALL restrictions applied to Normal members."""
    if await _check_locks(message):
        return True

    if await _check_filtered_words(message):
        return True

    if await _check_spam_rate(message):
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