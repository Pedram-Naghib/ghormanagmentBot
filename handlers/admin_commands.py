"""
handlers/admin_commands.py
-----------------------------
Management commands. Usable by (see utils/permissions.py):
    - Global Owners   (hardcoded in .env -> OWNER_USER_IDS) - everywhere
    - Group Owners    (whoever added the bot to THIS group) - this group only
    - Group Admins    (appointed by that group's owner) - this group only

Triggered as plain Persian text, sent as a REPLY to the target user's message.

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

from telebot.types import ChatPermissions, Message

from core import bot, db
from utils.permissions import (
    can_manage_chat_roles,
    is_authorized_admin,
    is_global_owner,
    is_group_admin,
)

# --- Trigger words ---
BAN_TRIGGERS = {"کیک", "بن", "اخراج"}
MUTE_TRIGGERS = {"میوت", "سکوت"}
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

DEFAULT_MUTE_SECONDS = 24 * 60 * 60  # 24h manual mute triggered by an admin


async def _require_admin(message: Message) -> bool:
    return await is_authorized_admin(db, message.chat.id, message.from_user.id)


async def _require_role_manager(message: Message) -> bool:
    return await can_manage_chat_roles(db, message.chat.id, message.from_user.id)


def _reply_target(message: Message):
    if message.reply_to_message and message.reply_to_message.from_user:
        return message.reply_to_message.from_user
    return None


# ---------------------------------------------------------------- #
# BAN (kick + ban combined - see module docstring above)
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in BAN_TRIGGERS)
async def ban_user(message: Message):
    if not await _require_admin(message):
        return
    target = _reply_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ برای اخراج و بن کردن کاربر، روی پیام او ریپلای کنید.")
        return
    try:
        await bot.ban_chat_member(message.chat.id, target.id)
        await bot.reply_to(
            message,
            f"⛔️ کاربر {target.full_name} از گروه اخراج و بن شد.\n"
            f"او نمی‌تواند با لینک دعوت دوباره وارد شود، مگر با دستور «رفع بن».",
        )
    except Exception as e:
        await bot.reply_to(message, f"❌ خطا: {e}")


# ---------------------------------------------------------------- #
# UNBAN — reply to any old message from the user, OR pass @username
# ---------------------------------------------------------------- #

@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: m.text and m.text.strip().startswith(UNBAN_PREFIXES),
)
async def unban_user(message: Message):
    if not await _require_admin(message):
        return

    target_id = None
    target_label = None

    reply_user = _reply_target(message)
    if reply_user:
        target_id = reply_user.id
        target_label = reply_user.full_name
    else:
        match = re.search(r"@(\w+)", message.text or "")
        if match:
            username = match.group(1)
            target_id = await db.get_user_id_by_username(username)
            target_label = f"@{username}"

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
# MUTE
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in MUTE_TRIGGERS)
async def mute_user(message: Message):
    if not await _require_admin(message):
        return
    target = _reply_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ برای سکوت کردن کاربر، روی پیام او ریپلای کنید.")
        return
    until = int(time.time() + DEFAULT_MUTE_SECONDS)
    try:
        await bot.restrict_chat_member(
            message.chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until,
        )
        await bot.reply_to(message, f"🔇 کاربر {target.full_name} به مدت ۲۴ ساعت سکوت (Mute) شد.")
    except Exception as e:
        await bot.reply_to(message, f"❌ خطا: {e}")


# ---------------------------------------------------------------- #
# VIP — per-chat, set/unset
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in VIP_TRIGGERS)
async def set_vip(message: Message):
    if not await _require_admin(message):
        return
    target = _reply_target(message)
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


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in UNVIP_TRIGGERS)
async def unset_vip(message: Message):
    if not await _require_admin(message):
        return
    target = _reply_target(message)
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

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in SHOW_OWNER_TRIGGERS)
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


@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in CLAIM_OWNER_TRIGGERS)
async def claim_owner(message: Message):
    """
    Bootstrap fallback: if this chat has no recorded owner yet (e.g. the bot
    was added before this feature existed), a real Telegram admin/creator of
    the group can claim it. Does nothing if an owner is already set.
    """
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
    func=lambda m: m.text and m.text.strip().startswith(SET_OWNER_PREFIX),
)
async def force_set_owner(message: Message):
    """Global-Owner-only override, for support/edge cases (e.g. real ownership transfer)."""
    if not is_global_owner(message.from_user.id):
        return
    target = _reply_target(message)
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

@bot.message_handler(
    chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in ADD_ADMIN_TRIGGERS
)
async def add_admin(message: Message):
    if not await _require_role_manager(message):
        await bot.reply_to(message, "⚠️ فقط مالک این گروه می‌تواند ادمین گروه اضافه کند.")
        return
    target = _reply_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربری که می‌خواهید ادمین این گروه شود ریپلای کنید.")
        return
    await db.set_user_role(
        message.chat.id, target.id, "admin",
        username=target.username, first_name=target.first_name, last_name=target.last_name,
    )
    await bot.reply_to(
        message, f"✅ کاربر {target.full_name} اکنون ادمین این گروه است (فقط در همین گروه)."
    )


@bot.message_handler(
    chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in REMOVE_ADMIN_TRIGGERS
)
async def remove_admin(message: Message):
    if not await _require_role_manager(message):
        await bot.reply_to(message, "⚠️ فقط مالک این گروه می‌تواند دسترسی ادمین را بگیرد.")
        return
    target = _reply_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربر مورد نظر ریپلای کنید.")
        return
    current_role = await db.get_user_role(message.chat.id, target.id)
    if current_role != "admin":
        await bot.reply_to(message, f"{target.full_name} ادمین این گروه نیست.")
        return
    await db.set_user_role(message.chat.id, target.id, "normal")
    await bot.reply_to(message, f"✅ دسترسی ادمین این گروه از {target.full_name} گرفته شد.")


@bot.message_handler(
    chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in LIST_ADMIN_TRIGGERS
)
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
    func=lambda m: m.text and m.text.strip().startswith(SPAM_SETTINGS_PREFIX),
)
async def set_spam_settings(message: Message):
    if not await _require_admin(message):
        return

    args = message.text.strip().split()[2:]  # skip "تنظیم" "اسپم"
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


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: m.text and m.text.strip() in SHOW_SPAM_SETTINGS_TRIGGERS,
)
async def show_spam_settings(message: Message):
    current = await db.get_chat_settings(message.chat.id)
    await bot.reply_to(
        message,
        "⚙️ <b>تنظیمات اسپم این گروه:</b>\n"
        f"حداکثر پیام مجاز: {current['spam_message_limit']}\n"
        f"در بازه: {current['spam_time_window_seconds']} ثانیه\n"
        f"مدت سکوت خودکار: {current['spam_mute_minutes']} دقیقه",
    )