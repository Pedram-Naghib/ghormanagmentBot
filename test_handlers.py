"""
Mock-based smoke tests for the v6 changes. Runs the ACTUAL handler
coroutines (not just import-checks them) against AsyncMock stand-ins for
`bot` and `db`, so real logic bugs (wrong args, wrong branch, etc.) show
up here instead of in production.

Run: BOT_TOKEN=... OWNER_USER_IDS=1 python3 test_handlers.py
"""

import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("BOT_TOKEN", "123456:fake-token-for-tests")
os.environ.setdefault("OWNER_USER_IDS", "999")

import core  # noqa: E402
from handlers import admin_commands, panel_command, profile_command, tracking  # noqa: E402
from utils.panel_auth import encode  # noqa: E402

# IMPORTANT: core.bot/core.db must stay the REAL AsyncTeleBot/Database
# objects at import time (above) so the @bot.message_handler /
# @bot.callback_query_handler decorators - which run immediately at
# import - work exactly like in production. We only replace the specific
# outbound API methods afterwards, since those are looked up on the same
# shared object at CALL time, not import time.
BOT_METHODS = [
    "reply_to", "send_message", "ban_chat_member", "restrict_chat_member",
    "unban_chat_member", "delete_message", "edit_message_text", "edit_message_caption",
    "answer_callback_query", "get_chat", "get_chat_member", "get_user_profile_photos", "get_me",
]
DB_METHODS = [
    "get_user_role", "get_user_id_by_username", "get_user_display_name", "set_user_role",
    "list_users_by_role", "get_chat_owner", "get_user_message_count", "get_chat_settings",
    "set_chat_settings", "get_chat_locks", "set_chat_lock", "add_filtered_word",
    "remove_filtered_word", "list_filtered_words", "add_warning", "clear_warnings",
    "count_warnings", "list_warned_users", "set_welcome_settings", "set_goodbye_settings",
    "upsert_user", "log_member_added", "log_message",
]

for m in BOT_METHODS:
    setattr(core.bot, m, AsyncMock(name=f"bot.{m}"))
for m in DB_METHODS:
    setattr(core.db, m, AsyncMock(name=f"db.{m}"))

PASS = []
FAIL = []


def check(name, condition, detail=""):
    if condition:
        PASS.append(name)
    else:
        FAIL.append(f"{name} :: {detail}")


def user(uid, first="Test", last=None, username=None, is_bot=False):
    return SimpleNamespace(id=uid, first_name=first, last_name=last, username=username, is_bot=is_bot,
                            full_name=first + (f" {last}" if last else ""))


def message(chat_id=100, from_user=None, text="", reply_to_message=None, message_id=1, title="گروه تست"):
    return SimpleNamespace(
        chat=SimpleNamespace(id=chat_id, type="supergroup", title=title),
        from_user=from_user,
        text=text,
        reply_to_message=reply_to_message,
        message_id=message_id,
        entities=[],
        caption=None,
        caption_entities=[],
        content_type="text",
    )


async def reset():
    for m in BOT_METHODS:
        getattr(core.bot, m).reset_mock(side_effect=True, return_value=True)
    for m in DB_METHODS:
        getattr(core.db, m).reset_mock(side_effect=True, return_value=True)


# ---------------------------------------------------------------- #
# 1) Non-admin gets an explanation, not silence (bug #1)
# ---------------------------------------------------------------- #
async def test_ban_denied_explains():
    await reset()
    core.db.get_user_role.return_value = "normal"  # not owner/admin
    admin = user(1)
    target = user(2)
    msg = message(from_user=admin, text="بن", reply_to_message=message(from_user=target))
    await admin_commands.ban_user(msg)
    core.bot.reply_to.assert_awaited_once()
    reply_text = core.bot.reply_to.await_args.args[1]
    check("ban_denied_explains", "ادمین" in reply_text, reply_text)
    check("ban_denied_no_ban_call", not core.bot.ban_chat_member.called)


