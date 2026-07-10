"""
handlers/admin_commands.py
-----------------------------
Management commands. Usable by (see utils/permissions.py):
    - Global Owners   (hardcoded in .env -> OWNER_USER_IDS) - everywhere
    - Group Owners    (whoever added the bot to THIS group) - this group only
    - Group Admins    (appointed by that group's owner) - this group only

Triggered as plain Persian text, sent as a REPLY to the target user's message.

All incoming text is run through normalize_fa() before matching, because
some keyboards (iOS especially) send Arabic Yeh/Kaf instead of Persian
Yeh/Kaf - see utils/text.py for the full explanation. Without this,
anything containing ی or ک (پروفایل, آمار کل, میوت, سکوت, ...) can silently
fail to match depending on the sender's keyboard.

--------------------------------------------------------------------
A NOTE ON "کیک" vs "بن" (kick vs ban)
--------------------------------------------------------------------
Telegram only has one underlying action here: banChatMember, which removes
the user AND blocks them from rejoining via invite link until someone
unbans them. A "kick" is just a ban immediately followed by an unban. This
bot keeps it simple: کیک/بن/اخراج all do the same thing - remove the user
AND keep them banned until an admin runs "رفع بن".
"""

import re
import time
from dataclasses import dataclass
from typing import Optional

from telebot.types import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core import bot, db
from utils.invoker_lock import decode as invoker_decode, encode as invoker_encode, verify as invoker_verify
from utils import global_admins
from utils.permissions import (
    MANAGEMENT_ROLES,
    ROLE_LABELS_FA,
    can_assign_role,
    is_authorized_admin,
    is_global_owner,
    is_group_admin,
    is_super_admin,
    outranks,
)
from utils import chat_config_cache, messages
from utils.telegram_errors import bot_permission_error_reply
from utils.text import matches_command, normalize_fa, normalize_trigger

# --- Trigger words (all already correct Persian - see utils/text.py) ---
# Plain Persian text only - no "/" commands (see bot.py). A command is
# either an EXACT match to one of these words, or - where explicitly noted
# (بن/کیک/اخراج/سیک + میوت) - the word plus one fixed-format argument
# (an "@username" or, for میوت only, a plain integer). See matches_command()
# in utils/text.py.
BAN_TRIGGERS = {"کیک", "بن", "اخراج", "سیک"}
MUTE_TRIGGERS = {"میوت", "سکوت"}
UNMUTE_TRIGGERS = {"آنمیوت", "رفع سکوت", "رفع میوت"}
UNBAN_PREFIXES = ("رفع بن", "آنبن")
VIP_TRIGGERS = {"تنظیم ویژه"}
UNVIP_TRIGGERS = {"لغو ویژه"}
ADD_ADMIN_TRIGGERS = {"افزودن ادمین گروه", "افزودن ادمین"}
REMOVE_ADMIN_TRIGGERS = {"حذف ادمین گروه", "حذف ادمین"}
LIST_ADMIN_TRIGGERS = {"لیست ادمین های گروه", "لیست ادمین ها"}
ADD_OWNER2_TRIGGERS = {"افزودن مالک دو", "افزودن مالک ۲"}
REMOVE_OWNER2_TRIGGERS = {"حذف مالک دو", "حذف مالک ۲"}
SHOW_OWNER_TRIGGERS = {"مالک این گروه", "مالک گروه"}
CLAIM_OWNER_TRIGGERS = {"ادعای مالکیت"}
SET_OWNER_PREFIX = "تنظیم مالک"
SET_SPAM_LIMIT_PREFIX_FA = "تنظیم تعداد پیام مجاز"
SET_SPAM_MUTE_PREFIX_FA = "تنظیم مدت سکوت اسپم"
SHOW_SPAM_SETTINGS_TRIGGERS = {"تنظیمات اسپم"}
SET_IMAGE_PREFIX = "ثبت تصویر"

WARN_TRIGGERS = {"اخطار"}
CLEAR_WARN_TRIGGERS = {"حذف اخطار", "پاک کردن اخطار"}
LIST_WARN_TRIGGERS = {"لیست اخطار", "لیست اخطارها"}
WARN_LIMIT = 3  # auto-ban after this many active warnings

ADD_FILTER_PREFIX = "افزودن کلمه فیلتر"
REMOVE_FILTER_PREFIX = "حذف کلمه فیلتر"
LIST_FILTER_TRIGGERS = {"لیست کلمات فیلتر"}

SET_WELCOME_PREFIX = "تنظیم خوش آمدگویی"
WELCOME_ON_TRIGGERS = {"روشن کردن خوش آمدگویی"}
WELCOME_OFF_TRIGGERS = {"خاموش کردن خوش آمدگویی"}
SET_GOODBYE_PREFIX = "تنظیم بدرود"
GOODBYE_ON_TRIGGERS = {"روشن کردن بدرود"}
GOODBYE_OFF_TRIGGERS = {"خاموش کردن بدرود"}

# --- New commands ---
PING_TRIGGERS = {"پینگ"}
CONFIGURE_TRIGGERS = {"پیکربندی"}  # adds every real Telegram admin as a bot admin
CLEANUP_ADMINS_TRIGGERS = {"پاک سازی"}  # removes every bot admin in this chat
DELETE_ALL_TRIGGERS = {"حذف کل"}  # wipes every message the bot has logged (needs confirmation)

DEFAULT_MUTE_SECONDS = 24 * 60 * 60  # fallback only - see mute_user for the real default (forever)

def _norm(message: Message) -> str:
    return normalize_trigger(message.text or "").strip()


async def _require_admin(message: Message) -> bool:
    """
    True if the sender may use management commands here. If not, ALWAYS
    explains why instead of staying silent (this used to just `return`
    with no feedback, which looked like the bot was broken/unresponsive).
    """
    if await is_authorized_admin(db, message.chat.id, message.from_user.id):
        return True
    await bot.reply_to(message, messages.get("not_admin"))
    return False


async def _require_role_manager(message: Message, target_role: str = "admin") -> bool:
    return await can_assign_role(db, message.chat.id, message.from_user.id, target_role)


async def _require_global_owner(message: Message) -> bool:
    """Gate for things a hardcoded Global Owner OR a dynamically-promoted
    ادمین کل can do (they're meant to be identical) - e.g. «ثبت تصویر».
    NOT used for adding/removing ادمین کل itself - see _require_true_global_owner."""
    if is_super_admin(message.from_user.id):
        return True
    await bot.reply_to(message, messages.get("not_super_admin"))
    return False


