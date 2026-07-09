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

from telebot.types import ChatPermissions, Message

from core import bot, db
from utils.permissions import (
    can_manage_chat_roles,
    is_authorized_admin,
    is_global_owner,
    is_group_admin,
)
from utils.telegram_errors import bot_permission_error_reply
from utils.text import normalize_fa, normalize_trigger

# --- Trigger words (all already correct Persian - see utils/text.py) ---
# Every command is reachable BOTH as a "/" command AND as one or more plain
# Persian text synonyms - both forms are just added to the same trigger
# set/prefix, so no separate registration is needed for the "/" form.
BAN_TRIGGERS = {"کیک", "بن", "اخراج", "سیک", "/ban", "/kick"}
MUTE_TRIGGERS = {"میوت", "سکوت", "/mute"}
UNMUTE_TRIGGERS = {"آنمیوت", "رفع سکوت", "رفع میوت", "/unmute"}
UNBAN_PREFIXES = ("رفع بن", "آنبن", "/unban")
VIP_TRIGGERS = {"تنظیم ویژه", "/vip"}
UNVIP_TRIGGERS = {"لغو ویژه", "/unvip"}
ADD_ADMIN_TRIGGERS = {"افزودن ادمین گروه", "افزودن ادمین", "/addadmin"}
REMOVE_ADMIN_TRIGGERS = {"حذف ادمین گروه", "حذف ادمین", "/removeadmin"}
LIST_ADMIN_TRIGGERS = {"لیست ادمین های گروه", "لیست ادمین ها", "/admins"}
SHOW_OWNER_TRIGGERS = {"مالک این گروه", "مالک گروه", "/owner"}
CLAIM_OWNER_TRIGGERS = {"ادعای مالکیت", "/claimowner"}
SET_OWNER_PREFIX = "تنظیم مالک"
SET_SPAM_LIMIT_PREFIX_FA = "تنظیم تعداد پیام مجاز"
SET_SPAM_LIMIT_PREFIX_SLASH = "/spamlimit"
SET_SPAM_MUTE_PREFIX_FA = "تنظیم مدت سکوت اسپم"
SET_SPAM_MUTE_PREFIX_SLASH = "/spammute"
SHOW_SPAM_SETTINGS_TRIGGERS = {"تنظیمات اسپم", "/spamstatus"}
SET_IMAGE_PREFIX = "ثبت تصویر"

WARN_TRIGGERS = {"اخطار", "/warn"}
CLEAR_WARN_TRIGGERS = {"حذف اخطار", "پاک کردن اخطار", "/clearwarn"}
LIST_WARN_TRIGGERS = {"لیست اخطار", "لیست اخطارها", "/warnlist"}
WARN_LIMIT = 3  # auto-ban after this many active warnings

ADD_FILTER_PREFIX = "افزودن کلمه فیلتر"
REMOVE_FILTER_PREFIX = "حذف کلمه فیلتر"
LIST_FILTER_TRIGGERS = {"لیست کلمات فیلتر", "/filterlist"}

SET_WELCOME_PREFIX = "تنظیم خوش آمدگویی"
WELCOME_ON_TRIGGERS = {"روشن کردن خوش آمدگویی", "/welcomeon"}
WELCOME_OFF_TRIGGERS = {"خاموش کردن خوش آمدگویی", "/welcomeoff"}
SET_GOODBYE_PREFIX = "تنظیم بدرود"
GOODBYE_ON_TRIGGERS = {"روشن کردن بدرود", "/goodbyeon"}
GOODBYE_OFF_TRIGGERS = {"خاموش کردن بدرود", "/goodbyeoff"}

DEFAULT_MUTE_SECONDS = 24 * 60 * 60  # fallback only - see mute_user for the real default (forever)

NOT_ADMIN_MESSAGE = (
    "⛔️ این دستور فقط برای <b>ادمین‌های ربات در این گروه</b> قابل استفاده است "
    "(مالک گروه، ادمین گروه، یا مالک ربات).\n"
    "توجه: ادمین بودن در خودِ تلگرام کافی نیست - باید توسط مالک گروه با «افزودن ادمین گروه» "
    "به ربات معرفی شده باشید."
)
NOT_GLOBAL_OWNER_MESSAGE = "⛔️ این دستور فقط مخصوص مالک ربات است و برای شما در دسترس نیست."


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
    await bot.reply_to(message, NOT_ADMIN_MESSAGE)
    return False


async def _require_role_manager(message: Message) -> bool:
    return await can_manage_chat_roles(db, message.chat.id, message.from_user.id)


