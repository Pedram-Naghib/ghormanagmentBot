"""
handlers/panel_command.py
----------------------------
پنل — the inline-keyboard admin panel (main -> قفل‌ها / لیست‌ها /
تنظیمات پیشرفته), replacing a growing pile of separate text commands with
one navigable menu, the way DIGI ANTI's panel works.

If an image is registered under the key "panel_banner" (see "ثبت تصویر" in
handlers/admin_commands.py), it's sent once as a photo and stays exactly
as-is; only the caption and keyboard change as the admin taps between
sections (via editMessageCaption), so the image never re-sends or changes -
same pattern as /start and «راهنما».

SECURITY: every button here is invoker-locked (see utils/panel_auth.py) -
only the admin who opened THIS panel message can press its buttons. Anyone
else tapping gets a small alert instead of silently acting as them.

Adding a new lock type needs ZERO changes here - see utils/locks.py.
"""

from telebot.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core import bot, db
from handlers.help_command import send_help
from utils.locks import LOCKS, is_lock_enabled
from utils import chat_config_cache
from utils.panel_auth import encode, verify_panel_callback
from utils.permissions import is_authorized_admin
from utils.text import normalize_trigger

PANEL_TRIGGERS = {"پنل"}

MAIN_TEXT = "🛠 <b>پنل تنظیمات گروه</b>\n\nیک بخش را انتخاب کنید:"


def _main_keyboard(invoker_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🔒 قفل‌ها", callback_data=encode(invoker_id, "locks")),
        InlineKeyboardButton("📋 لیست‌ها", callback_data=encode(invoker_id, "lists")),
    )
    kb.add(InlineKeyboardButton("⚙️ تنظیمات پیشرفته", callback_data=encode(invoker_id, "settings")))
    kb.add(InlineKeyboardButton("📖 راهنما", callback_data=encode(invoker_id, "help")))
    kb.add(InlineKeyboardButton("❌ بستن", callback_data=encode(invoker_id, "close"), style="danger"))
    return kb


async def _locks_text_and_keyboard(chat_id: int, invoker_id: int):
    locks_row = await db.get_chat_locks(chat_id)
    kb = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for lock in LOCKS:
        enabled = is_lock_enabled(locks_row, lock.key)
        style = "success" if enabled else None
        buttons.append(
            InlineKeyboardButton(
                f"{lock.label}", callback_data=encode(invoker_id, "locks", "toggle", lock.key), style=style
            )
        )
    kb.add(*buttons)
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=encode(invoker_id, "main"), style="danger"))
    text = "🔒 <b>قفل‌ها</b>\n\nروی هرکدام بزنید تا روشن/خاموش شود (فقط برای اعضای عادی اعمال می‌شود):"
    return text, kb


def _lists_menu_keyboard(invoker_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("👑 مالک و ادمین‌ها", callback_data=encode(invoker_id, "lists", "admins")),
        InlineKeyboardButton("⭐️ ویژه‌ها", callback_data=encode(invoker_id, "lists", "vips")),
    )
    kb.add(
        InlineKeyboardButton("🔒 کلمات فیلتر", callback_data=encode(invoker_id, "lists", "filters")),
        InlineKeyboardButton("⚠️ اخطارها", callback_data=encode(invoker_id, "lists", "warnings")),
    )
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=encode(invoker_id, "main"), style="danger"))
    return kb


async def _lists_admins_text(chat_id: int) -> str:
    owner_id = await db.get_chat_owner(chat_id)
    admin_ids = await db.list_users_by_role(chat_id, "admin")
    lines = ["👑 <b>مالک و ادمین‌های این گروه</b>\n"]
    if owner_id:
        lines.append(f"👑 مالک: {await db.get_user_display_name(chat_id, owner_id)}")
    else:
        lines.append("مالکی برای این گروه ثبت نشده.")
    if admin_ids:
        lines.append("\n👮‍♂️ ادمین‌ها:")
        for uid in admin_ids:
            lines.append(f"• {await db.get_user_display_name(chat_id, uid)}")
    else:
        lines.append("\nادمینی (جدا از مالک) تعیین نشده.")
    return "\n".join(lines)


