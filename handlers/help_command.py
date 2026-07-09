"""
handlers/help_command.py
---------------------------
/help و راهنما — split into short sections behind inline buttons instead of
one long wall of text. If an image is registered under the key
"help_banner" (see "ثبت تصویر" in handlers/admin_commands.py), it's sent
once as a photo and stays exactly as-is; only the caption and keyboard
change as the person taps between sections (via editMessageCaption), so
the image never re-sends or changes.

*** IMPORTANT: keep SECTIONS below in sync with what the bot actually
does whenever a feature changes. ***
"""

from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core import bot, db
from utils.text import normalize_fa

OVERVIEW_TEXT = (
    "🤖 <b>راهنمای ربات مدیریت گروه</b>\n\n"
    "برای دیدن هر بخش، روی دکمه‌های زیر بزنید 👇"
)

SECTIONS = {
    "access": {
        "label": "👑 سطوح دسترسی",
        "text": (
            "👑 <b>سطوح دسترسی</b> (هر گروه، مستقل از گروه‌های دیگر)\n\n"
            "• <b>مالک ربات (Global Owner)</b>: در تنظیمات سرور ربات مشخص می‌شود؛ در همهٔ "
            "گروه‌ها همیشه دسترسی کامل دارد.\n"
            "• <b>مالک گروه</b>: کسی که ربات را به یک گروه اضافه کرده. به‌طور خودکار "
            "ثبت می‌شود و فقط در همان گروه دسترسی کامل دارد.\n"
            "• <b>ادمین گروه</b>: کسی که مالک همان گروه او را تعیین کرده. فقط در همان "
            "گروه دسترسی مدیریتی کامل دارد.\n"
            "• <b>عضو ویژه (VIP)</b>: فقط در همان گروه از محدودیت‌های ضد اسپم معاف است.\n"
            "• <b>عضو عادی</b>: مشمول همهٔ محدودیت‌ها.\n\n"
            "ℹ️ ادمین بودن در خودِ تلگرام به‌تنهایی دسترسی به دستورات ربات نمی‌دهد."
        ),
    },
    "commands": {
        "label": "👮‍♂️ دستورات مدیریتی",
        "text": (
            "👮‍♂️ <b>دستورات مدیریتی</b>\n"
            "(روی پیام کاربر مورد نظر ریپلای کنید، یا @یوزرنیم را در دستور بنویسید)\n\n"
            "• <b>کیک / بن / اخراج</b> → اخراج و بن (تا «رفع بن» نشود برنمی‌گردد)\n"
            "• <b>رفع بن</b> یا <b>آنبن</b> → خروج از بن\n"
            "• <b>میوت / سکوت</b> → سکوت تا زمانی که «رفع سکوت» شود\n"
            "• <b>میوت 10</b> → سکوت فقط برای ۱۰ دقیقه (عدد دلخواه)\n"
            "• <b>رفع سکوت</b> یا <b>آنمیوت</b> → برداشتن سکوت\n"
            "• <b>تنظیم ویژه</b> / <b>لغو ویژه</b> → عضو ویژه کردن/برداشتن"
        ),
    },
    "ownership": {
        "label": "🛠 مالکیت و ادمین‌ها",
        "text": (
            "🛠 <b>مالکیت و ادمین‌های گروه</b>\n\n"
            "• <b>مالک این گروه</b> → نمایش مالک فعلی\n"
            "• <b>ادعای مالکیت</b> → برای گروه‌هایی که مالک ثبت‌شده ندارند\n"
            "• <b>افزودن ادمین گروه</b> (ریپلای، فقط مالک گروه)\n"
            "• <b>حذف ادمین گروه</b> (ریپلای، فقط مالک گروه)\n"
            "• <b>لیست ادمین های گروه</b>"
        ),
    },
    "spam": {
        "label": "🛡 تنظیم اسپم",
        "text": (
            "🛡 <b>تنظیم آستانهٔ اسپم</b> (داخل خود گروه، بدون نیاز به تنظیمات سرور)\n\n"
            "• <code>تنظیم اسپم [حداکثر پیام] [بازه به ثانیه] [مدت سکوت به دقیقه]</code>\n"
            "  مثال: <code>تنظیم اسپم 6 8 30</code>\n"
            "• <b>تنظیمات اسپم</b> → نمایش تنظیمات فعلی\n\n"
            "هر گروه تنظیمات مستقل خودش را دارد.\n\n"
            "قوانین خودکار برای اعضای عادی:\n"
            "• لینک یا فوروارد از کانال → حذف فوری پیام\n"
            "• پیام زیاد در زمان کوتاه → سکوت خودکار"
        ),
    },
    "stats": {
        "label": "📊 آمار گروه",
        "text": (
            "📊 <b>آمار گروه</b>\n\n"
            "• <b>آمار روزانه</b> → فعالیت ۲۴ ساعت گذشته\n"
            "• <b>آمار کل</b> → فعالیت کل از ابتدا"
        ),
    },
    "profile": {
        "label": "👤 پروفایل",
        "text": (
            "👤 <b>پروفایل کاربر</b>\n\n"
            "روی پیام کسی ریپلای کنید و بنویسید <b>پروفایل</b> (یا /profile) تا نام، عکس، "
            "نقش او در این گروه و آمار پیام‌هایش را ببینید."
        ),
    },
}