async def _require_global_owner(message: Message) -> bool:
    if is_global_owner(message.from_user.id):
        return True
    await bot.reply_to(message, NOT_GLOBAL_OWNER_MESSAGE)
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
    Proactively blocks banning/muting an owner or admin, with a clear bot
    response, instead of letting a raw Telegram API error ("can't remove
    chat owner") reach the admin. Returns True if the action was blocked.
    """
    if is_global_owner(target.id):
        await bot.reply_to(message, "❌ نمی‌توانید مالک ربات را مسدود کنید.")
        return True
    role = await db.get_user_role(message.chat.id, target.id)
    if role == "owner":
        await bot.reply_to(message, "❌ نمی‌توانید مالک این گروه را مسدود کنید.")
        return True
    if role == "admin":
        await bot.reply_to(
            message,
            "❌ این کاربر ادمین این گروه است. ابتدا با «حذف ادمین گروه» دسترسی ادمینی او را بگیرید، سپس دوباره تلاش کنید.",
        )
        return True
    return False


# ---------------------------------------------------------------- #
# BAN (kick + ban combined - see module docstring above)
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: (t := normalize_trigger(m.text or "").strip())
    and (t in BAN_TRIGGERS or any(t.startswith(trig + " ") for trig in BAN_TRIGGERS)),
)
async def ban_user(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(
            message,
            "⚠️ برای اخراج و بن کردن کاربر، روی پیام او ریپلای کنید، یا بنویسید: <code>بن @username</code>",
        )
        return
    if await _refuse_if_protected(message, target):
        return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.reply_to(
            message,
            f"⛔️ کاربر {target.full_name} از گروه اخراج و بن شد.\n"
            f"او نمی‌تواند با لینک دعوت دوباره وارد شود، مگر با دستور «رفع بن».",
        )
    except Exception as e:
        await bot.reply_to(message, bot_permission_error_reply(e))


# ---------------------------------------------------------------- #
# UNBAN — reply to any old message from the user, OR pass @username
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_trigger(m.text or "").strip().startswith(UNBAN_PREFIXES),
)
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
        await bot.reply_to(
            message,
            "⚠️ برای رفع بن، روی یکی از پیام‌های قبلی کاربر ریپلای کنید یا یوزرنیم را بنویسید:\n"
            "مثال: <code>رفع بن @username</code>\n"
            "(روش یوزرنیم فقط وقتی کار می‌کند که آن کاربر قبلاً در همین گروه پیام داده باشد.)",
        )
        return

    try:
        await bot.unban_chat_member(message.chat.id, target_id, only_if_banned=True)
        await bot.reply_to(message, f"✅ کاربر {target_label} از بن خارج شد و می‌تواند دوباره وارد گروه شود.")
    except Exception as e:
        await bot.reply_to(message, bot_permission_error_reply(e))


# ---------------------------------------------------------------- #
# MUTE — "میوت"/"سکوت" alone = forever (until manually unmuted),
#         "میوت 10" = 10 minutes
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: (t := normalize_trigger(m.text or "").strip())
    and (t in MUTE_TRIGGERS or any(t.startswith(trig + " ") for trig in MUTE_TRIGGERS)),
)
async def mute_user(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ برای سکوت کردن کاربر، روی پیام او ریپلای کنید.")
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
            await bot.reply_to(message, f"🔇 کاربر {target.full_name} به مدت {minutes} دقیقه سکوت (Mute) شد.")
        else:
            # No until_date -> Telegram treats this as "forever" (until manually lifted).
            await bot.restrict_chat_member(
                message.chat.id, target.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
            await bot.reply_to(
                message,
                f"🔇 کاربر {target.full_name} سکوت (Mute) شد و تا زمانی که با «رفع سکوت» "
                f"آزاد نشود، همینطور می‌ماند.",
            )
    except Exception as e:
        await bot.reply_to(message, bot_permission_error_reply(e))


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in UNMUTE_TRIGGERS)
async def unmute_user(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ برای رفع سکوت، روی پیام کاربر ریپلای کنید یا بنویسید: <code>رفع سکوت @username</code>")
        return
    try:
        # Restore this group's own default member permissions, rather than
        # guessing a fixed set - this is the correct way to "undo" a mute.
        chat = await bot.get_chat(message.chat.id)
        permissions = chat.permissions or ChatPermissions(can_send_messages=True)
        await bot.restrict_chat_member(message.chat.id, target.id, permissions=permissions)
        await bot.reply_to(message, f"🔊 سکوت کاربر {target.full_name} برداشته شد.")
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
        await bot.reply_to(message, "⚠️ برای تنظیم عضو ویژه، روی پیام او ریپلای کنید.")
        return
    await db.set_user_role(
        message.chat.id, target.id, "vip",
        username=target.username, first_name=target.first_name, last_name=target.last_name,
    )
    await bot.reply_to(
        message, f"⭐️ کاربر {target.full_name} اکنون عضو ویژهٔ این گروه است (فقط در همین گروه)."
    )


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in UNVIP_TRIGGERS)
async def unset_vip(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ برای لغو عضویت ویژه، روی پیام او ریپلای کنید.")
        return
    current_role = await db.get_user_role(message.chat.id, target.id)
    if current_role != "vip":
        await bot.reply_to(message, f"{target.full_name} عضو ویژهٔ این گروه نیست.")
        return
    await db.set_user_role(message.chat.id, target.id, "normal")
    await bot.reply_to(message, f"✅ عضویت ویژهٔ {target.full_name} در این گروه لغو شد.")


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


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_trigger(m.text or "").strip().startswith(SET_OWNER_PREFIX),
)
async def force_set_owner(message: Message):
    if not await _require_global_owner(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربری که می‌خواهید مالک گروه شود ریپلای کنید.")
        return
    await db.set_user_role(
        message.chat.id, target.id, "owner",
        username=target.username, first_name=target.first_name, last_name=target.last_name,
    )
    await bot.reply_to(message, f"✅ {target.full_name} اکنون مالک این گروه است.")


# ---------------------------------------------------------------- #
# GROUP ADMINS — appointed by the group's owner (or a Global Owner) only
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
    "• دسترسی به پنل تنظیمات گروه (/panel)\n\n"
    "برای دیدن لیست کامل دستورات بنویس: /help"
)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in ADD_ADMIN_TRIGGERS)
async def add_admin(message: Message):
    if not await _require_role_manager(message):
        await bot.reply_to(message, "⚠️ فقط مالک این گروه می‌تواند ادمین گروه اضافه کند.")
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
    if not await _require_role_manager(message):
        await bot.reply_to(message, "⚠️ فقط مالک این گروه می‌تواند دسترسی ادمین را بگیرد.")
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


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in LIST_ADMIN_TRIGGERS)
async def list_admins(message: Message):
    if not await _require_admin(message):
        return
    admin_ids = await db.list_users_by_role(message.chat.id, "admin")
    owner_id = await db.get_chat_owner(message.chat.id)

    lines = []
    if owner_id:
        owner_name = await db.get_user_display_name(message.chat.id, owner_id)
        lines.append(f"👑 مالک: {owner_name}")
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
    func=lambda m: normalize_trigger(m.text or "").strip().startswith((SET_SPAM_LIMIT_PREFIX_FA, SET_SPAM_LIMIT_PREFIX_SLASH)),
)
async def set_spam_limit(message: Message):
    if not await _require_admin(message):
        return
    text = _norm(message)
    prefix = SET_SPAM_LIMIT_PREFIX_SLASH if text.startswith(SET_SPAM_LIMIT_PREFIX_SLASH) else SET_SPAM_LIMIT_PREFIX_FA
    arg = text[len(prefix):].strip()
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
    await bot.reply_to(message, f"✅ سقف پیام مجاز این گروه روی {limit} پیام در ۳ ثانیه تنظیم شد.")


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_trigger(m.text or "").strip().startswith((SET_SPAM_MUTE_PREFIX_FA, SET_SPAM_MUTE_PREFIX_SLASH)),
)
async def set_spam_mute(message: Message):
    if not await _require_admin(message):
        return
    text = _norm(message)
    prefix = SET_SPAM_MUTE_PREFIX_SLASH if text.startswith(SET_SPAM_MUTE_PREFIX_SLASH) else SET_SPAM_MUTE_PREFIX_FA
    arg = text[len(prefix):].strip()
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

def _extract_reason(message: Message, triggers) -> str:
    text = _norm(message)
    for trig in sorted(triggers, key=len, reverse=True):
        if text == trig:
            return None
        if text.startswith(trig + " "):
            return text[len(trig):].strip() or None
    return None


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: (t := normalize_trigger(m.text or "").strip())
    and (t in WARN_TRIGGERS or any(t.startswith(trig + " ") for trig in WARN_TRIGGERS)),
)
async def warn_user(message: Message):
    if not await _require_admin(message):
        return
    target = await _resolve_target(message)
    if not target:
        await bot.reply_to(
            message,
            "⚠️ برای اخطار دادن به کاربر، روی پیام او ریپلای کنید یا بنویسید: <code>اخطار @username</code>",
        )
        return
    if await _refuse_if_protected(message, target):
        return

    reason = _extract_reason(message, WARN_TRIGGERS)
    count = await db.add_warning(message.chat.id, target.id, message.from_user.id, reason)
    reason_line = f"\nدلیل: {reason}" if reason else ""

    if count >= WARN_LIMIT:
        try:
            await bot.ban_chat_member(message.chat.id, target.id)
            await db.clear_warnings(message.chat.id, target.id)
            await bot.reply_to(
                message,
                f"⚠️ کاربر {target.full_name} اخطار {count} از {WARN_LIMIT} را دریافت کرد و به همین دلیل "
                f"به‌طور خودکار از گروه اخراج و بن شد.{reason_line}",
            )
        except Exception as e:
            await bot.reply_to(message, bot_permission_error_reply(e))
    else:
        await bot.reply_to(
            message, f"⚠️ کاربر {target.full_name} اخطار گرفت ({count} از {WARN_LIMIT}).{reason_line}"
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
    await bot.reply_to(message, f"✅ اخطارهای {target.full_name} پاک شد.")


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
    confirmation = "✅ متن خوش‌آمدگویی این گروه به‌روزرسانی شد."
    if media_file_id:
        confirmation += " (همراه با رسانه‌ای که ریپلای کردید)"
    await bot.reply_to(message, confirmation)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in {"حذف رسانه خوش آمدگویی", "/clearwelcomemedia"})
async def clear_welcome_media(message: Message):
    if not await _require_admin(message):
        return
    await db.set_welcome_settings(message.chat.id, clear_media=True)
    await bot.reply_to(message, "✅ رسانهٔ خوش‌آمدگویی حذف شد؛ از این پس فقط متن ارسال می‌شود.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in WELCOME_ON_TRIGGERS)
async def welcome_on(message: Message):
    if not await _require_admin(message):
        return
    await db.set_welcome_settings(message.chat.id, enabled=True)
    await bot.reply_to(message, "✅ خوش‌آمدگویی برای اعضای جدید این گروه فعال شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in WELCOME_OFF_TRIGGERS)
async def welcome_off(message: Message):
    if not await _require_admin(message):
        return
    await db.set_welcome_settings(message.chat.id, enabled=False)
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
    confirmation = "✅ متن بدرود این گروه به‌روزرسانی شد."
    if media_file_id:
        confirmation += " (همراه با رسانه‌ای که ریپلای کردید)"
    await bot.reply_to(message, confirmation)


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in {"حذف رسانه بدرود", "/cleargoodbyemedia"})
async def clear_goodbye_media(message: Message):
    if not await _require_admin(message):
        return
    await db.set_goodbye_settings(message.chat.id, clear_media=True)
    await bot.reply_to(message, "✅ رسانهٔ بدرود حذف شد؛ از این پس فقط متن ارسال می‌شود.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in GOODBYE_ON_TRIGGERS)
async def goodbye_on(message: Message):
    if not await _require_admin(message):
        return
    await db.set_goodbye_settings(message.chat.id, enabled=True)
    await bot.reply_to(message, "✅ بدرود برای اعضایی که گروه را ترک می‌کنند فعال شد.")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in GOODBYE_OFF_TRIGGERS)
async def goodbye_off(message: Message):
    if not await _require_admin(message):
        return
    await db.set_goodbye_settings(message.chat.id, enabled=False)
    await bot.reply_to(message, "✅ بدرود برای اعضایی که گروه را ترک می‌کنند غیرفعال شد.")


# ---------------------------------------------------------------- #
# JOIN-REQUEST CAPTCHA — OFF by default (see handlers/captcha.py)
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in {"روشن کردن کپچا", "/captchaon"})
async def captcha_on(message: Message):
    if not await _require_admin(message):
        return
    await db.set_join_captcha_enabled(message.chat.id, True)
    await bot.reply_to(
        message,
        "✅ کپچای عضویت فعال شد. توجه: این ویژگی فقط برای گروه‌هایی که «تایید درخواست عضویت» "
        "تلگرام را فعال کرده‌اند اثر دارد.",
    )


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_trigger(m.text or "").strip() in {"خاموش کردن کپچا", "/captchaoff"})
async def captcha_off(message: Message):
    if not await _require_admin(message):
        return
    await db.set_join_captcha_enabled(message.chat.id, False)
    await bot.reply_to(message, "✅ کپچای عضویت غیرفعال شد.")