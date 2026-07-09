"""
handlers/stats_commands.py
-----------------------------
آمار روزانه  -> activity in the last 24 hours
آمار کل      -> all-time activity

Both list top message senders and top member-adders, scoped to this chat.
"""

from datetime import datetime, timedelta, timezone

from telebot.types import Message

from core import bot, db
from utils.text import normalize_fa

DAY = timedelta(hours=24)


async def _format_stats(chat_id: int, since) -> str:
    senders = await db.get_top_message_senders(chat_id, since=since)
    adders = await db.get_top_adders(chat_id, since=since)

    lines = ["📨 <b>پیام‌ها:</b>"]
    if senders:
        for user_id, count in senders:
            name = await db.get_user_display_name(chat_id, user_id)
            lines.append(f"• {name}: {count} پیام")
    else:
        lines.append("پیامی ثبت نشده است.")

    lines.append("\n👥 <b>اعضای اضافه‌شده:</b>")
    if adders:
        for user_id, count in adders:
            name = await db.get_user_display_name(chat_id, user_id)
            lines.append(f"• {name}: {count} عضو")
    else:
        lines.append("عضوی اضافه نشده است.")

    return "\n".join(lines)


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_fa(m.text or "").strip() in {"آمار روز", "/daily_stats", "امار روز"},
)
async def daily_stats(message: Message):
    since = datetime.now(timezone.utc) - DAY
    text = await _format_stats(message.chat.id, since)
    await bot.reply_to(message, f"📊 <b>آمار ۲۴ ساعت گذشته گروه</b>\n\n{text}")


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_fa(m.text or "").strip() in {"آمار کل", "/total_stats", "امار کل"},
)
async def total_stats(message: Message):
    text = await _format_stats(message.chat.id, None)
    await bot.reply_to(message, f"📊 <b>آمار کلی گروه</b>\n\n{text}")