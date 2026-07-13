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

from telebot.formatting import hcite
from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core import bot
from utils.banners import is_banner_message, send_banner
from utils.invoker_lock import encode, verify
from utils.panel_auth import encode as panel_encode
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
            "👑 <b>سطوح دسترسی</b> (هر گروه، مستقل از بقیه)\n\n"
            "• <b>مالک ربات</b>: در تنظیمات سرور مشخص می‌شود؛ در همهٔ گروه‌ها دسترسی کامل و بالاتر از همه.\n"
            "• <b>مالک اصلی</b>: کسی که ربات را اضافه کرده؛ خودکار ثبت می‌شود، دسترسی کامل، می‌تواند همه را عزل کند.\n"
            "• <b>مالک ۲</b>: توسط مالک اصلی تعیین می‌شود؛ مثل ادمین به‌علاوهٔ افزودن/عزل ادمین و ویژه - "
            "اما نمی‌تواند مالک ۲ دیگر یا مالک اصلی را عزل کند.\n"
            "• <b>ادمین گروه</b>: توسط مالک اصلی/۲ تعیین می‌شود؛ دسترسی کامل، فقط ویژه‌ها را می‌تواند عزل کند.\n"
            "• <b>عضو ویژه (VIP)</b>: فقط از محدودیت‌های ضد اسپم معاف است.\n"
            "• <b>عضو عادی</b>: مشمول همهٔ محدودیت‌ها و قفل‌ها.\n\n"
            + hcite(
                "هر سطح فقط می‌تواند کسی با رتبهٔ پایین‌تر را عزل/بن/سکوت کند. ادمین بودن در خودِ تلگرام "
                "به‌تنهایی دسترسی به دستورات ربات نمی‌دهد؛ اگر عضو عادی دستور مخصوص ادمین‌ها بزند، ربات "
                "دلیلش را توضیح می‌دهد.",
                escape=False,
            )
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
            "👮‍♂️ <b>دستورات مدیریتی</b> (روی پیام کاربر ریپلای کنید؛ برای کپی کردن یک دستور، روی متنش بزنید)\n\n"
            "• <code>کیک</code> / <code>بن</code> / <code>اخراج</code> / <code>سیک</code> → اخراج و بن "
            "(یا <code>بن @username</code>)\n"
            "• <code>رفع بن</code> / <code>آنبن</code> → خروج از بن\n"
            "• <code>میوت</code> / <code>سکوت</code> → سکوت تا «رفع سکوت»\n"
            "• <code>میوت 10</code> → سکوت فقط ۱۰ دقیقه (عدد دلخواه)\n"
            "• <code>رفع سکوت</code> / <code>آنمیوت</code>\n"
            "• <code>تنظیم ویژه</code> / <code>لغو ویژه</code>\n"
            "• <code>اخطار</code> (ریپلای/@username) → پس از ۳ اخطار بن خودکار\n"
            "• <code>حذف اخطار</code> / <code>لیست اخطار</code>\n"
            "• <code>افزودن کلمه فیلتر [کلمه]</code> / <code>حذف کلمه فیلتر [کلمه]</code> / "
            "<code>لیست کلمات فیلتر</code> → حذف خودکار پیام‌های حاوی این کلمات (جدا از «قفل فحش»)\n"
            "• <code>پینگ</code> → بررسی زنده بودن ربات\n\n"
            + hcite(
                "این دستورات فقط با متن دقیقاً همان کلمه کار می‌کنند - «بن شدم» در یک جمله عادی هیچ "
                "اقدامی انجام نمی‌دهد. وقتی کسی ادمین می‌شود، ربات لیست کامل قابلیت‌هایش را برایش توضیح می‌دهد.",
                escape=False,
            )
        ),
    },
    "ownership": {
        "label": "🛠 مالکیت و ادمین‌ها",
        "text": (
            "🛠 <b>مالکیت و ادمین‌های گروه</b>\n\n"
            "• <code>مالک این گروه</code> → نمایش مالک فعلی\n"
            "• <code>ادعای مالکیت</code> → برای گروه‌های بدون مالک ثبت‌شده\n"
            "• <code>تنظیم مالک</code> (ریپلای) → واگذاری مالکیت اصلی (مالک قبلی خودکار عادی می‌شود) - "
            "توسط مالک ربات/ادمین کل، یا مالک اصلی برای واگذاری مالکیت خودش\n"
            "• <code>افزودن مالک دو</code> / <code>حذف مالک دو</code> (ریپلای، فقط مالک اصلی)\n"
            "• <code>افزودن ادمین گروه</code> / <code>حذف ادمین گروه</code> (ریپلای، مالک اصلی یا مالک ۲)\n"
            "• <code>لیست ادمین های گروه</code> → مالک اصلی، مالک‌های ۲ و ادمین‌ها\n"
            "• <code>پیکربندی</code> (فقط مالک گروه) → همهٔ ادمین‌های واقعی تلگرام را ادمین ربات می‌کند\n"
            "• <code>پاک سازی</code> (فقط مالک گروه) → همهٔ ادمین‌های ربات را حذف می‌کند (مالک دست‌نخورده می‌ماند)\n\n"
            "🔓 <b>ادمین کل (سراسری):</b>\n"
            "• <code>افزودن ادمین کل</code> (ریپلای، فقط مالک ربات) → دسترسی کامل در همهٔ گروه‌ها\n"
            "• <code>حذف ادمین کل</code> (مالک ربات، یا همان کسی که ارتقا داده)\n"
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
            "• <code>روشن کردن بدرود</code> / <code>خاموش کردن بدرود</code>\n\n"
            "پیام سیستمی خودِ تلگرام («فلانی به گروه اضافه شد»/«فلانی گروه را ترک کرد») جدا از این‌هاست و "
            "به‌طور پیش‌فرض حذف می‌شود (شامل بن/کیک هم می‌شود، چون تلگرام برای آن پیام سیستمی جدایی ندارد):\n"
            "• <code>روشن کردن حذف پیام سیستمی</code> / <code>خاموش کردن حذف پیام سیستمی</code>"
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
            "🔒 <b>قفل‌های محتوا</b> (پیش‌فرض: لینک و فوروارد روشن، بقیه خاموش): با دکمهٔ زیر همین‌جا "
            "روشن/خاموششان کنید - سبز یعنی روشن، قرمز یعنی خاموش.\n\n"
            "🔒 <b>قفل فحش</b> (پیش‌فرض: خاموش، جدا از قفل‌های بالا): از همون دکمه هم روشن/خاموش می‌شود؛ "
            "از یک دیتاست عمومی فحش فارسی استفاده می‌کند که ممکن است گاهی کلمات بی‌گناه را هم بگیرد، برای "
            "همین می‌توانید برای این گروه سفارشی‌اش کنید:\n"
            "• <code>افزودن فحش [کلمه]</code> → این کلمه را هم فحش حساب کن\n"
            "• <code>حذف فحش [کلمه]</code> → این کلمه دیگر فحش نیست\n"
            "• <code>لیست فحش</code> → نمایش سفارشی‌سازی‌های همین گروه\n\n"
            + hcite("توجه: «قفل فحش» کاملاً از «کلمه فیلتر» جداست - لیست کلمه با هم مشترک نیست.", escape=False)
        ),
    },
    "captcha": {
        "label": "🤖 کپچای عضویت",
        "text": (
            "🤖 <b>کپچای عضویت</b> (پیش‌فرض: خاموش)\n\n"
            "مخصوص گروه‌هایی که «تایید درخواست عضویت» تلگرام را فعال کرده‌اند. وقتی روشن باشد، "
            "ربات برای هرکسی که درخواست عضویت می‌دهد یک سؤال ریاضی ساده در پیوی می‌فرستد؛ اگر ظرف "
            "۱ دقیقه درست جواب دهد درخواستش خودکار تایید می‌شود، وگرنه رد می‌شود.\n\n"
            "با دکمهٔ زیر همین‌جا روشن/خاموشش کنید - سبز یعنی روشن، قرمز یعنی خاموش."
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


def _section_keyboard(invoker_id: int, key: str = None) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    extra = SECTION_ACTION_BUTTONS.get(key)
    if extra:
        label, panel_parts = extra
        kb.add(InlineKeyboardButton(label, callback_data=panel_encode(invoker_id, *panel_parts)))
    kb.add(InlineKeyboardButton("بازگشت", callback_data=encode(NAMESPACE, invoker_id, "main"), style="danger"))
    return kb


# Sections that link straight into a live /پنل screen instead of just
# describing the feature in text - tapping these re-verifies admin status
# (see utils/panel_auth.verify_panel_callback) exactly like opening /پنل
# directly would, so a non-admin tapping it just gets the same "دسترسی
# مدیریتی ندارید" alert rather than actually toggling anything.
SECTION_ACTION_BUTTONS = {
    "spam": ("🔒 روشن/خاموش کردن قفل‌ها", ("locks",)),
    "captcha": ("🤖 روشن/خاموش کردن کپچا", ("settings",)),
}


async def send_help(chat_id: int, invoker_id: int, reply_to_message_id: int = None):
    """Shared entry point - used by «راهنما», /start's help button, and the panel's help button."""
    keyboard = _main_keyboard(invoker_id)
    sent_banner = await send_banner(chat_id, "help_banner", OVERVIEW_TEXT, reply_markup=keyboard, reply_to_message_id=reply_to_message_id)
    if not sent_banner:
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
    if is_banner_message(call.message.content_type):
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
    kb = _section_keyboard(invoker_id, key)
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    if is_banner_message(call.message.content_type):
        try:
            await bot.edit_message_caption(caption=section["text"], chat_id=chat_id, message_id=msg_id, reply_markup=kb)
        except Exception:
            # A photo/video/GIF caption is capped at 1024 characters by
            # Telegram (a plain message's text can go up to 4096), so a
            # longer section here would otherwise leave the button looking
            # dead - fall back to a normal text message instead of failing
            # silently.
            await bot.send_message(chat_id, section["text"], reply_markup=kb, reply_to_message_id=msg_id)
    else:
        await bot.edit_message_text(section["text"], chat_id=chat_id, message_id=msg_id, reply_markup=kb)