# ---------------------------------------------------------------- #
# TARGET RESOLUTION
# ---------------------------------------------------------------- #
# Admins commonly do one of three things when they want to act on someone:
#   1. Type the command with @username directly: "بن @username"
#   2. Paste the person's @username as its OWN message, then reply to that
#      message with the command (see the screenshot: "@NastaranChan" sent
#      as a message, then "بن" as a reply to it). The natural reading is
#      "ban @NastaranChan", not "ban whoever pasted this".
#   3. Just reply to a normal message the person actually sent - the
#      classic case, where the target is that message's real sender.
# _resolve_target() tries these in order.

@dataclass
class _TargetRef:
    id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @property
    def full_name(self) -> str:
        if self.first_name:
            return self.first_name + (f" {self.last_name}" if self.last_name else "")
        return f"@{self.username}" if self.username else str(self.id)


def _is_bare_username(text: str) -> Optional[str]:
    """Returns the username if `text` is EXACTLY one @username token and nothing else."""
    tokens = text.strip().split()
    if len(tokens) == 1 and tokens[0].startswith("@") and len(tokens[0]) > 1:
        return tokens[0][1:]
    return None


async def _resolve_target(message: Message) -> Optional[_TargetRef]:
    # 1) @username written directly in the command itself, e.g. "بن @username"
    match = re.search(r"@(\w+)", normalize_fa(message.text or ""))
    if match:
        username = match.group(1)
        user_id = await db.get_user_id_by_username(username)
        if user_id:
            return _TargetRef(id=user_id, username=username)

    reply = message.reply_to_message
    if not reply:
        return None

    # 2) Replied-to message is a bare @username with nothing else
    reply_text = normalize_fa(reply.text or reply.caption or "")
    bare_username = _is_bare_username(reply_text)
    if bare_username:
        user_id = await db.get_user_id_by_username(bare_username)
        if user_id:
            return _TargetRef(id=user_id, username=bare_username)
        # Unknown username - don't silently fall through to "whoever pasted
        # it", that's the exact bug we're fixing. Tell the admin why.
        return None

    # 3) Normal case: the actual sender of the replied-to message
    if reply.from_user:
        u = reply.from_user
        return _TargetRef(id=u.id, username=u.username, first_name=u.first_name, last_name=u.last_name)

    return None


async def _refuse_if_protected(message: Message, target: _TargetRef) -> bool:
    """
    Blocks banning/muting/warning someone who OUTRANKS or EQUALS the actor
    in the role hierarchy (owner > owner2 > admin > vip > normal - see
    utils/permissions.py), with a clear bot response, instead of either a
    raw Telegram API error or letting a lower-ranked admin act on a
    higher-ranked one. Returns True if the action was blocked.
    """
    if is_global_owner(target.id):
        await bot.reply_to(message, messages.get("cant_touch_bot_owner"))
        return True

    if not await outranks(db, message.chat.id, message.from_user.id, target.id):
        target_role = await db.get_user_role(message.chat.id, target.id)
        if target_role in MANAGEMENT_ROLES:
            label = ROLE_LABELS_FA.get(target_role, target_role)
            await bot.reply_to(message, messages.get("not_outranked", role_label=label))
            return True
    return False


# ---------------------------------------------------------------- #
# BAN (kick + ban combined - see module docstring above)
# ---------------------------------------------------------------- #

BAN_ANNOUNCEMENT_TEMPLATES = [
    "🚔 {name} امروز با اسکورت کامل از {group} تشریف بردن، دیگه برنمی‌گردن (مگر با «رفع بن»)!",
    "📦 {name} بسته‌بندی و از {group} پست شدن. مقصد: هیچ‌کجا 😄",
    "🎬 و... کات! نقش {name} در سریال {group} همینجا به پایان رسید.",
    "🚪 در به روی {name} در {group} برای همیشه بسته شد (فعلاً).",
    "🛸 {name} توسط سفینهٔ بن از {group} ربوده شدند. شاهدی نداریم.",
]


def _pick_ban_announcement(name: str, group: str) -> str:
    import random

    return random.choice(BAN_ANNOUNCEMENT_TEMPLATES).format(name=name, group=group)


def _ban_trigger_matches(text: str) -> bool:
    """"کیک"/"بن"/"اخراج"/"سیک" alone, or exactly "<trigger> @username" -
    nothing else (see utils/text.py's matches_command). This is why
    "بن شدم" no longer bans whoever the message happens to be a reply to,
    while "بن @username" keeps working as a fixed, deliberate format."""
    return matches_command(normalize_trigger(text or ""), BAN_TRIGGERS, allow_mention=True)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: _ban_trigger_matches(m.text or ""))
async def ban_user(message: Message):
    # Target is resolved via @username in the command itself, via reply, or
    # by replying to a message that is itself a bare "@username" - see
    # _resolve_target().
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, messages.get("ban.need_target"))
        return
    if await _refuse_if_protected(message, target):
        return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        funny_line = _pick_ban_announcement(target.full_name, message.chat.title or "این گروه")
        await bot.reply_to(message, messages.get("ban.success", name=target.full_name, funny_line=funny_line))
    except Exception as e:
        await bot.reply_to(message, bot_permission_error_reply(e))


# ---------------------------------------------------------------- #
# UNBAN — reply to any old message from the user, OR pass @username
# ---------------------------------------------------------------- #

def _unban_trigger_matches(text: str) -> bool:
    """"رفع بن"/"آنبن" alone, or exactly "<trigger> @username" - nothing else."""
    t = normalize_trigger(text or "").strip()
    if not t:
        return False
    if t in UNBAN_PREFIXES:
        return True
    for prefix in UNBAN_PREFIXES:
        if t.startswith(prefix + " "):
            rest = t[len(prefix):].strip()
            if re.fullmatch(r"@\w+", rest):
                return True
    return False


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: _unban_trigger_matches(m.text or ""))
async def unban_user(message: Message):
    if not await _require_admin(message):
        return

    target_id = None
    target_label = None

    match = re.search(r"@(\w+)", normalize_fa(message.text or ""))
    if match:
        username = match.group(1)
        target_id = await db.get_user_id_by_username(username)
        target_label = f"@{username}"
    elif message.reply_to_message and message.reply_to_message.from_user:
        reply_user = message.reply_to_message.from_user
        target_id = reply_user.id
        target_label = reply_user.full_name

    if not target_id:
        await bot.reply_to(message, messages.get("unban.need_target"))
        return

    try:
        member = await bot.get_chat_member(message.chat.id, target_id)
        if member.status != "kicked":
            await bot.reply_to(message, messages.get("unban.already_unbanned", name=target_label))
            return
    except Exception:
        pass  # couldn't check status - fall through and just try the unban anyway

    try:
        await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
        await bot.reply_to(message, messages.get("unban.success", name=target_label))
    except Exception as e:
        await bot.reply_to(message, bot_permission_error_reply(e))


# ---------------------------------------------------------------- #
# MUTE — "میوت"/"سکوت" alone = forever (until manually unmuted),
#         "میوت 10" = 10 minutes
# ---------------------------------------------------------------- #