# ---------------------------------------------------------------- #
# 2) Successful ban by an authorized admin
# ---------------------------------------------------------------- #
async def test_ban_success():
    await reset()
    core.db.get_user_role.return_value = "owner"  # caller is owner -> authorized; also used for target-protection check
    admin = user(1)
    target = user(2, first="Sara")

    async def get_user_role_side_effect(chat_id, uid):
        return "owner" if uid == admin.id else "normal"

    core.db.get_user_role.side_effect = get_user_role_side_effect
    msg = message(from_user=admin, text="بن", reply_to_message=message(from_user=target))
    await admin_commands.ban_user(msg)
    check("ban_success_calls_api", core.bot.ban_chat_member.await_args is not None)
    if core.bot.ban_chat_member.await_args:
        args = core.bot.ban_chat_member.await_args.args
        check("ban_success_correct_target", args[1] == target.id, args)


# ---------------------------------------------------------------- #
# 3) Warning auto-ban at WARN_LIMIT
# ---------------------------------------------------------------- #
async def test_warn_auto_ban():
    await reset()
    admin = user(1)
    target = user(2, first="Ali")

    async def get_user_role_side_effect(chat_id, uid):
        return "admin" if uid == admin.id else "normal"

    core.db.get_user_role.side_effect = get_user_role_side_effect
    core.db.add_warning.return_value = admin_commands.WARN_LIMIT  # hit the threshold
    msg = message(from_user=admin, text="اخطار", reply_to_message=message(from_user=target))
    await admin_commands.warn_user(msg)
    check("warn_auto_ban_calls_ban", core.bot.ban_chat_member.await_args is not None)
    check("warn_auto_ban_clears_warnings", core.db.clear_warnings.await_args is not None)


# ---------------------------------------------------------------- #
# 4) Panel: invoker-lock rejects a different user's tap
# ---------------------------------------------------------------- #
async def test_panel_rejects_other_user():
    await reset()
    invoker = 111
    intruder = user(222)
    call = SimpleNamespace(
        id="cbq1",
        data=encode(invoker, "locks", "toggle", "sticker"),
        from_user=intruder,
        message=message(chat_id=100, message_id=5),
    )
    await panel_command.panel_callback(call)
    check("panel_rejects_intruder_alert", core.bot.answer_callback_query.await_args is not None)
    if core.bot.answer_callback_query.await_args:
        kwargs = core.bot.answer_callback_query.await_args.kwargs
        check("panel_rejects_intruder_show_alert", kwargs.get("show_alert") is True, kwargs)
    check("panel_rejects_intruder_no_toggle", not core.db.set_chat_lock.called)


# ---------------------------------------------------------------- #
# 5) Panel: legitimate invoker CAN toggle a lock
# ---------------------------------------------------------------- #
async def test_panel_toggle_by_invoker():
    await reset()
    invoker_user = user(111)
    core.db.get_user_role.return_value = "owner"
    core.db.get_chat_locks.return_value = {}  # sticker defaults to False -> toggling makes it True
    call = SimpleNamespace(
        id="cbq2",
        data=encode(111, "locks", "toggle", "sticker"),
        from_user=invoker_user,
        message=message(chat_id=100, message_id=5),
    )
    await panel_command.panel_callback(call)
    check("panel_toggle_calls_set_lock", core.db.set_chat_lock.await_args is not None)
    if core.db.set_chat_lock.await_args:
        args = core.db.set_chat_lock.await_args.args
        check("panel_toggle_correct_key_and_value", args[1] == "sticker" and args[2] is True, args)


# ---------------------------------------------------------------- #
# 6) Profile is admin-only and explains when blocked
# ---------------------------------------------------------------- #
async def test_profile_blocked_for_normal_user():
    await reset()
    core.db.get_user_role.return_value = "normal"
    normal = user(3)
    msg = message(from_user=normal, text="پروفایل")
    await profile_command.show_profile(msg)
    check("profile_blocked_replies", core.bot.reply_to.await_args is not None)
    check("profile_blocked_no_stats_lookup", not core.db.get_user_message_count.called)


