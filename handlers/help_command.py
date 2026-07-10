"""
handlers/help_command.py
---------------------------
راهنما — split into short sections behind inline buttons instead of one
long wall of text. If an image is registered under the key "help_banner"
(see "ثبت تصویر" in handlers/admin_commands.py), it's sent once as a photo
and stays exactly as-is; only the caption and keyboard change as the person
taps between sections (via editMessageCaption), so the image never
re-sends or changes.

SECURITY: every button here is invoker-locked (see utils/invoker_lock.py) -
only the person who opened THIS help message (via «راهنما», /start's
button, or the panel's «راهنما» button) can press its buttons. Anyone else
tapping gets a small alert instead of silently acting as them.

NOTE ON "/" COMMANDS: per project policy, this bot no longer registers any
slash ("/") commands - text triggers only. There is exactly one unavoidable
exception, handled in start_command.py, not here: Telegram itself always
sends the literal text "/start" when a person taps "Start" in a DM or a
deep link - that's a platform mechanic, not a user-typed command, so it
still has to be caught.

*** IMPORTANT: keep SECTIONS below in sync with what the bot actually
does whenever a feature changes. ***
"""

from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core import bot, db
from utils.invoker_lock import encode, verify
from utils.text import normalize_trigger

NAMESPACE = "help"

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
            "گروه‌ها همیشه دسترسی کامل دارد و بالاتر از همه است.\n"
            "• <b>مالک اصلی</b>: کسی که ربات را به یک گروه اضافه کرده. به‌طور خودکار "
            "ثبت می‌شود؛ دسترسی کامل و می‌تواند هرکسی (مالک ۲، ادمین، ویژه) را عزل کند.\n"
            "• <b>مالک ۲</b>: توسط مالک اصلی تعیین می‌شود؛ دسترسی کامل مثل ادمین، به‌علاوهٔ "
            "توانایی افزودن/عزل ادمین و ویژه - اما نمی‌تواند مالک ۲ دیگر یا مالک اصلی را عزل کند.\n"
            "• <b>ادمین گروه</b>: توسط مالک اصلی یا مالک ۲ تعیین می‌شود؛ دسترسی مدیریتی کامل، "
            "اما فقط می‌تواند اعضای ویژه را عزل کند.\n"
            "• <b>عضو ویژه (VIP)</b>: فقط در همان گروه از محدودیت‌های ضد اسپم معاف است.\n"
            "• <b>عضو عادی</b>: مشمول همهٔ محدودیت‌ها و قفل‌ها.\n\n"
            "ℹ️ هر سطح فقط می‌تواند کسی را عزل/بن/سکوت کند که رتبه‌اش پایین‌تر باشد - یعنی "
            "ادمین نمی‌تواند روی ادمین یا مالک ۲ دیگر این کار را انجام دهد، و مالک ۲ نمی‌تواند "
            "روی مالک ۲ دیگر یا مالک اصلی.\n"
            "ادمین بودن در خودِ تلگرام به‌تنهایی دسترسی به دستورات ربات نمی‌دهد.\n"
            "اگر عضو عادی دستوری مخصوص ادمین‌ها را اجرا کند، ربات دلیلش را توضیح می‌دهد، "
            "نه اینکه ساکت بماند."
        ),
    },
    "panel": {
        "label": "🛠 پنل تنظیمات",
        "text": (
            "🛠 <b>پنل تنظیمات («پنل»)</b>\n\n"
            "یک منوی دکمه‌ای برای مدیریت گروه بدون حفظ‌کردن دستورات متنی:\n"
            "• <b>قفل‌ها</b> → روشن/خاموش کردن حذف خودکار لینک، فوروارد، فایل، استیکر، "
            "ویس، گیف، مخاطب، نظرسنجی، هشتگ و منشن برای اعضای عادی\n"
            "• <b>لیست‌ها</b> → مالک/ادمین‌ها، ویژه‌ها، کلمات فیلتر، اخطارها\n"
            "• <b>تنظیمات پیشرفته</b> → وضعیت اسپم، خوش‌آمدگویی و بدرود\n\n"
            "⚠️ فقط ادمین‌های ربات می‌توانند این پنل را باز کنند، و فقط همان کسی که پنل را باز "
            "کرده می‌تواند دکمه‌های همان پیام را بزند."
        ),
    },
    "commands": {
        "label": "👮‍♂️ دستورات مدیریتی",
        "text": (
            "👮‍♂️ <b>دستورات مدیریتی</b>\n"
            "(روی پیام کاربر مورد نظر ریپلای کنید. برای کپی کردن یک دستور، فقط کافیست "
            "روی متنش بزنید)\n\n"
            "• <code>کیک</code> / <code>بن</code> / <code>اخراج</code> / <code>سیک</code> → "
            "اخراج و بن (یا <code>بن @username</code>)\n"
            "• <code>رفع بن</code> / <code>آنبن</code> → خروج از بن (یا <code>رفع بن @username</code>)\n"
            "• <code>میوت</code> / <code>سکوت</code> → سکوت تا زمانی که «رفع سکوت» شود\n"
            "• <code>میوت 10</code> → سکوت فقط برای ۱۰ دقیقه (عدد دلخواه)\n"
            "• <code>رفع سکوت</code> / <code>آنمیوت</code> → برداشتن سکوت\n"
            "• <code>تنظیم ویژه</code> / <code>لغو ویژه</code> → عضو ویژه کردن/برداشتن\n"
            "• <code>اخطار</code> (ریپلای) یا <code>اخطار @username</code> → اخطار؛ پس از ۳ اخطار بن خودکار\n"
            "• <code>حذف اخطار</code> یا <code>لیست اخطار</code>\n"
            "• <code>افزودن کلمه فیلتر [کلمه]</code> / <code>حذف کلمه فیلتر [کلمه]</code> / "
            "<code>لیست کلمات فیلتر</code> → پیام‌های عادی حاوی این کلمات خودکار حذف می‌شوند\n"
            "• <code>پینگ</code> → بررسی زنده بودن ربات\n\n"
            "⚠️ توجه: این دستورات فقط با متن دقیقاً همان کلمه (یا فرمت‌های ثابت بالا) کار "
            "می‌کنند - مثلاً نوشتن «بن شدم» در یک جمله عادی هیچ اقدامی انجام نمی‌دهد.\n\n"
            "وقتی کسی ادمین می‌شود، ربات لیست کامل قابلیت‌هایی که برایش باز شده را برایش توضیح می‌دهد."
        ),
    },
    "ownership": {
        "label": "🛠 مالکیت و ادمین‌ها",
        "text": (
            "🛠 <b>مالکیت و ادمین‌های گروه</b>\n\n"
            "• <code>مالک این گروه</code> → نمایش مالک فعلی\n"
            "• <code>ادعای مالکیت</code> → برای گروه‌هایی که مالک ثبت‌شده ندارند\n"
            "• <code>تنظیم مالک</code> (ریپلای) → واگذاری مالکیت اصلی گروه به شخص دیگر "
            "(مالک قبلی خودکار به عادی برمی‌گردد) - مالک ربات/ادمین کل هر گروهی، یا مالک اصلی "
            "خودِ همین گروه برای واگذاری مالکیت خودش\n"
            "• <code>افزودن مالک دو</code> / <code>حذف مالک دو</code> (ریپلای، فقط مالک اصلی)\n"
            "• <code>افزودن ادمین گروه</code> / <code>حذف ادمین گروه</code> (ریپلای، مالک اصلی یا مالک ۲)\n"
            "• <code>لیست ادمین های گروه</code> → مالک اصلی، مالک‌های ۲ و ادمین‌ها\n"
            "• <code>پیکربندی</code> (فقط مالک گروه) → همهٔ ادمین‌های واقعی تلگرام این گروه را "
            "به‌عنوان ادمین ربات اضافه می‌کند\n"
            "• <code>پاک سازی</code> (فقط مالک گروه) → همهٔ ادمین‌های ربات را از این گروه حذف "
            "می‌کند (مالک گروه دست‌نخورده می‌ماند)\n\n"
            "🔓 <b>ادمین کل (سراسری، نه مخصوص یک گروه):</b>\n"
            "• <code>افزودن ادمین کل</code> (ریپلای، فقط مالک ربات) → دسترسی کامل در «همهٔ» "
            "گروه‌ها، دقیقاً مثل مالک ربات\n"
            "• <code>حذف ادمین کل</code> (مالک ربات، یا همان کسی که این فرد را ارتقا داده)\n"
            "• <code>لیست ادمین های کل</code> (فقط مالک ربات)"
        ),
    },
    "danger": {
        "label": "🗑 حذف پیام‌ها",
        "text": (
            "🗑 <b>حذف پیام‌ها</b> (فقط ادمین‌های ربات)\n\n"
            "• <code>حذف [عدد]</code> → حذف همان تعداد پیام اخیر گروه (مثلاً <code>حذف 20</code>)\n"
            "• <code>حذف کل</code> → حذف تمام پیام‌های ثبت‌شدهٔ گروه (قبل از اجرا یک تاییدیه "
            "از شما گرفته می‌شود)\n\n"
            "⚠️ تلگرام فقط اجازهٔ حذف پیام‌های حداکثر ۴۸ ساعت اخیر را می‌دهد؛ پیام‌های "
            "قدیمی‌تر توسط خودِ تلگرام قابل حذف نیستند، حتی برای ادمین‌ها."
        ),
    },
    "welcome": {
        "label": "👋 خوش‌آمدگویی و بدرود",
        "text": (
            "👋 <b>خوش‌آمدگویی و بدرود</b> (به‌طور پیش‌فرض فعال است)\n\n"
            "• <code>تنظیم خوش آمدگویی [متن]</code> → تغییر متن (جای‌گذاری‌ها: "
            "<code>{نام}</code>, <code>{منشن}</code>, <code>{گروه}</code>)\n"
            "• روی یک عکس/ویدیو/ویس ریپلای کرده و همین دستور را بفرستید تا آن رسانه هم بخشی از "
            "پیام خوش‌آمدگویی شود؛ با <code>حذف رسانه خوش آمدگویی</code> حذفش کنید\n"
            "• <code>روشن کردن خوش آمدگویی</code> / <code>خاموش کردن خوش آمدگویی</code>\n"
            "• <code>تنظیم بدرود [متن]</code> → تغییر متن بدرود (همین جای‌گذاری‌ها و قابلیت رسانه)\n"
            "• <code>روشن کردن بدرود</code> / <code>خاموش کردن بدرود</code>"
        ),
    },
    "spam": {
        "label": "🛡 ضد اسپم و قفل‌ها",
        "text": (
            "🛡 <b>ضد اسپم</b> (ساده - فقط یک عدد در هر تنظیم؛ واحد زمانی ثابت ۳ ثانیه است)\n\n"
            "• <code>تنظیم تعداد پیام مجاز [عدد]</code> → مثلاً بیشتر از ۶ پیام در ۳ ثانیه = اسپم\n"
            "• <code>تنظیم مدت سکوت اسپم [عدد به دقیقه]</code> → مدت سکوت خودکار اسپم‌کننده\n"
            "• <code>تنظیمات اسپم</code> → نمایش تنظیمات فعلی\n\n"
            "هر گروه تنظیمات مستقل خودش را دارد.\n\n"
            "قفل‌های محتوا (پیش‌فرض: لینک و فوروارد روشن، بقیه خاموش) از پنل قابل تغییرند - "
            "بخش «پنل تنظیمات» را ببینید."
        ),
    },
    "captcha": {
        "label": "🤖 کپچای عضویت",
        "text": (
            "🤖 <b>کپچای عضویت</b> (پیش‌فرض: خاموش)\n\n"
            "مخصوص گروه‌هایی که «تایید درخواست عضویت» تلگرام را فعال کرده‌اند. وقتی روشن باشد، "
            "ربات برای هرکسی که درخواست عضویت می‌دهد یک سؤال ریاضی ساده در پیوی می‌فرستد؛ اگر ظرف "
            "۱ دقیقه درست جواب دهد درخواستش خودکار تایید می‌شود، وگرنه رد می‌شود.\n\n"
            "• <code>روشن کردن کپچا</code>\n"
            "• <code>خاموش کردن کپچا</code>"
        ),
    },
    "stats": {
        "label": "📊 آمار گروه",
        "text": (
            "📊 <b>آمار گروه</b>\n\n"
            "• <code>آمار روزانه</code> → فعالیت ۲۴ ساعت گذشته، به‌همراه لیست اعضای تازه‌وارد "
            "و ۳ نفر برتر در افزودن عضو\n"
            "• <code>آمار کل</code> → فعالیت کل از ابتدا\n\n"
            "نام هر عضو در این آمار قابل کلیک است و پروفایلش را باز می‌کند."
        ),
    },
    "profile": {
        "label": "👤 پروفایل",
        "text": (
            "👤 <b>پروفایل کاربر</b> (فقط ادمین‌های ربات)\n\n"
            "روی پیام کسی ریپلای کنید و بنویسید <code>پروفایل</code>، <code>ایدی</code> یا "
            "<code>id</code> تا نام، آیدی عددی، عکس، نقش او در این گروه و آمار پیام‌هایش را ببینید."
        ),
    },
}