def _mute_trigger_matches(text: str) -> bool:
    """"میوت"/"سکوت" alone, or exactly "میوت <digits>" (minutes) - nothing
    else. Rejects things like "میوت شدم" (ordinary Persian sentence
    fragment) which used to falsely match just because it started with
    "میوت "."""
    t = normalize_trigger(text or "").strip()
    if not t:
        return False
    if t in MUTE_TRIGGERS:
        return True
    parts = t.split()
    return len(parts) == 2 and parts[0] in MUTE_TRIGGERS and parts[1].isdigit()


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: _mute_trigger_matches(m.text or ""))
async def mute_user(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, messages.get("mute.need_target"))
        return
    if await _refuse_if_protected(message, target):
        return

    parts = _norm(message).split()
    minutes = None
    if len(parts) > 1 and parts[1].isdigit():
        minutes = int(parts[1])

    try:
        if minutes:
            until = int(time.time() + minutes * 60)
            await bot.restrict_chat_member(
                message.chat.id, target.id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until,
            )
            await bot.reply_to(message, messages.get("mute.timed", name=target.full_name, minutes=minutes))
        else:
            # No until_date -> Telegram treats this as "forever" (until manually lifted).
            await bot.restrict_chat_member(
                message.chat.id, target.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await bot.reply_to(message, messages.get("mute.forever", name=target.full_name))
    except Exception as e:
        await bot.reply_to(message, bot_permission_error_reply(e))


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in UNMUTE_TRIGGERS)
async def unmute_user(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, messages.get("unmute.need_target"))
        return

    try:
        member = await bot.get_chat_member(message.chat.id, target.id)
        already_can_speak = member.status != "restricted" or getattr(member, "can_send_messages", True)
        if member.status != "kicked" and already_can_speak:
            await bot.reply_to(message, messages.get("unmute.already_speaking", name=target.full_name))
            return
    except Exception:
        pass  # couldn't check status - fall through and just try the unmute anyway

    try:
        # Restore this group's own default member permissions, rather than
        # guessing a fixed set - this is the correct way to "undo" a mute.
        chat = await bot.get_chat(message.chat.id)
        permissions = chat.permissions or ChatPermissions(can_send_messages=True)
        await bot.restrict_chat_member(message.chat.id, target.id, permissions=permissions)
        await bot.reply_to(message, messages.get("unmute.success", name=target.full_name))
    except Exception as e:
        await bot.reply_to(message, bot_permission_error_reply(e))


# ---------------------------------------------------------------- #
# VIP — per-chat, set/unset
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in VIP_TRIGGERS)
async def set_vip(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, messages.get("vip.need_target"))
        return
    await db.set_user_role(
        message.chat.id, target.id, "vip",
        username=target.username, first_name=target.first_name, last_name=target.last_name,
    )
    await bot.reply_to(message, messages.get("vip.set", name=target.full_name))


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in UNVIP_TRIGGERS)
async def unset_vip(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, messages.get("vip.need_target"))
        return
    current_role = await db.get_user_role(message.chat.id, target.id)
    if current_role != "vip":
        await bot.reply_to(message, messages.get("vip.not_vip", name=target.full_name))
        return
    await db.set_user_role(message.chat.id, target.id, "normal")
    await bot.reply_to(message, messages.get("vip.unset", name=target.full_name))


# ---------------------------------------------------------------- #
# GROUP OWNERSHIP — view / claim (bootstrap) / force-transfer
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in SHOW_OWNER_TRIGGERS)
async def show_owner(message: Message):
    owner_id = await db.get_chat_owner(message.chat.id)
    if not owner_id:
        await bot.reply_to(
            message,
            "👑 برای این گروه هنوز مالکی ثبت نشده (مثلاً چون ربات قبل از این قابلیت اضافه شده).\n"
            "اگر شما ادمین واقعی تلگرام در این گروه هستید، می‌توانید بنویسید: «ادعای مالکیت»",
        )
        return
    name = await db.get_user_display_name(message.chat.id, owner_id)
    await bot.reply_to(message, f"👑 مالک این گروه: {name}")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in CLAIM_OWNER_TRIGGERS)
async def claim_owner(message: Message):
    existing = await db.get_chat_owner(message.chat.id)
    if existing:
        await bot.reply_to(message, "این گروه از قبل مالک ثبت‌شده دارد. برای دیدن آن بنویسید: «مالک این گروه»")
        return
    if not await is_group_admin(bot, message.chat.id, message.from_user.id):
        await bot.reply_to(message, "⚠️ فقط ادمین‌های واقعی تلگرام در این گروه می‌توانند مالکیت را ادعا کنند.")
        return
    u = message.from_user
    await db.set_user_role(message.chat.id, u.id, "owner", username=u.username, first_name=u.first_name, last_name=u.last_name)
    await bot.reply_to(message, f"👑 {u.full_name} به‌عنوان مالک این گروه ثبت شد.")


async def _can_use_set_owner(message: Message) -> bool:
    """Global Owners/Admins can do this in ANY group. A group's own مالک
    اصلی can ALSO use it, but only to transfer ownership within THEIR OWN
    group (e.g. handing the group to someone else) - not anyone else's."""
    if is_super_admin(message.from_user.id):
        return True
    role = await db.get_user_role(message.chat.id, message.from_user.id)
    return role == "owner"


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_trigger(m.text or "").strip().startswith(SET_OWNER_PREFIX),
)
async def force_set_owner(message: Message):
    if not await _can_use_set_owner(message):
        await bot.reply_to(
            message,
            "⚠️ این دستور فقط برای مالک ربات، ادمین کل، یا مالک اصلی همین گروه (برای واگذاری مالکیت) قابل استفاده است.",
        )
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربری که می‌خواهید مالک گروه شود ریپلای کنید.")
        return

    # BUG FIX: this used to only set the NEW owner's role, never demoting
    # the previous one - leaving two 'owner' rows for the same chat, which
    # made get_chat_owner() (no ORDER BY) return an unpredictable one.
    previous_owner_id = await db.get_chat_owner(message.chat.id)
    if previous_owner_id and previous_owner_id != target.id:
        await db.set_user_role(message.chat.id, previous_owner_id, "normal")

    await db.set_user_role(
        message.chat.id, target.id, "owner",
        username=target.username, first_name=target.first_name, last_name=target.last_name,
    )
    await bot.reply_to(message, f"✅ {target.full_name} اکنون مالک اصلی این گروه است.")


# ---------------------------------------------------------------- #
# GLOBAL ADMINS (ادمین کل) — bot-wide, not scoped to a chat. Identical
# access to a hardcoded Global Owner, but removable (unlike OWNER_USER_IDS
# in .env, which needs a redeploy to change). Usable in any group, reply
# to the target's message - the effect applies EVERYWHERE, not just here.
# See utils/global_admins.py for the in-memory cache this reads/writes.
# ---------------------------------------------------------------- #

