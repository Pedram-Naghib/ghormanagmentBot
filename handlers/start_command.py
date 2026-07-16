"""
handlers/start_command.py
----------------------------
/start — shown in a private chat with the bot. If an image is registered
under the key "start_banner" (see "ثبت تصویر" in handlers/admin_commands.py),
it's sent as a photo with the welcome text as its caption; the image itself
never changes when the person taps a button below it.

WHY "/start" STILL EXISTS DESPITE "NO SLASH COMMANDS": this one is not a
user-typed command - Telegram's own client ALWAYS sends the literal text
"/start" automatically the moment someone taps "Start" in a fresh DM or
opens a "https://t.me/<bot>?startgroup=..." deep link. There is no text-
only equivalent for that platform mechanic, so it has to stay wired up or
the "add me to your group" flow (and opening a DM with the bot at all)
would simply stop working. It is NOT exposed in the bot's "/" command
menu (see bot.py) and is not something admins are meant to type by hand.

SECURITY: the "راهنمای کامل" button is invoker-locked (utils/invoker_lock.py) -
only the person who ran /start can press it.
"""

from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import SUPPORT_URL
from core import bot
from handlers.help_command import send_help
from utils.banners import send_banner
from utils.invoker_lock import encode, verify

NAMESPACE = "strt"

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


async def _start_keyboard(invoker_id: int) -> InlineKeyboardMarkup:
    username = await _get_bot_username()
    kb = InlineKeyboardMarkup(row_width=1)

    add_url = (
        f"https://t.me/{username}?startgroup=true"
        f"&admin=delete_messages+restrict_members+invite_users"
    )
    kb.add(InlineKeyboardButton("➕ افزودن به گروه", url=add_url))
    kb.add(InlineKeyboardButton("📖 راهنمای کامل", callback_data=encode(NAMESPACE, invoker_id, "show_help")))
    if SUPPORT_URL:
        kb.add(InlineKeyboardButton("💬 پشتیبانی", url=SUPPORT_URL))
    return kb


def _start_targets_this_bot(text: str, own_username: str) -> bool:
    """pyTelegramBotAPI's `commands=` filter matches "/start" regardless of
    which bot is @-mentioned (it strips and ignores the "@..." suffix
    entirely - see telebot.util.extract_command), so without this check
    THIS bot would also reply to "/start@SomeOtherBot" sent in a group
    where multiple bots are present. Only react if there's no @mention at
    all (a plain "/start"), or it explicitly names THIS bot."""
    head = (text or "").split()[0] if text else ""
    if "@" not in head:
        return True
    mentioned = head.split("@", 1)[1]
    return mentioned.lower() == (own_username or "").lower()


@bot.message_handler(commands=["start"])
async def start_command(message: Message):
    username = await _get_bot_username()
    if not _start_targets_this_bot(message.text or "", username):
        return
    invoker_id = message.from_user.id if message.from_user else 0
    text = _start_text(message.from_user.first_name if message.from_user else "")
    keyboard = await _start_keyboard(invoker_id)
    sent_banner = await send_banner(message.chat.id, "start_banner", text, reply_markup=keyboard)
    if not sent_banner:
        await bot.reply_to(message, text, reply_markup=keyboard)


@bot.callback_query_handler(func=lambda c: c.data.startswith(f"{NAMESPACE}:") and c.data.split(":")[2:3] == ["show_help"])
async def start_show_help(call: CallbackQuery):
    invoker_id, _parts = await verify(call, NAMESPACE)
    if invoker_id is None:
        return
    await bot.answer_callback_query(call.id)
    await send_help(call.message.chat.id, invoker_id)