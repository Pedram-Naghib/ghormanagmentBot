"""
utils/permissions.py
----------------------
Role model (per your spec):

    Global Owner  -> hardcoded in .env (OWNER_USER_IDS). Full access,
                     every group, always. Not stored in the database.
                     Outranks everyone below, everywhere.

    owner   (مالک اصلی)  -> whoever added the bot to a specific group.
                     Auto-set the moment the bot joins (see
                     handlers/tracking.py -> on_bot_added_to_chat). Full
                     management access, ONLY in that group. Can appoint
                     AND remove owner2/admin/vip - "عزل همه".

    owner2  (مالک ۲)      -> appointed by the group's owner (or Global
                     Owner). Full management access, ONLY in that group.
                     Can appoint/remove admin and vip, but NOT another
                     owner2 or the owner - "عزل ادمین و ویژه".

    admin   (ادمین)       -> appointed by owner or owner2. Full management
                     access, ONLY in that group. Can appoint/remove vip
                     only - "عزل ویژه". Cannot touch admin/owner2/owner.

    vip     (ویژه)        -> exempt from anti-spam restrictions, ONLY in
                     that group - VIP in Group A is a plain Normal member
                     in Group B unless Group B separately grants it.

    normal  (عادی)        -> default for everyone else.

--------------------------------------------------------------------------
HIERARCHY / RANKS
--------------------------------------------------------------------------
ROLE_RANK below encodes the "من می‌تونم فلانی رو عزل/ارتقا بدم یا نه؟" rule
as one simple comparison: an actor may appoint-to or remove-from a given
role ONLY IF their own rank is STRICTLY GREATER than that role's rank.
That single rule produces exactly your spec:
    owner (4)  > owner2 (3) > admin (2) > vip (1) > normal (0)
  - owner  can manage owner2, admin, vip (ranks 3,2,1)   -> "عزل همه"
  - owner2 can manage admin, vip (ranks 2,1), NOT owner2  -> "عزل ادمین و ویژه"
  - admin  can manage vip (rank 1) only, NOT admin/owner2 -> "عزل ویژه"
This same rank comparison is also used for ban/mute/kick target
protection (see handlers/admin_commands.py:_refuse_if_protected) - an
admin should no more be able to ban an owner2 than demote one.

Being a real Telegram admin/creator of a group does NOT, by itself, grant
bot-command access. Telegram admin status is checked in exactly one place -
the "ادعای مالکیت" bootstrap command, for groups where the bot was added
before this role system existed and so has no recorded owner yet.
"""

from telebot.async_telebot import AsyncTeleBot

from config import OWNER_USER_IDS
from database import Database
from utils import global_admins

ADMIN_STATUSES = {"administrator", "creator"}

# Higher = more powerful. Global Owner/Global Admin isn't in here - it's
# handled separately below since it's above the per-chat role system
# entirely (env-hardcoded OR dynamically promoted - see is_super_admin()).
ROLE_RANK = {"owner": 4, "owner2": 3, "admin": 2, "vip": 1, "normal": 0}
GLOBAL_OWNER_RANK = 100  # always above everything

ROLE_LABELS_FA = {
    "owner": "👑 مالک اصلی",
    "owner2": "👑 مالک ۲",
    "admin": "👮‍♂️ ادمین",
    "vip": "⭐️ ویژه",
    "normal": "👤 عادی",
}

MANAGEMENT_ROLES = ("owner", "owner2", "admin")  # can all run ban/mute/warn/etc.


def is_global_owner(user_id: int) -> bool:
    """STRICT/hardcoded only - OWNER_USER_IDS in .env. Prefer is_super_admin()
    below for actual access decisions; this is kept separate because a few
    things (like WHO may promote a new ادمین کل) are deliberately
    restricted to the hardcoded set only, not to dynamic ادمین کل too."""
    return user_id in OWNER_USER_IDS


def is_super_admin(user_id: int) -> bool:
    """True for a hardcoded Global Owner OR a dynamically-promoted
    ادمین کل (Global Admin) - both get IDENTICAL full access, every group,
    always. This is an in-memory set lookup (utils/global_admins.py), not a
    DB call, since this runs on every single group message."""
    return is_global_owner(user_id) or global_admins.is_global_admin(user_id)


async def is_group_admin(bot: AsyncTeleBot, chat_id: int, user_id: int) -> bool:
    """Real Telegram admin/creator status - used ONLY by the ownership-claim bootstrap."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ADMIN_STATUSES
    except Exception:
        return False


async def get_rank(db: Database, chat_id: int, user_id: int) -> int:
    """The actor's rank in THIS chat - a super admin always wins regardless
    of any per-chat role they may or may not also have."""
    if is_super_admin(user_id):
        return GLOBAL_OWNER_RANK
    role = await db.get_user_role(chat_id, user_id)
    return ROLE_RANK.get(role, 0)


async def is_authorized_admin(db: Database, chat_id: int, user_id: int) -> bool:
    """True if the user can use management commands (ban/mute/warn/panel/
    etc.) in THIS chat - owner, owner2, and admin all qualify equally;
    the hierarchy only matters for WHO CAN APPOINT/REMOVE WHOM, see
    can_assign_role() below."""
    if is_super_admin(user_id):
        return True
    role = await db.get_user_role(chat_id, user_id)
    return role in MANAGEMENT_ROLES


async def can_assign_role(db: Database, chat_id: int, user_id: int, target_role: str) -> bool:
    """True if `user_id` may appoint someone TO `target_role`, or remove
    someone currently holding it, in THIS chat. One rule covers every case
    in the hierarchy - see the module docstring."""
    actor_rank = await get_rank(db, chat_id, user_id)
    return actor_rank > ROLE_RANK.get(target_role, 0)


async def can_manage_chat_roles(db: Database, chat_id: int, user_id: int) -> bool:
    """Back-compat alias: can appoint/remove admins (owner or owner2)."""
    return await can_assign_role(db, chat_id, user_id, "admin")


async def outranks(db: Database, chat_id: int, actor_id: int, target_id: int) -> bool:
    """True if `actor_id` outranks `target_id` in THIS chat - used to
    protect ban/mute/kick targets the same way the role hierarchy protects
    appoint/remove: an admin can no more ban an owner2 than demote one."""
    actor_rank = await get_rank(db, chat_id, actor_id)
    if is_super_admin(target_id):
        return False  # nobody outranks a super admin, ever
    target_role = await db.get_user_role(chat_id, target_id)
    return actor_rank > ROLE_RANK.get(target_role, 0)


async def is_normal_member(db: Database, chat_id: int, user_id: int) -> bool:
    """A 'Normal' member is not an authorized admin and not a VIP, in THIS chat.
    Runs on EVERY group message (see handlers/antispam.py), so this fetches
    the role exactly once."""
    if is_super_admin(user_id):
        return False
    role = await db.get_user_role(chat_id, user_id)
    return role not in MANAGEMENT_ROLES and role != "vip"