async def _lists_vips_text(chat_id: int) -> str:
    vip_ids = await db.list_users_by_role(chat_id, "vip")
    if not vip_ids:
        return "⭐️ <b>اعضای ویژه</b>\n\nعضو ویژه‌ای در این گروه ثبت نشده."
    lines = ["⭐️ <b>اعضای ویژهٔ این گروه</b>\n"]
    for uid in vip_ids:
        lines.append(f"• {await db.get_user_display_name(chat_id, uid)}")
    return "\n".join(lines)


async def _lists_filters_text(chat_id: int) -> str:
    words = await db.list_filtered_words(chat_id)
    if not words:
        return "🔒 <b>کلمات فیلتر</b>\n\nهیچ کلمه‌ای فیلتر نشده.\n\nبرای افزودن بنویسید: «افزودن کلمه فیلتر [کلمه]»"
    lines = ["🔒 <b>کلمات فیلتر این گروه</b>\n"] + [f"• {w}" for w in words]
    return "\n".join(lines)


async def _lists_warnings_text(chat_id: int) -> str:
    from handlers.admin_commands import WARN_LIMIT

    warned = await db.list_warned_users(chat_id)
    if not warned:
        return "⚠️ <b>اخطارها</b>\n\nهیچ کاربری اخطار فعالی ندارد."
    lines = ["⚠️ <b>اخطارهای این گروه</b>\n"]
    for uid, count in warned:
        lines.append(f"• {await db.get_user_display_name(chat_id, uid)}: {count} از {WARN_LIMIT}")
    return "\n".join(lines)


async def _settings_text_and_keyboard(chat_id: int, invoker_id: int):
    s = await db.get_chat_settings(chat_id)
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton(
            f"{'✅' if s['welcome_enabled'] else '❌'} خوش‌آمدگویی",
            callback_data=encode(invoker_id, "settings", "toggle", "welcome"),
        ),
        InlineKeyboardButton(
            f"{'✅' if s['goodbye_enabled'] else '❌'} بدرود",
            callback_data=encode(invoker_id, "settings", "toggle", "goodbye"),
        ),
    )
    kb.add(
        InlineKeyboardButton(
            f"{'✅' if s['join_captcha_enabled'] else '❌'} کپچای عضویت",
            callback_data=encode(invoker_id, "settings", "toggle", "captcha"),
        )
    )
    kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=encode(invoker_id, "main"), style="danger"))
    text = (
        "⚙️ <b>تنظیمات پیشرفته</b>\n\n"
        f"سقف پیام مجاز (ضد اسپم): {s['spam_message_limit']} پیام در ۳ ثانیه\n"
        f"مدت سکوت خودکار: {s['spam_mute_minutes']} دقیقه\n"
        "(برای تغییر بنویسید: «تنظیم تعداد پیام مجاز [عدد]» یا «تنظیم مدت سکوت اسپم [عدد]»)\n\n"
        "برای تغییر متن خوش‌آمدگویی/بدرود بنویسید:\n"
        "«تنظیم خوش آمدگویی [متن]» یا «تنظیم بدرود [متن]»\n"
        "(می‌توانید روی یک عکس/ویدیو/ویس ریپلای کرده و همین دستور را بفرستید تا آن رسانه هم پیام خوش‌آمدگویی شود)\n\n"
        "کپچای عضویت: اگر گروه شما «تایید درخواست عضویت» فعال باشد، با روشن کردن این گزینه، ربات "
        "برای هرکسی که درخواست عضویت می‌دهد یک سؤال ساده در پیوی می‌فرستد؛ اگر ظرف ۱ دقیقه درست جواب "
        "ندهد، درخواستش خودکار رد می‌شود."
    )
    return text, kb


