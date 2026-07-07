"""
handlers/admin_commands.py
-----------------------------
Management commands. Usable by (see utils/permissions.py):
    - Owners            (hardcoded in .env -> OWNER_USER_IDS)
    - Bot Admins        (bot-wide, stored in Supabase - "افزودن ادمین")
    - Real Telegram admins/creators of the current group

Triggered as plain Persian text, sent as a REPLY to the target user's
message (same UX as before).

--------------------------------------------------------------------
A NOTE ON "کیک" vs "بن" (kick vs ban)
--------------------------------------------------------------------
Telegram only really has one underlying action here: banChatMember, which
removes the user AND blocks them from rejoining via invite link until
someone unbans them. A "kick" is just a ban immediately followed by an
unban - the user is removed but can rejoin right away with a new invite
link. Per your request, this bot keeps it simple: کیک/بن/اخراج all do the
same thing - remove the user AND keep them banned until an admin runs
"رفع بن". No separate "temporary kick" command.
"""

import re
import time

from telebot.types import ChatPermissions, Message

from core import bot, db
from utils.permissions import is_authorized_admin, is_owner

# --- Trigger words ---
BAN_TRIGGERS = {"کیک", "بن", "اخراج"}
MUTE_TRIGGERS = {"میوت", "سکوت"}
UNBAN_PREFIXES = ("رفع بن", "آنبن", "/unban")
VIP_TRIGGERS = {"تنظیم ویژه"}
ADD_BOT_ADMIN_TRIGGERS = {"افزودن ادمین"}
REMOVE_BOT_ADMIN_TRIGGERS = {"حذف ادمین"}
LIST_BOT_ADMIN_TRIGGERS = {"لیست ادمین ها", "لیست ادمین‌ها"}
SPAM_SETTINGS_PREFIX = "تنظیم اسپم"
SHOW_SPAM_SETTINGS_TRIGGERS = {"تنظیمات اسپم"}

DEFAULT_MUTE_SECONDS = 24 * 60 * 60  # 24h manual mute triggered by an admin


async def _require_admin(message: Message) -> bool:
    return await is_authorized_admin(bot, db, message.chat.id, message.from_user.id)


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
# VIP
# ---------------------------------------------------------------- #

@bot.message_handler(chat_types=["group", "supergroup"], func=lambda m: m.text and m.text.strip() in VIP_TRIGGERS)
async def set_vip(message: Message):
    if not await _require_admin(message):
        return
    target = _reply_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ برای تنظیم عضو ویژه، روی پیام او ریپلای کنید.")
        return
    await db.upsert_user(target.id, target.username, target.first_name, target.last_name)
    await db.set_vip(target.id, True)
    await bot.reply_to(message, f"⭐️ کاربر {target.full_name} اکنون عضو ویژه (VIP) است.")


# ---------------------------------------------------------------- #
# BOT ADMIN MANAGEMENT — owner-only, bot-wide (NOT scoped to one group)
# ---------------------------------------------------------------- #

@bot.message_handler(func=lambda m: m.text and m.text.strip() in ADD_BOT_ADMIN_TRIGGERS)
async def add_bot_admin(message: Message):
    if not is_owner(message.from_user.id):
        return
    target = _reply_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربری که می‌خواهید ادمین ربات شود ریپلای کنید.")
        return
    await db.upsert_user(target.id, target.username, target.first_name, target.last_name)
    await db.add_bot_admin(target.id, added_by=message.from_user.id)
    await bot.reply_to(
        message,
        f"✅ کاربر {target.full_name} اکنون ادمین ربات است و در همهٔ گروه‌های این ربات دسترسی مدیریتی دارد.",
    )


@bot.message_handler(func=lambda m: m.text and m.text.strip() in REMOVE_BOT_ADMIN_TRIGGERS)
async def remove_bot_admin(message: Message):
    if not is_owner(message.from_user.id):
        return
    target = _reply_target(message)
    if not target:
        await bot.reply_to(message, "⚠️ روی پیام کاربر مورد نظر ریپلای کنید.")
        return
    await db.remove_bot_admin(target.id)
    await bot.reply_to(message, f"✅ دسترسی ادمین ربات از {target.full_name} گرفته شد.")


@bot.message_handler(func=lambda m: m.text and m.text.strip() in LIST_BOT_ADMIN_TRIGGERS)
async def list_bot_admins(message: Message):
    if message.chat.type in ("group", "supergroup") and not await _require_admin(message):
        return
    admins = await db.list_bot_admins()
    if not admins:
        await bot.reply_to(message, "هیچ ادمین ربات (جدا از ادمین‌های تلگرام) ثبت نشده است.")
        return
    lines = ["👮‍♂️ <b>ادمین‌های ربات:</b>"]
    for user_id in admins:
        name = await db.get_user_display_name(user_id)
        lines.append(f"• {name}")
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