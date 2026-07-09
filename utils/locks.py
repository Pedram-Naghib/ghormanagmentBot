"""
utils/locks.py
-----------------
Single source of truth for the قفل‌ها (content-type locks) shown in the
panel (/پنل). Adding a brand new lock type is ONE new entry in LOCKS below
plus a detector function - the panel keyboard, the toggle callback, and
the enforcement in handlers/antispam.py all pick it up automatically.

Locks only ever apply to "Normal" members (see utils/permissions.py) -
owners, admins, and VIPs are always exempt, exactly like the pre-panel
hardcoded link/forward rule worked.

DEFAULT_ON exists so that groups already running the bot before the panel
existed keep their exact old behavior (link + forward were hardcoded on)
without needing a database migration - a missing chat_locks row falls back
to this default instead of "off".
"""

from dataclasses import dataclass
from typing import Callable

from telebot.types import Message

LOCKS_DEFAULT_ON = {"link", "forward"}


def _has_link(message: Message) -> bool:
    import re

    entities = list(message.entities or []) + list(getattr(message, "caption_entities", None) or [])
    if any(e.type in ("url", "text_link") for e in entities):
        return True
    text = message.text or message.caption or ""
    url_regex = re.compile(
        r"((https?://|www\.)\S+|\b[a-zA-Z0-9-]+\.(com|ir|net|org|io|me|co|info|xyz|link)\b)",
        re.IGNORECASE,
    )
    return bool(url_regex.search(text))


def _is_forward(message: Message) -> bool:
    return bool(
        getattr(message, "forward_from", None)
        or getattr(message, "forward_from_chat", None)
        or getattr(message, "forward_origin", None)
    )


def _is_file(message: Message) -> bool:
    return message.content_type == "document"


def _is_sticker(message: Message) -> bool:
    return message.content_type == "sticker"


def _is_voice(message: Message) -> bool:
    return message.content_type in ("voice", "video_note")


def _is_gif(message: Message) -> bool:
    return message.content_type == "animation"


def _is_contact(message: Message) -> bool:
    return message.content_type == "contact"


def _is_poll(message: Message) -> bool:
    return message.content_type == "poll"


def _has_hashtag(message: Message) -> bool:
    entities = list(message.entities or []) + list(getattr(message, "caption_entities", None) or [])
    return any(e.type == "hashtag" for e in entities)


def _has_mention(message: Message) -> bool:
    entities = list(message.entities or []) + list(getattr(message, "caption_entities", None) or [])
    return any(e.type in ("mention", "text_mention") for e in entities)


@dataclass
class LockDef:
    key: str
    label: str
    detector: Callable[[Message], bool]


# Order here = order shown in the panel keyboard.
LOCKS = [
    LockDef("link", "لینک", _has_link),
    LockDef("forward", "فوروارد", _is_forward),
    LockDef("file", "فایل", _is_file),
    LockDef("sticker", "استیکر", _is_sticker),
    LockDef("voice", "ویس", _is_voice),
    LockDef("gif", "گیف", _is_gif),
    LockDef("contact", "مخاطب", _is_contact),
    LockDef("poll", "نظرسنجی", _is_poll),
    LockDef("hashtag", "هشتگ", _has_hashtag),
    LockDef("mention", "منشن", _has_mention),
]

LOCKS_BY_KEY = {lock.key: lock for lock in LOCKS}


def is_lock_enabled(locks_row: dict, key: str) -> bool:
    """locks_row is whatever db.get_chat_locks(chat_id) returned."""
    if key in locks_row:
        return locks_row[key]
    return key in LOCKS_DEFAULT_ON