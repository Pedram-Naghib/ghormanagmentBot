"""
utils/mentions.py
--------------------
Single shared helper for turning a Telegram user into a clickable
tg://user?id=... hyperlink - used EVERYWHERE the bot displays a member's
name (ban/mute/vip/warn confirmations, admin/VIP/warned-user lists,
profile, stats, owner-detection messages, ...) so tapping a name always
opens that person's Telegram profile instead of just showing inert text.

Two entry points depending on what you have on hand:
    - mention(user) -> pass an actual telebot User/Member object (has
      .id/.first_name/.last_name/.username) - the common case when you
      already resolved a target via _resolve_target().
    - mention_by_id(user_id, display_name) -> pass a raw id + a name string
      you already fetched some other way (e.g. db.get_user_display_name()
      results in a list/loop, where you only have an id and a name, not a
      full user object).
"""


def _full_name(user) -> str:
    return " ".join(filter(None, [getattr(user, "first_name", None), getattr(user, "last_name", None)])) or (
        f"@{user.username}" if getattr(user, "username", None) else str(user.id)
    )


def mention(user) -> str:
    """user must have .id, and ideally .first_name/.last_name/.username."""
    name = _full_name(user)
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def mention_by_id(user_id: int, display_name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{display_name}</a>'