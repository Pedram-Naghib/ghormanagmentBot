"""
utils/telegram_errors.py
---------------------------
When an admin action (ban/mute/restrict/delete/...) fails because the BOT
ITSELF isn't a Telegram admin in that group (or is missing the specific
right needed), Telegram's API returns an error like "Forbidden: not enough
rights..." or "CHAT_ADMIN_REQUIRED". Previously that raw exception text was
just dumped back to the admin, which doesn't tell them what to actually do.

bot_permission_error_reply() recognizes these cases and returns the right
Persian explanation instead; anywhere the bot calls a moderation API and
catches Exception should route the error through this first.
"""

_BOT_PERMISSION_MARKERS = (
    "not enough rights",
    "CHAT_ADMIN_REQUIRED",
    "have no rights",
    "USER_NOT_MUTUAL_CONTACT",
    "not a member of the chat",
    "can't remove chat owner",
)


def is_bot_permission_error(exc: Exception) -> bool:
    text = str(exc)
    return any(marker.lower() in text.lower() for marker in _BOT_PERMISSION_MARKERS)


def bot_permission_error_reply(exc: Exception) -> str:
    """Returns a ready-to-send Persian message for the given exception."""
    text = str(exc)
    if "can't remove chat owner" in text.lower():
        return "❌ نمی‌توان این کاربر را بن کرد؛ او مالک یا ادمین واقعی این گروه در تلگرام است."
    if is_bot_permission_error(exc):
        return (
            "⚠️ ربات دسترسی لازم برای انجام این کار را در این گروه ندارد.\n"
            "لطفاً از تنظیمات گروه، ربات را <b>ادمین</b> کنید و مطمئن شوید دسترسی‌های "
            "«حذف پیام»، «محدود کردن اعضا» و «دعوت با لینک» برایش فعال است، سپس دوباره امتحان کنید."
        )
    return f"❌ خطا: {text}"