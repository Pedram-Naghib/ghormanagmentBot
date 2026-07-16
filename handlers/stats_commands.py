"""
handlers/stats_commands.py
-----------------------------
آمار روزانه  -> activity in the last 24 hours (+ who joined in that window)
آمار کل      -> all-time activity

Both list top message senders and top member-adders, scoped to this chat.
Every name is a clickable tg://user mention (tap to open their profile),
not just plain text.
"""

from datetime import datetime, timedelta, timezone

from telebot.types import Message

from core import bot, db
from utils.text import normalize_fa

DAY = timedelta(hours=24)
NEW_JOINERS_TOP_ADDERS_LIMIT = 3


def _mention(user_id: int, name: str) -> str:
    return f'<a href="tg://user?id={user_id}">{name}</a>'


async def _format_stats(chat_id: int, since) -> str:
    senders = await db.get_top_message_senders(chat_id, since=since)
    adders = await db.get_top_adders(chat_id, since=since)

    lines = ["📨 <b>پیام‌ها:</b>"]
    if senders:
        for user_id, count in senders:
            name = await db.get_user_display_name(chat_id, user_id)
            lines.append(f"• {_mention(user_id, name)}: {count} پیام")
    else:
        lines.append("پیامی ثبت نشده است.")

    lines.append("\n👥 <b>اعضای اضافه‌شده:</b>")
    if adders:
        for user_id, count in adders:
            name = await db.get_user_display_name(chat_id, user_id)
            lines.append(f"• {_mention(user_id, name)}: {count} عضو")
    else:
        lines.append("عضوی اضافه نشده است.")

    return "\n".join(lines)


async def _new_joiners_block(chat_id: int, since) -> str:
    """اعضای جدید (۲۴ ساعت اخیر) + ۳ نفر برتر در افزودن عضو - only makes
    sense in the daily stats context (it's specifically a 24h view), so it
    lives here rather than on every /پروفایل lookup."""
    recent_joins = await db.get_recently_joined_members(chat_id, since=since)
    top_adders = await db.get_top_adders(chat_id, since=since, limit=NEW_JOINERS_TOP_ADDERS_LIMIT)

    lines = ["\n➖➖➖➖➖➖➖➖➖➖\n🆕 <b>اعضای جدید (۲۴ ساعت اخیر)</b>"]
    if recent_joins:
        for user_id, _joined_at in recent_joins:
            name = await db.get_user_display_name(chat_id, user_id)
            lines.append(f"• {_mention(user_id, name)}")
    else:
        lines.append("در ۲۴ ساعت اخیر عضو جدیدی وارد نشده.")

    lines.append("\n🏆 <b>۳ نفر برتر در افزودن عضو</b>")
    if top_adders:
        for user_id, count in top_adders:
            name = await db.get_user_display_name(chat_id, user_id)
            lines.append(f"• {_mention(user_id, name)}: {count} عضو")
    else:
        lines.append("هنوز کسی عضوی به این گروه اضافه نکرده.")

    return "\n".join(lines)


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_fa(m.text or "").strip() in {"آمار روزانه", "امار روزانه", "آمار روز", "امار روز"},
)
async def daily_stats(message: Message):
    since = datetime.now(timezone.utc) - DAY
    text = await _format_stats(message.chat.id, since)
    text += await _new_joiners_block(message.chat.id, since)
    await bot.reply_to(message, f"📊 <b>آمار ۲۴ ساعت گذشته گروه</b>\n\n{text}")


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_fa(m.text or "").strip() in {"آمار کل", "امار کل"},
)
async def total_stats(message: Message):
    text = await _format_stats(message.chat.id, None)
    await bot.reply_to(message, f"📊 <b>آمار کلی گروه</b>\n\n{text}")