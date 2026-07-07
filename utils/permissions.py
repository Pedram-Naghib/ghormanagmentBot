"""
utils/permissions.py
----------------------
Role model:

    Owner        -> hardcoded in .env (OWNER_USER_IDS). Can add/remove Bot Admins.
    Bot Admin    -> stored in Supabase (`bot_admins` table, bot-wide - see
                    "افزودن ادمین" in handlers/admin_commands.py). Can use
                    management commands in ANY group this bot is in, even
                    if they hold no special Telegram role in that group.
    Group Admin  -> real Telegram admin/creator of THIS group (checked live
                    via the Bot API - no manual list to maintain).
    VIP          -> stored per-user in Supabase (`users.is_vip`). Exempt
                    from anti-spam restrictions.
    Normal       -> everyone else.

"management command access" = Owner OR Bot Admin OR Group Admin.
"""

from telebot.async_telebot import AsyncTeleBot

from config import OWNER_USER_IDS
from database import Database

ADMIN_STATUSES = {"administrator", "creator"}


def is_owner(user_id: int) -> bool:
    return user_id in OWNER_USER_IDS


async def is_group_admin(bot: AsyncTeleBot, chat_id: int, user_id: int) -> bool:
    """True if the user is a real admin/creator of THIS Telegram group."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ADMIN_STATUSES
    except Exception:
        return False


async def is_authorized_admin(bot: AsyncTeleBot, db: Database, chat_id: int, user_id: int) -> bool:
    """
    True if the user can use management commands (ban/mute/etc.) in this chat -
    either because they're a Bot Admin (bot-wide, DB-managed, doesn't require
    being a Telegram admin here) or a real admin of this specific group.
    """
    if is_owner(user_id):
        return True
    if await db.is_bot_admin(user_id):
        return True
    return await is_group_admin(bot, chat_id, user_id)


async def is_normal_member(bot: AsyncTeleBot, db: Database, chat_id: int, user_id: int) -> bool:
    """A 'Normal' member is not an authorized admin and not VIP."""
    if await is_authorized_admin(bot, db, chat_id, user_id):
        return False
    if await db.is_vip(user_id):
        return False
    return True