ADD_GLOBAL_ADMIN_TRIGGERS = {"افزودن ادمین کل"}
REMOVE_GLOBAL_ADMIN_TRIGGERS = {"حذف ادمین کل"}
LIST_GLOBAL_ADMIN_TRIGGERS = {"لیست ادمین های کل"}

GLOBAL_ADMIN_CAPABILITIES_TEXT = (
    "🔓 شما اکنون <b>ادمین کل</b> ربات هستید - دسترسی کامل و یکسان با مالک ربات، در «همهٔ» "
    "گروه‌هایی که این ربات در آن‌هاست، نه فقط این گروه:\n"
    "• همهٔ قابلیت‌های مدیریتی در هر گروه (بن، سکوت، اخطار، پنل، تنظیمات و ...)\n"
    "• بالاتر از مالک اصلی/مالک ۲/ادمین هر گروه\n\n"
    "تنها تفاوت با مالک‌های ربات که در تنظیمات سرور مشخص شده‌اند: این نقش با دستور «حذف ادمین کل» "
    "توسط مالک ربات یا همان کسی که شما را ارتقا داده قابل پس‌گرفتن است."
)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in ADD_GLOBAL_ADMIN_TRIGGERS)
async def add_global_admin(message: Message):
    # Deliberately STRICTER than _require_global_owner: only a hardcoded
    # Global Owner may CREATE a new ادمین کل - an ادمین کل cannot promote
    # more of themselves, to keep this powerful role's growth controlled.
    if not is_global_owner(message.from_user.id):
        await bot.reply_to(message, "⛔️ فقط مالک ربات می‌تواند ادمین کل جدید تعیین کند.")
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربری که می‌خواهید ادمین کل شود ریپلای کنید.")
        return
    await global_admins.add(db, target.id, promoted_by=message.from_user.id)
    mention = f'<a href="tg://user?id={target.id}">{target.full_name}</a>'
    await bot.reply_to(message, f"✅ {target.full_name} اکنون ادمین کل ربات است.\n\n{mention} " + GLOBAL_ADMIN_CAPABILITIES_TEXT)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in REMOVE_GLOBAL_ADMIN_TRIGGERS)
