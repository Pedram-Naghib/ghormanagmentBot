"""
handlers/profile_command.py
------------------------------
پروفایل / /profile

Reply to someone's message with this word to see their name, profile
picture (if available), role, total messages in this group, and messages
in the last 24 hours. Used without a reply, shows your own profile.
"""

from datetime import datetime, timedelta, timezone

from telebot.types import Message

from core import bot, db

DAY = timedelta(hours=24)


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: m.text and m.text.strip() in {"پروفایل", "/profile"},
)
async def show_profile(message: Message):
    target = (
        message.reply_to_message.from_user
        if message.reply_to_message and message.reply_to_message.from_user
        else message.from_user
    )

    total = await db.get_user_message_count(target.id, message.chat.id)
    since_iso = (datetime.now(timezone.utc) - DAY).isoformat()
    last_24h = await db.get_user_message_count(target.id, message.chat.id, since_iso=since_iso)

    is_vip = await db.is_vip(target.id)
    role = "⭐️ ویژه (VIP)" if is_vip else "👤 عادی"

    full_name = " ".join(filter(None, [target.first_name, target.last_name])) or "-"
    username_line = f"یوزرنیم: @{target.username}\n" if target.username else ""

    caption = (
        f"👤 <b>پروفایل کاربر</b>\n\n"
        f"نام: {full_name}\n"
        f"{username_line}"
        f"سطح دسترسی: {role}\n"
        f"📨 کل پیام‌ها در این گروه: {total}\n"
        f"🕓 پیام‌های ۲۴ ساعت اخیر: {last_24h}"
    )

    try:
        photos = await bot.get_user_profile_photos(target.id, limit=1)
        if photos.total_count > 0:
            file_id = photos.photos[0][-1].file_id
            await bot.send_photo(
                message.chat.id, file_id, caption=caption, reply_to_message_id=message.message_id
            )
            return
    except Exception:
        pass

    await bot.reply_to(message, caption)