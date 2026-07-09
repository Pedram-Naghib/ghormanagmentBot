"""
utils/panel_auth.py
----------------------
Fixes: "وقتی پنل دکمه شیشه‌ای باز میشه فقط کسی که پنل رو با هر کامندی گرفته
میتونه دکمه هاشو استفاده کنه" - only the person who opened a given panel
message may press its buttons; anyone else tapping gets a small alert
instead of the action silently applying (or worse, applying as if THEY
were the admin who opened it).

How: every panel callback_data is encoded as "pnl:<invoker_id>:<...parts>".
encode() builds it, decode() parses it, and verify_panel_callback() does
the actual invoker + live-permission check and answers the callback query
appropriately - callers just do:

    invoker_id, parts = await verify_panel_callback(call)
    if invoker_id is None:
        return  # already answered/rejected

This is ONLY for admin/settings panels (پنل, قفل‌ها, etc). The public
/help menu intentionally stays open to everyone and doesn't use this.
"""

from typing import List, Optional, Tuple

from telebot.types import CallbackQuery

from core import bot, db
from utils.permissions import is_authorized_admin

PREFIX = "pnl"


def encode(invoker_id: int, *parts: str) -> str:
    data = ":".join([PREFIX, str(invoker_id), *parts])
    if len(data.encode()) > 64:
        raise ValueError(f"callback_data too long ({len(data.encode())} bytes): {data}")
    return data


def decode(data: str) -> Optional[Tuple[int, List[str]]]:
    if not data or not data.startswith(PREFIX + ":"):
        return None
    segments = data.split(":")
    if len(segments) < 2:
        return None
    try:
        invoker_id = int(segments[1])
    except ValueError:
        return None
    return invoker_id, segments[2:]


async def verify_panel_callback(call: CallbackQuery) -> Tuple[Optional[int], List[str]]:
    """
    Returns (invoker_id, parts) if this press is legitimate, or (None, [])
    if it was rejected (an alert has already been shown to the user in
    that case - callers should just `return`).
    """
    decoded = decode(call.data)
    if decoded is None:
        return None, []
    invoker_id, parts = decoded

    if call.from_user.id != invoker_id:
        await bot.answer_callback_query(
            call.id,
            "⛔️ این پنل مخصوص کسی است که آن را باز کرده. برای استفاده، دستور مربوطه را خودتان اجرا کنید.",
            show_alert=True,
        )
        return None, []

    # Defense in depth: re-check live admin status too, in case the
    # invoker's role was revoked after the panel was opened.
    if not await is_authorized_admin(db, call.message.chat.id, invoker_id):
        await bot.answer_callback_query(
            call.id,
            "⛔️ دسترسی مدیریتی شما در این گروه گرفته شده است.",
            show_alert=True,
        )
        return None, []

    return invoker_id, parts