async def remove_global_admin(message: Message):
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربر مورد نظر ریپلای کنید.")
        return
    if not global_admins.is_global_admin(target.id):
        await bot.reply_to(message, f"{target.full_name} ادمین کل نیست.")
        return
    # Removable by a hardcoded Global Owner, OR by whoever specifically promoted this person.
    promoter_id = global_admins.get_promoter(target.id)
    if not (is_global_owner(message.from_user.id) or message.from_user.id == promoter_id):
        await bot.reply_to(
            message,
            "⛔️ فقط مالک ربات یا کسی که این فرد را ادمین کل کرده می‌تواند این دسترسی را بگیرد.",
        )
        return
    await global_admins.remove(db, target.id)
    await bot.reply_to(message, f"✅ دسترسی ادمین کل از {target.full_name} گرفته شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in LIST_GLOBAL_ADMIN_TRIGGERS)
async def list_global_admins(message: Message):
    if not is_global_owner(message.from_user.id):
        await bot.reply_to(message, "⛔️ این دستور فقط مخصوص مالک ربات است.")
        return
    ids = global_admins.list_ids()
    if not ids:
        await bot.reply_to(message, "هیچ ادمین کلی تعیین نشده.")
        return
    lines = ["🔓 <b>ادمین‌های کل ربات:</b>"]
    for uid in ids:
        name = await db.get_user_display_name(message.chat.id, uid)
        promoter = global_admins.get_promoter(uid)
        lines.append(f"• {name} (<code>{uid}</code>) - ارتقا توسط <code>{promoter}</code>")
    await bot.reply_to(message, "\n".join(lines))


# ---------------------------------------------------------------- #
# GROUP ADMINS & مالک ۲ — appointed by the group's owner (مالک ۲ also
# appoints/removes admins), see utils/permissions.py for the full hierarchy
# ---------------------------------------------------------------- #

ADMIN_CAPABILITIES_TEXT = (
    "🔓 قابلیت‌هایی که الان در این گروه داری:\n"
    "• بن/کیک/اخراج و رفع بن (بن، کیک، اخراج، رفع بن)\n"
    "• سکوت و رفع سکوت (میوت، سکوت، رفع سکوت)\n"
    "• تنظیم/لغو عضو ویژه (تنظیم ویژه، لغو ویژه)\n"
    "• اخطار دادن و مدیریت اخطارها (اخطار، حذف اخطار، لیست اخطار)\n"
    "• کلمات فیلتر (افزودن/حذف/لیست کلمه فیلتر)\n"
    "• دیدن پروفایل و آیدی اعضا (پروفایل)\n"
    "• تنظیمات ضد اسپم، خوش‌آمدگویی/بدرود و کپچای عضویت\n"
    "• دسترسی به پنل تنظیمات گروه («پنل»)\n\n"
    "توجه: نمی‌تونی ادمین یا مالک ۲ دیگه‌ای رو عزل کنی - فقط اعضای ویژه.\n"
    "برای دیدن لیست کامل دستورات بنویس: «راهنما»"
)

OWNER2_CAPABILITIES_TEXT = (
    "🔓 قابلیت‌هایی که الان در این گروه داری (علاوه بر همهٔ قابلیت‌های ادمین):\n"
    "• همهٔ کارهای مدیریتی ادمین‌ها (بن، سکوت، اخطار، ویژه، فیلتر کلمات، پنل و ...)\n"
    "• افزودن و عزل ادمین گروه («افزودن ادمین گروه» / «حذف ادمین گروه»)\n\n"
    "توجه: نمی‌تونی یک مالک ۲ دیگه یا مالک اصلی رو عزل کنی - این کار فقط با مالک اصلی گروه است.\n"
    "برای دیدن لیست کامل دستورات بنویس: «راهنما»"
)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in ADD_ADMIN_TRIGGERS)
async def add_admin(message: Message):
    if not await _require_role_manager(message, "admin"):
        await bot.reply_to(message, "⚠️ فقط مالک اصلی یا مالک ۲ این گروه می‌تواند ادمین گروه اضافه کند.")
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربری که می‌خواهید ادمین این گروه شود ریپلای کنید.")
        return
    await db.set_user_role(
        message.chat.id, target.id, "admin",
        username=target.username, first_name=target.first_name, last_name=target.last_name,
    )
    mention = f'<a href="tg://user?id={target.id}">{target.full_name}</a>'
    await bot.reply_to(
        message,
        f"✅ کاربر {target.full_name} اکنون ادمین این گروه است (فقط در همین گروه).\n\n"
        f"{mention} " + ADMIN_CAPABILITIES_TEXT,
    )


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in REMOVE_ADMIN_TRIGGERS)
async def remove_admin(message: Message):
    if not await _require_role_manager(message, "admin"):
        await bot.reply_to(message, "⚠️ فقط مالک اصلی یا مالک ۲ این گروه می‌تواند دسترسی ادمین را بگیرد.")
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربر مورد نظر ریپلای کنید.")
        return
    current_role = await db.get_user_role(message.chat.id, target.id)
    if current_role != "admin":
        await bot.reply_to(message, f"{target.full_name} ادمین این گروه نیست.")
        return
    await db.set_user_role(message.chat.id, target.id, "normal")
    await bot.reply_to(message, f"✅ دسترسی ادمین این گروه از {target.full_name} گرفته شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in ADD_OWNER2_TRIGGERS)
async def add_owner2(message: Message):
    if not await _require_role_manager(message, "owner2"):
        await bot.reply_to(message, "⚠️ فقط مالک اصلی این گروه می‌تواند مالک ۲ تعیین کند.")
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربری که می‌خواهید مالک ۲ این گروه شود ریپلای کنید.")
        return
    await db.set_user_role(
        message.chat.id, target.id, "owner2",
        username=target.username, first_name=target.first_name, last_name=target.last_name,
    )
    mention = f'<a href="tg://user?id={target.id}">{target.full_name}</a>'
    await bot.reply_to(
        message,
        f"✅ کاربر {target.full_name} اکنون مالک ۲ این گروه است (فقط در همین گروه).\n\n"
        f"{mention} " + OWNER2_CAPABILITIES_TEXT,
    )


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in REMOVE_OWNER2_TRIGGERS)
async def remove_owner2(message: Message):
    if not await _require_role_manager(message, "owner2"):
        await bot.reply_to(message, "⚠️ فقط مالک اصلی این گروه می‌تواند دسترسی مالک ۲ را بگیرد.")
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربر مورد نظر ریپلای کنید.")
        return
    current_role = await db.get_user_role(message.chat.id, target.id)
    if current_role != "owner2":
        await bot.reply_to(message, f"{target.full_name} مالک ۲ این گروه نیست.")
        return
    await db.set_user_role(message.chat.id, target.id, "normal")
    await bot.reply_to(message, f"✅ دسترسی مالک ۲ این گروه از {target.full_name} گرفته شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in LIST_ADMIN_TRIGGERS)
async def list_admins(message: Message):
    if not await _require_admin(message):
        return
    owner2_ids = await db.list_users_by_role(message.chat.id, "owner2")
    admin_ids = await db.list_users_by_role(message.chat.id, "admin")
    owner_id = await db.get_chat_owner(message.chat.id)

    lines = []
    if owner_id:
        owner_name = await db.get_user_display_name(message.chat.id, owner_id)
        lines.append(f"👑 مالک اصلی: {owner_name}")
    if owner2_ids:
        lines.append("\n👑 <b>مالک‌های ۲ این گروه:</b>")
        for user_id in owner2_ids:
            name = await db.get_user_display_name(message.chat.id, user_id)
            lines.append(f"• {name}")
    if admin_ids:
        lines.append("\n👮‍♂️ <b>ادمین‌های این گروه:</b>")
        for user_id in admin_ids:
            name = await db.get_user_display_name(message.chat.id, user_id)
            lines.append(f"• {name}")
    else:
        lines.append("\nهیچ ادمینی (جدا از مالک) برای این گروه تعیین نشده.")

    await bot.reply_to(message, "\n".join(lines))


# ---------------------------------------------------------------- #
# SPAM PROTECTION — simplified to ONE number per setting (per your
# feedback that the old 3-argument command was too complex for a normal
# admin). Time window is a fixed 3 seconds (matching how similar bots do
# it) and is no longer something admins need to think about.
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_trigger(m.text or "").strip().startswith(SET_SPAM_LIMIT_PREFIX_FA),
)
async def set_spam_limit(message: Message):
    if not await _require_admin(message):
        return
    text = _norm(message)
    arg = text[len(SET_SPAM_LIMIT_PREFIX_FA):].strip()
    if not arg.isdigit():
        current = await db.get_chat_settings(message.chat.id)
        await bot.reply_to(
            message,
            "⚠️ فرمت درست: <code>تنظیم تعداد پیام مجاز [عدد]</code>\n"
            "مثال: <code>تنظیم تعداد پیام مجاز 6</code>\n"
            "(یعنی بیشتر از این تعداد پیام در ۳ ثانیه = اسپم)\n\n"
            f"مقدار فعلی: {current['spam_message_limit']}",
        )
        return
    limit = int(arg)
    await db.set_spam_limit(message.chat.id, limit)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, f"✅ سقف پیام مجاز این گروه روی {limit} پیام در ۳ ثانیه تنظیم شد.")


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_trigger(m.text or "").strip().startswith(SET_SPAM_MUTE_PREFIX_FA),
)
async def set_spam_mute(message: Message):
    if not await _require_admin(message):
        return
    text = _norm(message)
    arg = text[len(SET_SPAM_MUTE_PREFIX_FA):].strip()
    if not arg.isdigit():
        current = await db.get_chat_settings(message.chat.id)
        await bot.reply_to(
            message,
            "⚠️ فرمت درست: <code>تنظیم مدت سکوت اسپم [عدد به دقیقه]</code>\n"
            "مثال: <code>تنظیم مدت سکوت اسپم 30</code>\n\n"
            f"مقدار فعلی: {current['spam_mute_minutes']} دقیقه",
        )
        return
    minutes = int(arg)
    await db.set_spam_mute_minutes(message.chat.id, minutes)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, f"✅ مدت سکوت خودکار اسپم‌کننده‌ها روی {minutes} دقیقه تنظیم شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in SHOW_SPAM_SETTINGS_TRIGGERS)
async def show_spam_settings(message: Message):
    current = await db.get_chat_settings(message.chat.id)
    await bot.reply_to(
        message,
        "⚙️ <b>تنظیمات ضد اسپم این گروه:</b>\n"
        f"حداکثر پیام مجاز: {current['spam_message_limit']} در ۳ ثانیه\n"
        f"مدت سکوت خودکار: {current['spam_mute_minutes']} دقیقه\n\n"
        "برای تغییر:\n"
        "• <code>تنظیم تعداد پیام مجاز [عدد]</code>\n"
        "• <code>تنظیم مدت سکوت اسپم [عدد به دقیقه]</code>",
    )


