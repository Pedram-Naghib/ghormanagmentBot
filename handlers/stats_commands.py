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

DAY = timedelta(hours=24)


async def _format_stats(chat_id: int, since_iso) -> str:
    senders = await db.get_top_message_senders(chat_id, since_iso=since_iso)
    adders = await db.get_top_adders(chat_id, since_iso=since_iso)

    lines = ["📨 <b>پیام‌ها:</b>"]
    if senders:
        for user_id, count in senders:
            name = await db.get_user_display_name(user_id)
            lines.append(f"• {name}: {count} پیام")
    else:
        lines.append("پیامی ثبت نشده است.")

    lines.append("\n👥 <b>اعضای اضافه‌شده:</b>")
    if adders:
        for user_id, count in adders:
            name = await db.get_user_display_name(user_id)
            lines.append(f"• {name}: {count} عضو")
    else:
        lines.append("عضوی اضافه نشده است.")

    return "\n".join(lines)


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: m.text and m.text.strip() in {"آمار روزانه", "/daily_stats"},
)
async def daily_stats(message: Message):
    since_iso = (datetime.now(timezone.utc) - DAY).isoformat()
    text = await _format_stats(message.chat.id, since_iso)
    await bot.reply_to(message, f"📊 <b>آمار ۲۴ ساعت گذشته گروه</b>\n\n{text}")


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: m.text and m.text.strip() in {"آمار کل", "/total_stats"},
)
async def total_stats(message: Message):
    text = await _format_stats(message.chat.id, None)
    await bot.reply_to(message, f"📊 <b>آمار کلی گروه</b>\n\n{text}")