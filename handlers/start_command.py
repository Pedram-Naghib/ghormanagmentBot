"""
handlers/start_command.py
----------------------------
/start — shown in a private chat with the bot. If an image is registered
under the key "start_banner" (see "ثبت تصویر" in handlers/admin_commands.py),
it's sent as a photo with the welcome text as its caption; the image itself
never changes when the person taps a button below it.
"""

from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import SUPPORT_URL
from core import bot, db
from handlers.help_command import send_help

_bot_username_cache = None


async def _get_bot_username() -> str:
    global _bot_username_cache
    if _bot_username_cache is None:
        me = await bot.get_me()
        _bot_username_cache = me.username
    return _bot_username_cache


def _start_text(first_name: str) -> str:
    name = first_name or "دوست من"
    return (
        f"سلام {name} 👋\n\n"
        f"من ربات مدیریت گروه‌ام. کارم اینه که کارهای تکراری و خسته‌کننده‌ی "
        f"ادمین‌بودن رو از دوشتون بردارم:\n\n"
        f"🚫 لینک و فوروارد مزاحم رو خودکار حذف می‌کنم\n"
        f"🔇 اسپم‌کننده‌ها رو خودکار سکوت می‌کنم\n"
        f"📊 آمار روزانه و کلی هر گروه رو نشون می‌دم\n"
        f"👑 توی هر گروه، مالک و ادمین و عضو ویژه‌ی مخصوص همون گروه دارید\n\n"
        f"هر گروه تنظیمات کاملاً مستقل خودش رو داره؛ چیزی که توی یک گروه "
        f"تغییر بدید روی گروه‌های دیگه اثر نمی‌ذاره.\n\n"
        f"برای شروع، من رو به گروه‌تون اضافه و ادمین کنید 👇"
    )


async def _start_keyboard() -> InlineKeyboardMarkup:
    username = await _get_bot_username()
    kb = InlineKeyboardMarkup(row_width=1)

    add_url = (
        f"https://t.me/{username}?startgroup=true"
        f"&admin=delete_messages+restrict_members+invite_users"
    )
    kb.add(InlineKeyboardButton("➕ افزودن به گروه", url=add_url))
    kb.add(InlineKeyboardButton("📖 راهنمای کامل", callback_data="show_help"))
    if SUPPORT_URL:
        kb.add(InlineKeyboardButton("💬 پشتیبانی", url=SUPPORT_URL))
    return kb


@bot.message_handler(commands=["start"])
async def start_command(message: Message):
    text = _start_text(message.from_user.first_name if message.from_user else "")
    keyboard = await _start_keyboard()
    banner = await db.get_asset("start_banner")
    if banner:
        await bot.send_photo(message.chat.id, banner, caption=text, reply_markup=keyboard)
    else:
        await bot.reply_to(message, text, reply_markup=keyboard)


@bot.callback_query_handler(func=lambda c: c.data == "show_help")
async def start_show_help(call: CallbackQuery):
    await bot.answer_callback_query(call.id)
    await send_help(call.message.chat.id)