def _main_keyboard(invoker_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = [
        InlineKeyboardButton(s["label"], callback_data=encode(NAMESPACE, invoker_id, "section", key))
        for key, s in SECTIONS.items()
    ]
    kb.add(*buttons)
    return kb


def _section_keyboard(invoker_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("بازگشت", callback_data=encode(NAMESPACE, invoker_id, "main"), style="danger"))
    return kb


async def send_help(chat_id: int, invoker_id: int, reply_to_message_id: int = None):
    """Shared entry point - used by «راهنما», /start's help button, and the panel's help button."""
    banner = await db.get_asset("help_banner")
    keyboard = _main_keyboard(invoker_id)
    if banner:
        await bot.send_photo(
            chat_id, banner, caption=OVERVIEW_TEXT, reply_markup=keyboard,
            reply_to_message_id=reply_to_message_id,
        )
    else:
        await bot.send_message(
            chat_id, OVERVIEW_TEXT, reply_markup=keyboard,
            reply_to_message_id=reply_to_message_id,
        )


@bot.message_handler(func=lambda m: normalize_trigger(m.text or "").strip() == "راهنما")
async def help_command_fa(message: Message):
    await send_help(message.chat.id, message.from_user.id, reply_to_message_id=message.message_id)


@bot.callback_query_handler(func=lambda c: c.data.startswith(f"{NAMESPACE}:") and c.data.split(":")[2:3] == ["main"])
async def help_back_to_main(call: CallbackQuery):
    invoker_id, _parts = await verify(call, NAMESPACE)
    if invoker_id is None:
        return
    await bot.answer_callback_query(call.id)
    kb = _main_keyboard(invoker_id)
    if call.message.content_type == "photo":
        await bot.edit_message_caption(
            caption=OVERVIEW_TEXT, chat_id=call.message.chat.id,
            message_id=call.message.message_id, reply_markup=kb,
        )
    else:
        await bot.edit_message_text(
            OVERVIEW_TEXT, chat_id=call.message.chat.id,
            message_id=call.message.message_id, reply_markup=kb,
        )


@bot.callback_query_handler(
    func=lambda c: c.data.startswith(f"{NAMESPACE}:")
    and len(c.data.split(":")) >= 4
    and c.data.split(":")[2] == "section"
    and c.data.split(":")[3] in SECTIONS
)
async def help_show_section(call: CallbackQuery):
    invoker_id, parts = await verify(call, NAMESPACE)
    if invoker_id is None:
        return
    key = parts[1]
    section = SECTIONS[key]
    await bot.answer_callback_query(call.id)
    kb = _section_keyboard(invoker_id)
    if call.message.content_type == "photo":
        await bot.edit_message_caption(
            caption=section["text"], chat_id=call.message.chat.id,
            message_id=call.message.message_id, reply_markup=kb,
        )
    else:
        await bot.edit_message_text(
            section["text"], chat_id=call.message.chat.id,
            message_id=call.message.message_id, reply_markup=kb,
        )