async def _render_main(message: Message, invoker_id: int, edit: bool):
    kb = _main_keyboard(invoker_id)
    if edit:
        await _edit_call_message(message.chat.id, message.message_id, message.content_type, MAIN_TEXT, kb)
    else:
        banner = await db.get_asset("panel_banner")
        if banner:
            await bot.send_photo(message.chat.id, banner, caption=MAIN_TEXT, reply_markup=kb, reply_to_message_id=message.message_id)
        else:
            await bot.reply_to(message, MAIN_TEXT, reply_markup=kb)


async def _edit_call_message(chat_id: int, message_id: int, content_type: str, text: str, kb: InlineKeyboardMarkup):
    """Edits the panel message in place, whether it's plain text or a photo
    with a caption (پنل بنر - see "ثبت تصویر panel_banner"). Mirrors the
    same pattern used by /start and «راهنما»."""
    if content_type == "photo":
        await bot.edit_message_caption(caption=text, chat_id=chat_id, message_id=message_id, reply_markup=kb)
    else:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=kb)


@bot.message_handler(
    chat_types=["group", "supergroup"],
    func=lambda m: normalize_trigger(m.text or "").strip() in PANEL_TRIGGERS,
)
async def open_panel(message: Message):
    if not await is_authorized_admin(db, message.chat.id, message.from_user.id):
        await bot.reply_to(
            message,
            "⛔️ پنل تنظیمات فقط برای ادمین‌های ربات در این گروه قابل استفاده است.",
        )
        return
    await _render_main(message, message.from_user.id, edit=False)


@bot.callback_query_handler(func=lambda c: c.data.startswith("pnl:"))
async def panel_callback(call: CallbackQuery):
    invoker_id, parts = await verify_panel_callback(call)
    if invoker_id is None:
        return
    await bot.answer_callback_query(call.id)

    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    content_type = call.message.content_type

    async def edit(text: str, kb: InlineKeyboardMarkup):
        await _edit_call_message(chat_id, msg_id, content_type, text, kb)

    if not parts or parts[0] == "main":
        await edit(MAIN_TEXT, _main_keyboard(invoker_id))
        return

    if parts[0] == "close":
        try:
            await bot.delete_message(chat_id, msg_id)
        except Exception:
            await edit("پنل بسته شد.", InlineKeyboardMarkup())
        return

    if parts[0] == "help":
        await send_help(chat_id, invoker_id)
        return

    if parts[0] == "locks":
        if len(parts) >= 3 and parts[1] == "toggle":
            lock_key = parts[2]
            locks_row = await db.get_chat_locks(chat_id)
            new_state = not is_lock_enabled(locks_row, lock_key)
            await db.set_chat_lock(chat_id, lock_key, new_state)
            chat_config_cache.invalidate(chat_id)
        text, kb = await _locks_text_and_keyboard(chat_id, invoker_id)
        await edit(text, kb)
        return

    if parts[0] == "lists":
        if len(parts) >= 2:
            sub = parts[1]
            text_fn = {
                "admins": _lists_admins_text,
                "vips": _lists_vips_text,
                "filters": _lists_filters_text,
                "warnings": _lists_warnings_text,
            }.get(sub)
            if text_fn:
                text = await text_fn(chat_id)
                kb = InlineKeyboardMarkup()
                kb.add(InlineKeyboardButton("⬅️ بازگشت", callback_data=encode(invoker_id, "lists"), style="danger"))
                await edit(text, kb)
                return
        await edit(
            "📋 <b>لیست‌ها</b>\n\nیک مورد را انتخاب کنید:",
            _lists_menu_keyboard(invoker_id),
        )
        return

    if parts[0] == "settings":
        if len(parts) >= 3 and parts[1] == "toggle":
            key = parts[2]
            s = await db.get_chat_settings(chat_id)
            if key == "welcome":
                await db.set_welcome_settings(chat_id, enabled=not s["welcome_enabled"])
            elif key == "goodbye":
                await db.set_goodbye_settings(chat_id, enabled=not s["goodbye_enabled"])
            elif key == "captcha":
                await db.set_join_captcha_enabled(chat_id, not s["join_captcha_enabled"])
            chat_config_cache.invalidate(chat_id)
        text, kb = await _settings_text_and_keyboard(chat_id, invoker_id)
        await edit(text, kb)
        return