# ---------------------------------------------------------------- #
# IMAGE REGISTRATION — reply to a photo with "ثبت تصویر [key]"
# ---------------------------------------------------------------- #
# Global-Owner-only (these are bot-wide assets, e.g. the /start or /help
# banner, not per-group). Captures the photo's file_id and stores just
# that tiny string - Telegram keeps hosting the actual image forever, we
# never touch the file bytes. This is how you add new images later: send
# the photo to any chat with the bot, reply to it with this command, done.

@bot.message_handler(func=lambda m: normalize_trigger(m.text or "").strip().startswith(SET_IMAGE_PREFIX))
async def set_image(message: Message):
    if not await _require_global_owner(message):
        return
    parts = _norm(message).split()
    if len(parts) < 3 or not message.reply_to_message or not message.reply_to_message.photo:
        await bot.reply_to(
            message,
            "⚠️ روی یک عکس ریپلای کنید و بنویسید:\n<code>ثبت تصویر [کلید]</code>\n"
            "مثال: <code>ثبت تصویر start_banner</code>",
        )
        return
    key = parts[2]
    file_id = message.reply_to_message.photo[-1].file_id
    await db.set_asset(key, file_id, set_by=message.from_user.id)
    await bot.reply_to(message, f"✅ تصویر با کلید <code>{key}</code> ذخیره شد.")


# ---------------------------------------------------------------- #
# WARNINGS (اخطار) — reply to warn; WARN_LIMIT active warnings = auto-ban
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_trigger(m.text or "").strip() in WARN_TRIGGERS,
)
async def warn_user(message: Message):
    # Exact match only - "اخطار" must be the ENTIRE message (see the
    # module-level note on this file). An inline free-text reason used to
    # be supported ("اخطار فلان دلیل") but that meant any admin casually
    # typing a sentence starting with "اخطار" while replying to someone
    # would silently warn that person - removed on purpose.
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ برای اخطار دادن به کاربر، روی پیام او ریپلای کنید.")
        return
    if await _refuse_if_protected(message, target):
        return

    count = await db.add_warning(message.chat.id, target.id, message.from_user.id, None)
    reason_line = ""

    if count >= WARN_LIMIT:
        try:
            await bot.ban_chat_member(message.chat.id, target.id)
            await db.clear_warnings(message.chat.id, target.id)
            await bot.reply_to(
                message,
                messages.get("warn.auto_ban", name=target.full_name, count=count, limit=WARN_LIMIT, reason_line=reason_line),
            )
        except Exception as e:
            await bot.reply_to(message, bot_permission_error_reply(e))
    else:
        await bot.reply_to(
            message,
            messages.get("warn.given", name=target.full_name, count=count, limit=WARN_LIMIT, reason_line=reason_line),
        )


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in CLEAR_WARN_TRIGGERS)
async def clear_warn(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربر مورد نظر ریپلای کنید.")
        return
    await db.clear_warnings(message.chat.id, target.id)
    await bot.reply_to(message, messages.get("warn.cleared", name=target.full_name))


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in LIST_WARN_TRIGGERS)
async def list_warn(message: Message):
    if not await _require_admin(message):
        return
    warned = await db.list_warned_users(message.chat.id)
    if not warned:
        await bot.reply_to(message, "هیچ کاربری در این گروه اخطار فعالی ندارد.")
        return
    lines = ["⚠️ <b>لیست اخطارهای این گروه:</b>"]
    for user_id, count in warned:
        name = await db.get_user_display_name(message.chat.id, user_id)
        lines.append(f"• {name}: {count} از {WARN_LIMIT}")
    await bot.reply_to(message, "\n".join(lines))


# ---------------------------------------------------------------- #
# FILTERED WORDS (فیلتر کلمات) — auto-delete for Normal members,
# enforced in handlers/antispam.py
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip().startswith(ADD_FILTER_PREFIX))
async def add_filter_word(message: Message):
    if not await _require_admin(message):
        return
    word = _norm(message)[len(ADD_FILTER_PREFIX):].strip()
    if not word:
        await bot.reply_to(message, "⚠️ فرمت درست: <code>افزودن کلمه فیلتر [کلمه]</code>")
        return
    await db.add_filtered_word(message.chat.id, word, added_by=message.from_user.id)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, f"✅ کلمهٔ «{word}» به فیلتر این گروه اضافه شد و پیام‌های حاوی آن حذف می‌شوند.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip().startswith(REMOVE_FILTER_PREFIX))
async def remove_filter_word(message: Message):
    if not await _require_admin(message):
        return
    word = _norm(message)[len(REMOVE_FILTER_PREFIX):].strip()
    if not word:
        await bot.reply_to(message, "⚠️ فرمت درست: <code>حذف کلمه فیلتر [کلمه]</code>")
        return
    removed = await db.remove_filtered_word(message.chat.id, word)
    chat_config_cache.invalidate(message.chat.id)
    if removed:
        await bot.reply_to(message, f"✅ کلمهٔ «{word}» از فیلتر این گروه حذف شد.")
    else:
        await bot.reply_to(message, f"«{word}» در لیست کلمات فیلتر این گروه نبود.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in LIST_FILTER_TRIGGERS)
async def list_filter_words(message: Message):
    if not await _require_admin(message):
        return
    words = await db.list_filtered_words(message.chat.id)
    if not words:
        await bot.reply_to(message, "هیچ کلمه‌ای در فیلتر این گروه ثبت نشده.")
        return
    await bot.reply_to(message, "🔒 <b>کلمات فیلتر این گروه:</b>\n" + "\n".join(f"• {w}" for w in words))


# ---------------------------------------------------------------- #
# WELCOME / GOODBYE — customizable, per-chat, default ON, optional media
# ---------------------------------------------------------------- #
# Placeholders use Persian words ({نام}, {منشن}, {گروه}) so a Persian-
# speaking admin can read their own template and immediately understand
# what each one means - they're only ever shown to the admin writing the
# template, never sent literally to a real member (see handlers/tracking.py
# for the substitution). Reply to a photo/video/voice/audio/gif/document
# with the same "تنظیم خوش آمدگویی"/"تنظیم بدرود" command to make THAT the
# welcome/goodbye message (sent as that media type, with the text as its
# caption) instead of a plain text message.

WELCOME_TEXT_HELP = (
    "⚠️ فرمت درست: <code>تنظیم خوش آمدگویی [متن]</code>\n"
    "می‌توانید از جای‌گذاری‌های زیر در متن استفاده کنید:\n"
    "• <code>{نام}</code> → نام عضو جدید\n"
    "• <code>{منشن}</code> → منشن قابل کلیک عضو جدید\n"
    "• <code>{گروه}</code> → نام گروه\n\n"
    "برای اینکه پیام خوش‌آمدگویی شامل عکس/ویدیو/ویس/فایل هم باشد، روی آن رسانه "
    "ریپلای کنید و همین دستور را با متن دلخواه (به‌عنوان کپشن) بفرستید."
)
GOODBYE_TEXT_HELP = (
    "⚠️ فرمت درست: <code>تنظیم بدرود [متن]</code>\n"
    "می‌توانید از جای‌گذاری‌های زیر در متن استفاده کنید:\n"
    "• <code>{نام}</code> → نام عضوی که رفت\n"
    "• <code>{منشن}</code> → منشن قابل کلیک او\n"
    "• <code>{گروه}</code> → نام گروه\n\n"
    "برای اینکه پیام بدرود شامل عکس/ویدیو/ویس/فایل هم باشد، روی آن رسانه "
    "ریپلای کنید و همین دستور را با متن دلخواه (به‌عنوان کپشن) بفرستید."
)

_MEDIA_FILE_ID_GETTERS = {
    "photo": lambda m: m.photo[-1].file_id,
    "video": lambda m: m.video.file_id,
    "voice": lambda m: m.voice.file_id,
    "audio": lambda m: m.audio.file_id,
    "animation": lambda m: m.animation.file_id,
    "document": lambda m: m.document.file_id,
    "video_note": lambda m: m.video_note.file_id,
}


def _extract_media(reply_message):
    """Returns (file_id, content_type) if `message` replied to a supported
    media message, or (None, None) otherwise."""
    if not reply_message:
        return None, None
    getter = _MEDIA_FILE_ID_GETTERS.get(reply_message.content_type)
    if not getter:
        return None, None
    try:
        return getter(reply_message), reply_message.content_type
    except Exception:
        return None, None


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip().startswith(SET_WELCOME_PREFIX))
async def set_welcome_text(message: Message):
    if not await _require_admin(message):
        return
    text = _norm(message)[len(SET_WELCOME_PREFIX):].strip()
    media_file_id, media_type = _extract_media(message.reply_to_message)
    if not text and not media_file_id:
        await bot.reply_to(message, WELCOME_TEXT_HELP)
        return
    await db.set_welcome_settings(
        message.chat.id, text=text or None, media_file_id=media_file_id, media_type=media_type,
    )
    chat_config_cache.invalidate(message.chat.id)
    confirmation = "✅ متن خوش‌آمدگویی این گروه به‌روزرسانی شد."
    if media_file_id:
        confirmation += " (همراه با رسانه‌ای که ریپلای کردید)"
    await bot.reply_to(message, confirmation)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in {"حذف رسانه خوش آمدگویی"})
