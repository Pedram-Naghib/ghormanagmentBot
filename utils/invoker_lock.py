"""
utils/invoker_lock.py
------------------------
Generic "only the person who opened this message may press its buttons"
helper for inline keyboards OTHER than /panel (see utils/panel_auth.py for
that one - it also re-checks live admin status, which not every keyboard
needs).

Used by:
  - handlers/help_command.py -> /help's section buttons. Previously these
    were intentionally public (anyone could tap them); per request, they're
    now locked to whichever person actually ran «راهنما»//start/«پنل» ->
    «راهنما» for THIS particular help message.
  - handlers/admin_commands.py -> the «حذف کل» confirmation buttons.

callback_data layout: "<namespace>:<invoker_id>:<...parts>"
"""

from typing import List, Optional, Tuple

from telebot.types import CallbackQuery

from core import bot

DEFAULT_DENIAL_TEXT = "⛔️ این دکمه مخصوص کسی است که این پیام را باز کرده."


def encode(namespace: str, invoker_id: int, *parts: str) -> str:
    data = ":".join([namespace, str(invoker_id), *parts])
    if len(data.encode()) > 64:
        raise ValueError(f"callback_data too long ({len(data.encode())} bytes): {data}")
    return data


def decode(data: str, namespace: str) -> Optional[Tuple[int, List[str]]]:
    if not data or not data.startswith(namespace + ":"):
        return None
    segments = data.split(":")
    if len(segments) < 2:
        return None
    try:
        invoker_id = int(segments[1])
    except ValueError:
        return None
    return invoker_id, segments[2:]


async def verify(
    call: CallbackQuery, namespace: str, denial_text: str = DEFAULT_DENIAL_TEXT
) -> Tuple[Optional[int], List[str]]:
    """
    Returns (invoker_id, parts) if this press is legitimate, or (None, [])
    if it was rejected (an alert has already been shown - callers should
    just `return`).
    """
    decoded = decode(call.data, namespace)
    if decoded is None:
        return None, []
    invoker_id, parts = decoded

    if call.from_user.id != invoker_id:
        await bot.answer_callback_query(call.id, denial_text, show_alert=True)
        return None, []

    return invoker_id, parts