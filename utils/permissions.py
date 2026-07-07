"""
utils/permissions.py
----------------------
Role model (per your spec):

    Global Owner  -> hardcoded in .env (OWNER_USER_IDS). Full access,
                     every group, always. Not stored in the database.

    owner         -> whoever added the bot to a specific group. Auto-set
                     the moment the bot joins (see handlers/tracking.py ->
                     on_bot_added_to_chat). Full access, but ONLY in that
                     group. Can appoint 'admin' and 'vip' for their group.

    admin         -> appointed by that group's owner (or a Global Owner).
                     Full access, but ONLY in that group. Cannot appoint
                     more admins (that stays with the owner).

    vip           -> exempt from anti-spam restrictions, but ONLY in that
                     group - VIP in Group A is a plain Normal member in
                     Group B unless Group B separately grants it.

    normal        -> default for everyone else.

Being a real Telegram admin/creator of a group does NOT, by itself, grant
bot-command access. Telegram admin status is checked in exactly one place -
the "ادعای مالکیت" bootstrap command, for groups where the bot was added
before this role system existed and so has no recorded owner yet.
"""

from telebot.async_telebot import AsyncTeleBot

from config import OWNER_USER_IDS
from database import Database

ADMIN_STATUSES = {"administrator", "creator"}


def is_global_owner(user_id: int) -> bool:
    return user_id in OWNER_USER_IDS


async def is_group_admin(bot: AsyncTeleBot, chat_id: int, user_id: int) -> bool:
    """Real Telegram admin/creator status - used ONLY by the ownership-claim bootstrap."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ADMIN_STATUSES
    except Exception:
        return False


async def is_authorized_admin(db: Database, chat_id: int, user_id: int) -> bool:
    """True if the user can use management commands in THIS chat."""
    if is_global_owner(user_id):
        return True
    role = await db.get_user_role(chat_id, user_id)
    return role in ("owner", "admin")


async def can_manage_chat_roles(db: Database, chat_id: int, user_id: int) -> bool:
    """
    True if the user can appoint/remove admins and VIPs for this chat -
    restricted to the chat's owner (and Global Owners), deliberately NOT
    extended to regular admins.
    """
    if is_global_owner(user_id):
        return True
    role = await db.get_user_role(chat_id, user_id)
    return role == "owner"


async def is_normal_member(db: Database, chat_id: int, user_id: int) -> bool:
    """A 'Normal' member is not an authorized admin and not a VIP, in THIS chat."""
    if await is_authorized_admin(db, chat_id, user_id):
        return False
    role = await db.get_user_role(chat_id, user_id)
    return role != "vip"