async def clear_welcome_media(message: Message):
    if not await _require_admin(message):
        return
    await db.set_welcome_settings(message.chat.id, clear_media=True)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, "✅ رسانهٔ خوش‌آمدگویی حذف شد؛ از این پس فقط متن ارسال می‌شود.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in WELCOME_ON_TRIGGERS)
async def welcome_on(message: Message):
    if not await _require_admin(message):
        return
    await db.set_welcome_settings(message.chat.id, enabled=True)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, "✅ خوش‌آمدگویی برای اعضای جدید این گروه فعال شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in WELCOME_OFF_TRIGGERS)
async def welcome_off(message: Message):
    if not await _require_admin(message):
        return
    await db.set_welcome_settings(message.chat.id, enabled=False)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, "✅ خوش‌آمدگویی برای اعضای جدید این گروه غیرفعال شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip().startswith(SET_GOODBYE_PREFIX))
async def set_goodbye_text(message: Message):
    if not await _require_admin(message):
        return
    text = _norm(message)[len(SET_GOODBYE_PREFIX):].strip()
    media_file_id, media_type = _extract_media(message.reply_to_message)
    if not text and not media_file_id:
        await bot.reply_to(message, GOODBYE_TEXT_HELP)
        return
    await db.set_goodbye_settings(
        message.chat.id, text=text or None, media_file_id=media_file_id, media_type=media_type,
    )
    chat_config_cache.invalidate(message.chat.id)
    confirmation = "✅ متن بدرود این گروه به‌روزرسانی شد."
    if media_file_id:
        confirmation += " (همراه با رسانه‌ای که ریپلای کردید)"
    await bot.reply_to(message, confirmation)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in {"حذف رسانه بدرود"})
async def clear_goodbye_media(message: Message):
    if not await _require_admin(message):
        return
    await db.set_goodbye_settings(message.chat.id, clear_media=True)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, "✅ رسانهٔ بدرود حذف شد؛ از این پس فقط متن ارسال می‌شود.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in GOODBYE_ON_TRIGGERS)
async def goodbye_on(message: Message):
    if not await _require_admin(message):
        return
    await db.set_goodbye_settings(message.chat.id, enabled=True)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, "✅ بدرود برای اعضایی که گروه را ترک می‌کنند فعال شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in GOODBYE_OFF_TRIGGERS)
async def goodbye_off(message: Message):
    if not await _require_admin(message):
        return
    await db.set_goodbye_settings(message.chat.id, enabled=False)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, "✅ بدرود برای اعضایی که گروه را ترک می‌کنند غیرفعال شد.")


# ---------------------------------------------------------------- #
# JOIN-REQUEST CAPTCHA — OFF by default (see handlers/captcha.py)
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in {"روشن کردن کپچا"})
async def captcha_on(message: Message):
    if not await _require_admin(message):
        return
    await db.set_join_captcha_enabled(message.chat.id, True)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(
        message,
        "✅ کپچای عضویت فعال شد. توجه: این ویژگی فقط برای گروه‌هایی که «تایید درخواست عضویت» "
        "تلگرام را فعال کرده‌اند اثر دارد.",
    )


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in {"خاموش کردن کپچا"})
async def captcha_off(message: Message):
    if not await _require_admin(message):
        return
    await db.set_join_captcha_enabled(message.chat.id, False)
    chat_config_cache.invalidate(message.chat.id)
    await bot.reply_to(message, "✅ کپچای عضویت غیرفعال شد.")


# ---------------------------------------------------------------- #
# PING — simple liveness check, open to everyone (no admin gate needed)
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup", "private"], func=lambda m: normalize_trigger(m.text or "").strip() in PING_TRIGGERS)
async def ping(message: Message):
    start = time.monotonic()
    sent = await bot.reply_to(message, "🏓 پونگ...")
    elapsed_ms = int((time.monotonic() - start) * 1000)
    try:
        await bot.edit_message_text(
            f"🏓 پونگ! ربات روشن و در حال کار است. (پاسخ در {elapsed_ms} میلی‌ثانیه)",
            chat_id=message.chat.id, message_id=sent.message_id,
        )
    except Exception:
        pass


