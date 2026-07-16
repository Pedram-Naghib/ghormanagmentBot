"""
utils/messages.py
--------------------
Central registry for every bot response that's meant to be editable
without touching code - backed by the `bot_messages` DB table, with an
in-memory cache so normal message-sending never hits the DB (see load()).

HOW TO ADD A NEW EDITABLE MESSAGE:
    1. Add DEFAULTS["your.key"] = "template with {placeholders}"
    2. Use it: messages.get("your.key", placeholder=value, ...)
A missing DB row just means "use the hardcoded default", so adding a new
key never needs a migration, and nothing breaks if the DB has a stale key
from a since-removed message.

WHO EDITS THESE: the authenticated web page at /admin/messages (see
admin_panel_page.py) - HTTP Basic Auth against ADMIN_PANEL_USERNAME/
ADMIN_PANEL_PASSWORD in .env. There's deliberately no in-Telegram command
for this (unlike welcome/goodbye, which get their own dedicated commands
since they're the single most commonly customized thing) - a web form is a
much better editing experience for a page full of text than a chat command
with an entire template as its argument.

SCOPE (round 1): the highest-traffic admin-facing confirmations/denials -
ban/unban/mute/unmute/vip/warn outcomes, and the two "you can't do that"
messages. NOT yet migrated: the long onboarding/capability texts (وضعیت
قابلیت‌ها) and the full /help section text (help_command.py) - those are
more "documentation" than "tone", and are a much bigger, mechanical follow-
up if you want them editable too (same pattern, just more keys).
"""

from typing import Dict

DEFAULTS: Dict[str, str] = {
    # --- Access denials ---
    "not_admin": "⛔️ این دستور فقط برای ادمین‌های ربات در این گروه قابل استفاده است.",
    "not_super_admin": "⛔️ این دستور فقط مخصوص مالک ربات یا ادمین کل است و برای شما در دسترس نیست.",
    "not_outranked": "❌ این کاربر {role_label} این گروه است و رتبهٔ شما برای این کار روی او کافی نیست.",
    "cant_touch_bot_owner": "❌ نمی‌توانید مالک ربات را مسدود کنید.",

    # --- Ban ---
    "ban.success": (
        "⛔️ کاربر {name} از گروه اخراج و بن شد.\n"
        "او نمی‌تواند با لینک دعوت دوباره وارد شود، مگر با دستور «رفع بن».\n\n"
        "{funny_line}"
    ),
    "ban.need_target": (
        "⚠️ برای اخراج و بن کردن کاربر، روی پیام او ریپلای کنید (یا روی پیامی که فقط "
        "@username کاربر را دارد ریپلای کنید)."
    ),
    "ban.already_banned": "ℹ️ کاربر {name} از قبل بن است؛ نیازی به بن دوباره نبود.",

    # --- Unban ---
    "unban.success": "✅ کاربر {name} از بن خارج شد و می‌تواند دوباره وارد گروه شود.",
    "unban.already_unbanned": "ℹ️ کاربر {name} از قبل بن نیست؛ نیازی به رفع بن نبود.",
    "unban.need_target": (
        "⚠️ برای رفع بن، روی یکی از پیام‌های قبلی کاربر ریپلای کنید یا یوزرنیم را بنویسید:\n"
        "مثال: <code>رفع بن @username</code>\n"
        "(روش یوزرنیم فقط وقتی کار می‌کند که آن کاربر قبلاً در همین گروه پیام داده باشد.)"
    ),

    # --- Mute / Unmute ---
    "mute.forever": "🔇 کاربر {name} سکوت (Mute) شد و تا زمانی که با «رفع سکوت» آزاد نشود، همینطور می‌ماند.",
    "mute.timed": "🔇 کاربر {name} به مدت {minutes} دقیقه سکوت (Mute) شد.",
    "mute.need_target": "⚠️ برای سکوت کردن کاربر، روی پیام او ریپلای کنید.",
    "mute.already_muted": "ℹ️ کاربر {name} از قبل سکوت است؛ نیازی به سکوت دوباره نبود.",
    "unmute.success": "🔊 سکوت کاربر {name} برداشته شد.",
    "unmute.already_speaking": "ℹ️ {name} از قبل سکوت نبود؛ می‌تواند پیام بدهد.",
    "unmute.need_target": "⚠️ برای رفع سکوت، روی پیام کاربر ریپلای کنید یا بنویسید: <code>رفع سکوت @username</code>",

    # --- VIP ---
    "vip.set": "⭐️ کاربر {name} اکنون عضو ویژهٔ این گروه است (فقط در همین گروه).",
    "vip.unset": "✅ عضویت ویژهٔ {name} در این گروه لغو شد.",
    "vip.not_vip": "{name} عضو ویژهٔ این گروه نیست.",
    "vip.need_target": "⚠️ برای تنظیم/لغو عضو ویژه، روی پیام او ریپلای کنید.",

    # --- Warnings ---
    "warn.given": "⚠️ کاربر {name} اخطار گرفت ({count} از {limit}).{reason_line}",
    "warn.auto_ban": (
        "⚠️ کاربر {name} اخطار {count} از {limit} را دریافت کرد و به همین دلیل "
        "به‌طور خودکار از گروه اخراج و بن شد.{reason_line}"
    ),
    "warn.cleared": "✅ اخطارهای {name} پاک شد.",
}

_overrides: Dict[str, str] = {}


async def load(db) -> None:
    """Call once at startup (after db.connect()) to seed the cache."""
    _overrides.clear()
    _overrides.update(await db.get_message_overrides())


def get(key: str, **kwargs) -> str:
    template = _overrides.get(key) or DEFAULTS.get(key, key)
    try:
        return template.format(**kwargs)
    except Exception:
        # A bad custom template (e.g. missing/misspelled placeholder) should
        # never crash a live reply - fall back to the hardcoded default.
        fallback = DEFAULTS.get(key, key)
        try:
            return fallback.format(**kwargs)
        except Exception:
            return fallback


async def set_override(db, key: str, template: str, updated_by=None) -> None:
    await db.set_message_override(key, template, updated_by)
    _overrides[key] = template


async def reset_override(db, key: str) -> None:
    await db.reset_message_override(key)
    _overrides.pop(key, None)


def all_keys():
    return sorted(DEFAULTS.keys())


def effective(key: str) -> str:
    """The template currently in effect (override if set, else the default) - RAW, unformatted."""
    return _overrides.get(key) or DEFAULTS.get(key, "")


def is_overridden(key: str) -> bool:
    return key in _overrides