# ---------------------------------------------------------------- #
# 7) Welcome message fires on new_chat_members, respects the toggle
# ---------------------------------------------------------------- #
async def test_welcome_message_sent_and_respects_toggle():
    await reset()
    core.db.get_chat_settings.return_value = {
        "welcome_enabled": True, "welcome_text": None,
        "goodbye_enabled": True, "goodbye_text": None,
    }
    new_member = user(50, first="Reza")
    msg = message(from_user=user(1), text="")
    msg.new_chat_members = [new_member]
    msg.left_chat_member = None
    await tracking._send_welcome(msg)
    check("welcome_sent_when_enabled", core.bot.send_message.await_args is not None)

    await reset()
    core.db.get_chat_settings.return_value = {
        "welcome_enabled": False, "welcome_text": None,
        "goodbye_enabled": True, "goodbye_text": None,
    }
    await tracking._send_welcome(msg)
    check("welcome_not_sent_when_disabled", not core.bot.send_message.called)


# ---------------------------------------------------------------- #
# 8) Locks: a sticker gets deleted only when the sticker lock is ON
# ---------------------------------------------------------------- #
async def test_lock_deletes_sticker_when_enabled():
    from handlers import antispam

    await reset()
    core.db.get_chat_locks.return_value = {"sticker": True}
    sticker_msg = message(from_user=user(4), text="")
    sticker_msg.content_type = "sticker"
    result = await antispam._check_locks(sticker_msg)
    check("lock_sticker_on_deletes", result is True and core.bot.delete_message.await_args is not None)

    await reset()
    core.db.get_chat_locks.return_value = {"sticker": False}
    result = await antispam._check_locks(sticker_msg)
    check("lock_sticker_off_ignores", result is False and not core.bot.delete_message.called)


# ---------------------------------------------------------------- #
# 9) Filtered words: message containing a filtered word gets deleted
# ---------------------------------------------------------------- #
async def test_filtered_word_deletes_message():
    from handlers import antispam

    await reset()
    core.db.list_filtered_words.return_value = ["فحش‌بد"]
    msg = message(from_user=user(5), text="این یک فحش‌بد است")
    result = await antispam._check_filtered_words(msg)
    check("filtered_word_deletes", result is True and core.bot.delete_message.await_args is not None)

    await reset()
    core.db.list_filtered_words.return_value = ["فحش‌بد"]
    clean_msg = message(from_user=user(5), text="سلام دوستان")
    result = await antispam._check_filtered_words(clean_msg)
    check("filtered_word_ignores_clean_text", result is False and not core.bot.delete_message.called)


# ---------------------------------------------------------------- #
# 10) Bot lacking admin rights -> friendly explanation, not raw exception
# ---------------------------------------------------------------- #
async def test_bot_permission_error_is_translated():
    await reset()

    async def get_user_role_side_effect(chat_id, uid):
        return "owner" if uid == 1 else "normal"

    core.db.get_user_role.side_effect = get_user_role_side_effect
    core.bot.ban_chat_member.side_effect = Exception("Forbidden: not enough rights to restrict/unrestrict chat member")
    admin = user(1)
    target = user(6, first="Neda")
    msg = message(from_user=admin, text="بن", reply_to_message=message(from_user=target))
    await admin_commands.ban_user(msg)
    reply_call = core.bot.reply_to.await_args
    check("bot_permission_error_friendly", reply_call is not None and "ادمین" in reply_call.args[1], reply_call)
    check("bot_permission_error_not_raw", reply_call is not None and "Forbidden" not in reply_call.args[1])


async def main():
    tests = [
        test_ban_denied_explains,
        test_ban_success,
        test_warn_auto_ban,
        test_panel_rejects_other_user,
        test_panel_toggle_by_invoker,
        test_profile_blocked_for_normal_user,
        test_welcome_message_sent_and_respects_toggle,
        test_lock_deletes_sticker_when_enabled,
        test_filtered_word_deletes_message,
        test_bot_permission_error_is_translated,
    ]
    for t in tests:
        try:
            await t()
        except Exception as e:
            FAIL.append(f"{t.__name__} :: CRASHED: {e!r}")

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed\n")
    for name in PASS:
        print(f"  ✅ {name}")
    for name in FAIL:
        print(f"  ❌ {name}")

    if FAIL:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())