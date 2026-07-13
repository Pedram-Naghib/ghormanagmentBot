"""
utils/chat_config_cache.py
-----------------------------
WHY THIS EXISTS: every single group message used to trigger several
separate, sequential DB reads just to check restrictions - db.get_chat_locks(),
db.list_filtered_words(), db.get_chat_settings() (for the spam thresholds),
and now db.get_profanity_customizations() (for قفل فحش). In a busy group
that's several network round trips to Supabase PER MESSAGE, on top of
everything else, and was almost certainly a real part of the "bot feels
slow" complaint.

This caches all of them together, per chat, for a short TTL. On a cache
miss, the reads happen CONCURRENTLY (asyncio.gather) instead of one after
another, so even a first-touch/cold chat only pays ~1 round trip's worth
of latency instead of 4.

Trade-off: a lock/filter-word/spam-setting/profanity change can take up to
TTL_SECONDS to apply to already-in-flight messages in the worst case - but
every admin command that changes these ALSO calls invalidate(chat_id)
immediately, so in practice a change is live for the very next message, not
just "within the TTL". The TTL is really just a safety net for cache
staleness, not the primary invalidation path.
"""

import asyncio
import time
from typing import Optional

TTL_SECONDS = 30

_cache: dict[int, tuple[float, dict]] = {}


async def get_chat_config(db, chat_id: int) -> dict:
    entry = _cache.get(chat_id)
    if entry is not None and (time.monotonic() - entry[0]) < TTL_SECONDS:
        return entry[1]

    locks, filtered_words, settings, profanity = await asyncio.gather(
        db.get_chat_locks(chat_id),
        db.list_filtered_words(chat_id),
        db.get_chat_settings(chat_id),
        db.get_profanity_customizations(chat_id),
    )
    value = {
        "locks": locks, "filtered_words": filtered_words, "settings": settings,
        "profanity_added": profanity["added"], "profanity_removed": profanity["removed"],
    }
    _cache[chat_id] = (time.monotonic(), value)
    return value


def invalidate(chat_id: int) -> None:
    """Call this immediately after writing any lock/filter-word/chat-setting/
    profanity-word change for a chat, so the very next message sees it
    instead of waiting out the TTL."""
    _cache.pop(chat_id, None)