# ---------------------------------------------------------------- #
# پیکربندی — imports every REAL Telegram admin of this group as a bot
# admin in one shot (for groups with many existing Telegram admins that
# would otherwise need "افزودن ادمین گروه" repeated one-by-one).
# پاک سازی — the reverse: strips bot-admin status from everyone currently
# an admin in THIS chat (does not touch their real Telegram admin rights,
# and does not touch the group owner).
# Both restricted to whoever can manage roles here (group owner / Global
# Owner) - same gate as "افزودن ادمین گروه" / "حذف ادمین گروه".
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in CONFIGURE_TRIGGERS)
async def configure_admins_from_telegram(message: Message):
    if not await _require_role_manager(message):
        await bot.reply_to(message, "⚠️ فقط مالک این گروه می‌تواند پیکربندی خودکار ادمین‌ها را اجرا کند.")
        return
    try:
        members = await bot.get_chat_administrators(message.chat.id)
    except Exception as e:
        await bot.reply_to(message, bot_permission_error_reply(e))
        return

    added = []
    for member in members:
        user = member.user
        if user.is_bot:
            continue
        current_role = await db.get_user_role(message.chat.id, user.id)
        if current_role == "owner":
            continue  # don't downgrade/overwrite the recorded group owner
        await db.set_user_role(
            message.chat.id, user.id, "admin",
            username=user.username, first_name=user.first_name, last_name=user.last_name,
        )
        added.append(user.full_name if hasattr(user, "full_name") else (user.first_name or str(user.id)))

    if not added:
        await bot.reply_to(message, "هیچ ادمین تلگرامی (به‌جز مالک گروه) برای افزودن پیدا نشد.")
        return
    await bot.reply_to(
        message,
        "✅ ادمین‌های تلگرام این گروه به‌عنوان ادمین ربات ثبت شدند:\n" + "\n".join(f"• {n}" for n in added),
    )


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in CLEANUP_ADMINS_TRIGGERS)
async def cleanup_bot_admins(message: Message):
    if not await _require_role_manager(message):
        await bot.reply_to(message, "⚠️ فقط مالک این گروه می‌تواند ادمین‌های ربات را پاک‌سازی کند.")
        return
    admin_ids = await db.list_users_by_role(message.chat.id, "admin")
    if not admin_ids:
        await bot.reply_to(message, "هیچ ادمین ربات (جدا از مالک) برای این گروه ثبت نشده بود.")
        return
    for user_id in admin_ids:
        await db.set_user_role(message.chat.id, user_id, "normal")
    await bot.reply_to(message, f"✅ دسترسی ادمین ربات از {len(admin_ids)} نفر گرفته شد (مالک گروه دست‌نخورده ماند).")


# ---------------------------------------------------------------- #
# حذف {عدد} / حذف کل — bulk message deletion.
#
# "حذف {عدد}" removes exactly the last {عدد} messages the bot has actually
# logged in this chat (see database.py:get_recent_message_ids - a bot can
# only ever delete messages it has itself observed, never a group's full
# history from before it joined).
#
# "حذف کل" wipes EVERY logged message and needs an explicit confirmation
# tap first (invoker-locked, same mechanism as /help - see
# utils/invoker_lock.py) since it's irreversible and chat-wide.
# ---------------------------------------------------------------- #

DELETE_ALL_NAMESPACE = "delall"


def _delete_count_trigger(text: str) -> Optional[int]:
    """Returns N if `text` is EXACTLY "حذف {N}" (nothing else), else None."""
    t = normalize_trigger(text or "").strip()
    parts = t.split()
    if len(parts) == 2 and parts[0] == "حذف" and parts[1].isdigit():
        n = int(parts[1])
        return n if n > 0 else None
    return None


async def _bulk_delete(chat_id: int, message_ids: list) -> int:
    """Deletes message_ids in batches, tolerating already-gone/too-old ones
    that Telegram refuses individually. Returns how many actually deleted."""
    deleted = 0
    CHUNK = 100
    for i in range(0, len(message_ids), CHUNK):
        chunk = message_ids[i:i + CHUNK]
        try:
            await bot.delete_messages(chat_id, chunk)
            deleted += len(chunk)
        except Exception:
            for mid in chunk:
                try:
                    await bot.delete_message(chat_id, mid)
                    deleted += 1
                except Exception:
                    pass
    await db.delete_logged_messages(chat_id, message_ids)
    return deleted


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: _delete_count_trigger(m.text or "") is not None)
async def delete_recent_messages(message: Message):
    if not await _require_admin(message):
        return
    n = _delete_count_trigger(message.text or "")
    ids = await db.get_recent_message_ids(message.chat.id, n)
    ids.append(message.message_id)  # also remove the "حذف N" command itself
    deleted = await _bulk_delete(message.chat.id, ids)
    await bot.send_message(message.chat.id, f"✅ {max(deleted - 1, 0)} پیام اخیر حذف شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in DELETE_ALL_TRIGGERS)
async def delete_all_messages_prompt(message: Message):
    if not await _require_admin(message):
        return
    kb = InlineKeyboardMarkup()
    kb.add(
        InlineKeyboardButton("بله، همه چیز حذف شود", callback_data=invoker_encode(DELETE_ALL_NAMESPACE, message.from_user.id, "yes"), style="danger"),
        InlineKeyboardButton("انصراف", callback_data=invoker_encode(DELETE_ALL_NAMESPACE, message.from_user.id, "no"), style="success"),
    )
    await bot.reply_to(
        message,
        "⚠️ <b>این کار تمام پیام‌هایی که ربات از این گروه ثبت کرده را برای همیشه پاک می‌کند.</b>\n"
        "(پیام‌های قبل از عضویت ربات یا قبل از این آپدیت قابل حذف نیستند - محدودیت خود تلگرام است.)\n\n"
        "مطمئنید؟",
        reply_markup=kb,
    )


@bot.callback_query_handler(func=lambda c: invoker_decode(c.data, DELETE_ALL_NAMESPACE) is not None)
async def delete_all_messages_confirm(call):
    invoker_id, parts = await invoker_verify(call, DELETE_ALL_NAMESPACE)
    if invoker_id is None:
        return
    # Defense in depth: re-check live admin status, same as the panel does.
    if not await is_authorized_admin(db, call.message.chat.id, invoker_id):
        await bot.answer_callback_query(call.id, "⛔️ دسترسی مدیریتی شما در این گروه گرفته شده است.", show_alert=True)
        return
    await bot.answer_callback_query(call.id)

    if parts == ["no"]:
        await bot.edit_message_text("لغو شد. هیچ پیامی حذف نشد.", chat_id=call.message.chat.id, message_id=call.message.message_id)
        return

    if parts == ["yes"]:
        await bot.edit_message_text("⏳ در حال حذف پیام‌ها...", chat_id=call.message.chat.id, message_id=call.message.message_id)
        ids = await db.get_all_logged_message_ids(call.message.chat.id)
        deleted = await _bulk_delete(call.message.chat.id, ids)
        try:
            await bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        await bot.send_message(call.message.chat.id, f"✅ {deleted} پیام حذف شد.")