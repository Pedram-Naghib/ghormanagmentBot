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
from utils.text import normalize_fa

# --- Trigger words (all already correct Persian - see utils/text.py) ---
BAN_TRIGGERS = {"کیک", "بن", "اخراج"}
MUTE_TRIGGERS = {"میوت", "سکوت"}
UNMUTE_TRIGGERS = {"آنمیوت", "رفع سکوت", "رفع میوت"}
UNBAN_PREFIXES = ("رفع بن", "آنبن", "/unban")
VIP_TRIGGERS = {"تنظیم ویژه"}
UNVIP_TRIGGERS = {"لغو ویژه"}
ADD_ADMIN_TRIGGERS = {"افزودن ادمین گروه", "افزودن ادمین"}
REMOVE_ADMIN_TRIGGERS = {"حذف ادمین گروه", "حذف ادمین"}
LIST_ADMIN_TRIGGERS = {"لیست ادمین های گروه", "لیست ادمین ها"}
SHOW_OWNER_TRIGGERS = {"مالک این گروه", "مالک گروه"}
CLAIM_OWNER_TRIGGERS = {"ادعای مالکیت"}
SET_OWNER_PREFIX = "تنظیم مالک"
SPAM_SETTINGS_PREFIX = "تنظیم اسپم"
SHOW_SPAM_SETTINGS_TRIGGERS = {"تنظیمات اسپم"}
SET_IMAGE_PREFIX = "ثبت تصویر"

DEFAULT_MUTE_SECONDS = 24 * 60 * 60  # fallback only - see mute_user for the real default (forever)


def _norm(message: Message) -> str:
    return normalize_fa(message.text or "").strip()


async def _require_admin(message: Message) -> bool:
    return await is_authorized_admin(db, message.chat.id, message.from_user.id)


async def _require_role_manager(message: Message) -> bool:
    return await can_manage_chat_roles(db, message.chat.id, message.from_user.id)


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
    func=lambda m: (t := normalize_fa(m.text or "").strip())
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
        text = str(e)
        if "can't remove chat owner" in text or "CHAT_ADMIN_REQUIRED" in text:
            await bot.reply_to(message, "❌ نمی‌توان این کاربر را بن کرد؛ او مالک یا ادمین واقعی این گروه در تلگرام است.")
        else:
            await bot.reply_to(message, f"❌ خطا: {e}")


# ---------------------------------------------------------------- #
# UNBAN — reply to any old message from the user, OR pass @username
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_fa(m.text or "").strip().startswith(UNBAN_PREFIXES),
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
        await bot.reply_to(message, f"❌ خطا: {e}")


# ---------------------------------------------------------------- #
# MUTE — "میوت"/"سکوت" alone = forever (until manually unmuted),
#         "میوت 10" = 10 minutes
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: (t := normalize_fa(m.text or "").strip())
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
        await bot.reply_to(message, f"❌ خطا: {e}")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in UNMUTE_TRIGGERS)
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
        await bot.reply_to(message, f"❌ خطا: {e}")


# ---------------------------------------------------------------- #
# VIP — per-chat, set/unset
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in VIP_TRIGGERS)
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


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in UNVIP_TRIGGERS)
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

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in SHOW_OWNER_TRIGGERS)
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


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in CLAIM_OWNER_TRIGGERS)
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
    func=lambda m: normalize_fa(m.text or "").strip().startswith(SET_OWNER_PREFIX),
)
async def force_set_owner(message: Message):
    if not is_global_owner(message.from_user.id):
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

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in ADD_ADMIN_TRIGGERS)
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
    await bot.reply_to(message, f"✅ کاربر {target.full_name} اکنون ادمین این گروه است (فقط در همین گروه).")


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in REMOVE_ADMIN_TRIGGERS)
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


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in LIST_ADMIN_TRIGGERS)
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
# SPAM THRESHOLD MANAGEMENT — per chat, no .env editing needed
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_fa(m.text or "").strip().startswith(SPAM_SETTINGS_PREFIX),
)
async def set_spam_settings(message: Message):
    if not await _require_admin(message):
        return

    args = _norm(message).split()[2:]  # skip "تنظیم" "اسپم"
    if len(args) != 3 or not all(a.isdigit() for a in args):
        current = await db.get_chat_settings(message.chat.id)
        await bot.reply_to(
            message,
            "⚠️ فرمت درست:\n"
            "<code>تنظیم اسپم [حداکثر پیام] [بازه زمانی به ثانیه] [مدت سکوت به دقیقه]</code>\n"
            "مثال: <code>تنظیم اسپم 6 8 30</code>\n\n"
            "تنظیمات فعلی این گروه:\n"
            f"حداکثر پیام: {current['spam_message_limit']}\n"
            f"بازه زمانی: {current['spam_time_window_seconds']} ثانیه\n"
            f"مدت سکوت: {current['spam_mute_minutes']} دقیقه",
        )
        return

    limit, window, mute_minutes = (int(a) for a in args)
    await db.set_chat_settings(message.chat.id, limit, window, mute_minutes)
    await bot.reply_to(
        message,
        "✅ تنظیمات اسپم این گروه به‌روزرسانی شد:\n"
        f"حداکثر پیام: {limit}\nبازه زمانی: {window} ثانیه\nمدت سکوت: {mute_minutes} دقیقه",
    )


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: normalize_fa(m.text or "").strip() in SHOW_SPAM_SETTINGS_TRIGGERS)
async def show_spam_settings(message: Message):
    current = await db.get_chat_settings(message.chat.id)
    await bot.reply_to(
        message,
        "⚙️ <b>تنظیمات اسپم این گروه:</b>\n"
        f"حداکثر پیام مجاز: {current['spam_message_limit']}\n"
        f"در بازه: {current['spam_time_window_seconds']} ثانیه\n"
        f"مدت سکوت خودکار: {current['spam_mute_minutes']} دقیقه",
    )


# ---------------------------------------------------------------- #
# IMAGE REGISTRATION — reply to a photo with "ثبت تصویر [key]"
# ---------------------------------------------------------------- #
# Global-Owner-only (these are bot-wide assets, e.g. the /start or /help
# banner, not per-group). Captures the photo's file_id and stores just
# that tiny string - Telegram keeps hosting the actual image forever, we
# never touch the file bytes. This is how you add new images later: send
# the photo to any chat with the bot, reply to it with this command, done.

@bot.message_handler(func=lambda m: normalize_fa(m.text or "").strip().startswith(SET_IMAGE_PREFIX))
async def set_image(message: Message):
    if not is_global_owner(message.from_user.id):
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