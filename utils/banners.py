"""
utils/banners.py
--------------------
Shared helper for the optional media banners registered via
"ثبت تصویر [کلید]" (see handlers/admin_commands.py's set_image) - a banner
can be a still photo, a GIF (animation), or a short video; this is the one
place that knows how to send whichever type was registered, so every
caller (start, راهنما, پنل, بن, میوت/سکوت, ...) doesn't have to.

Used by:
    handlers/start_command.py   -> key "start_banner"
    handlers/help_command.py    -> key "help_banner"
    handlers/panel_command.py   -> key "panel_banner"
    handlers/admin_commands.py  -> keys "ban_banner", "mute_banner"

Adding a new bannered command is: pick a key, call send_banner() with a
fallback to a plain bot.reply_to/send_message if it returns False.

IMPLEMENTATION NOTE: the actual bot.send_photo/send_animation/send_video
method is looked up at CALL time (getattr(bot, name) inside send_banner),
never captured as a bound method at import time - `core.bot` is a shared
singleton, and grabbing a bound method reference at module-import time
would silently keep pointing at whatever that method was when this module
first loaded (breaks under test mocking, and is fragile in general).
"""

from typing import Optional

from telebot.types import InlineKeyboardMarkup

from core import bot, db

_SEND_METHOD_NAME_BY_TYPE = {
    "photo": "send_photo",
    "animation": "send_animation",
    "video": "send_video",
}


async def send_banner(
    chat_id: int,
    key: str,
    caption: str,
    reply_markup: Optional[InlineKeyboardMarkup] = None,
    reply_to_message_id: Optional[int] = None,
) -> bool:
    """
    Sends the banner registered under `key` (if any) as a photo/GIF/video
    with `caption`. Returns True if something was sent. Returns False (and
    sends nothing) if no banner is registered for this key - the caller
    should fall back to a plain text message in that case.
    """
    asset = await db.get_asset(key)
    if not asset:
        return False

    method_name = _SEND_METHOD_NAME_BY_TYPE.get(asset["content_type"], "send_photo")
    send = getattr(bot, method_name)  # resolved at CALL time, not import time - see module docstring
    await send(
        chat_id,
        asset["file_id"],
        caption=caption,
        reply_markup=reply_markup,
        reply_to_message_id=reply_to_message_id,
    )
    return True


def is_banner_message(content_type: str) -> bool:
    """True for any message content_type a banner could have been sent as -
    use this instead of a bare `content_type == "photo"` check when deciding
    whether to editMessageCaption vs editMessageText on a message that might
    be a banner (see handlers/help_command.py, handlers/panel_command.py)."""
    return content_type in ("photo", "animation", "video")