def _main_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = [InlineKeyboardButton(s["label"], callback_data=f"help:{key}") for key, s in SECTIONS.items()]
    kb.add(*buttons)
    return kb


def _section_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data="help:main"))
    return kb


async def send_help(chat_id: int, reply_to_message_id: int = None):
    """Shared entry point - used by /help, راهنما, and /start's help button."""
    banner = await db.get_asset("help_banner")
    if banner:
        await bot.send_photo(
            chat_id, banner, caption=OVERVIEW_TEXT, reply_markup=_main_keyboard(),
            reply_to_message_id=reply_to_message_id,
        )
    else:
        await bot.send_message(
            chat_id, OVERVIEW_TEXT, reply_markup=_main_keyboard(),
            reply_to_message_id=reply_to_message_id,
        )


@bot.message_handler(commands=["help"])
async def help_command(message: Message):
    await send_help(message.chat.id, reply_to_message_id=message.message_id)


@bot.message_handler(func=lambda m: normalize_fa(m.text or "").strip() == "راهنما")
async def help_command_fa(message: Message):
    await send_help(message.chat.id, reply_to_message_id=message.message_id)


@bot.callback_query_handler(func=lambda c: c.data == "help:main")
async def help_back_to_main(call: CallbackQuery):
    await bot.answer_callback_query(call.id)
    if call.message.content_type == "photo":
        await bot.edit_message_caption(
            caption=OVERVIEW_TEXT, chat_id=call.message.chat.id,
            message_id=call.message.message_id, reply_markup=_main_keyboard(),
        )
    else:
        await bot.edit_message_text(
            OVERVIEW_TEXT, chat_id=call.message.chat.id,
            message_id=call.message.message_id, reply_markup=_main_keyboard(),
        )


@bot.callback_query_handler(func=lambda c: c.data.startswith("help:") and c.data.split(":", 1)[1] in SECTIONS)
async def help_show_section(call: CallbackQuery):
    key = call.data.split(":", 1)[1]
    section = SECTIONS[key]
    await bot.answer_callback_query(call.id)
    if call.message.content_type == "photo":
        await bot.edit_message_caption(
            caption=section["text"], chat_id=call.message.chat.id,
            message_id=call.message.message_id, reply_markup=_section_keyboard(),
        )
    else:
        await bot.edit_message_text(
            section["text"], chat_id=call.message.chat.id,
            message_id=call.message.message_id, reply_markup=_section_keyboard(),
        )