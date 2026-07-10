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
    "send_photo", "send_video", "send_voice", "send_audio", "send_animation", "send_document",
    "send_video_note", "approve_chat_join_request", "decline_chat_join_request", "delete_messages",
]
DB_METHODS = [
    "get_user_role", "get_user_id_by_username", "get_user_display_name", "set_user_role",
    "list_users_by_role", "get_chat_owner", "get_user_message_count", "get_chat_settings",
    "set_chat_settings", "get_chat_locks", "set_chat_lock", "add_filtered_word",
    "remove_filtered_word", "list_filtered_words", "add_warning", "clear_warnings",
    "count_warnings", "list_warned_users", "set_welcome_settings", "set_goodbye_settings",
    "upsert_user", "log_member_added", "log_message",
    "set_spam_limit", "set_spam_mute_minutes", "set_join_captcha_enabled",
    "add_global_admin", "remove_global_admin", "list_global_admins",
    "get_message_overrides", "set_message_override", "reset_message_override",
    "cleanup_old_message_logs", "get_recently_joined_members", "get_top_adders",
    "get_top_message_senders", "get_recent_message_ids", "get_all_logged_message_ids",
    "delete_logged_messages", "get_asset", "set_asset",
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
    core.db.get_asset.return_value = None  # "no banner registered" - the common case


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
        "welcome_media_file_id": None, "welcome_media_type": None,
        "goodbye_enabled": True, "goodbye_text": None,
        "goodbye_media_file_id": None, "goodbye_media_type": None,
        "join_captcha_enabled": False,
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
        "welcome_media_file_id": None, "welcome_media_type": None,
        "goodbye_enabled": True, "goodbye_text": None,
        "goodbye_media_file_id": None, "goodbye_media_type": None,
        "join_captcha_enabled": False,
    }
    await tracking._send_welcome(msg)
    check("welcome_not_sent_when_disabled", not core.bot.send_message.called)


# ---------------------------------------------------------------- #
# 8) Locks: a sticker gets deleted only when the sticker lock is ON
# ---------------------------------------------------------------- #
async def test_lock_deletes_sticker_when_enabled():
    from handlers import antispam
    from utils import chat_config_cache

    await reset()
    chat_id = 9001  # dedicated chat_id per sub-case so the cache can't bleed between them
    chat_config_cache.invalidate(chat_id)
    core.db.get_chat_locks.return_value = {"sticker": True}
    core.db.list_filtered_words.return_value = []
    core.db.get_chat_settings.return_value = {"spam_message_limit": 999, "spam_time_window_seconds": 3, "spam_mute_minutes": 30}
    sticker_msg = message(chat_id=chat_id, from_user=user(4), text="")
    sticker_msg.content_type = "sticker"
    result = await antispam.apply_normal_member_restrictions(sticker_msg)
    check("lock_sticker_on_deletes", result is True and core.bot.delete_message.await_args is not None)

    await reset()
    chat_id2 = 9002
    chat_config_cache.invalidate(chat_id2)
    core.db.get_chat_locks.return_value = {"sticker": False}
    core.db.list_filtered_words.return_value = []
    core.db.get_chat_settings.return_value = {"spam_message_limit": 999, "spam_time_window_seconds": 3, "spam_mute_minutes": 30}
    sticker_msg2 = message(chat_id=chat_id2, from_user=user(4), text="")
    sticker_msg2.content_type = "sticker"
    result = await antispam.apply_normal_member_restrictions(sticker_msg2)
    check("lock_sticker_off_ignores", result is False and not core.bot.delete_message.called)


# ---------------------------------------------------------------- #
# 9) Filtered words: message containing a filtered word gets deleted
# ---------------------------------------------------------------- #
async def test_filtered_word_deletes_message():
    from handlers import antispam
    from utils import chat_config_cache

    await reset()
    chat_id = 9003
    chat_config_cache.invalidate(chat_id)
    core.db.get_chat_locks.return_value = {}
    core.db.list_filtered_words.return_value = ["فحش‌بد"]
    core.db.get_chat_settings.return_value = {"spam_message_limit": 999, "spam_time_window_seconds": 3, "spam_mute_minutes": 30}
    msg = message(chat_id=chat_id, from_user=user(5), text="این یک فحش‌بد است")
    msg.content_type = "text"
    result = await antispam.apply_normal_member_restrictions(msg)
    check("filtered_word_deletes", result is True and core.bot.delete_message.await_args is not None)

    await reset()
    chat_id2 = 9004
    chat_config_cache.invalidate(chat_id2)
    core.db.get_chat_locks.return_value = {}
    core.db.list_filtered_words.return_value = ["فحش‌بد"]
    core.db.get_chat_settings.return_value = {"spam_message_limit": 999, "spam_time_window_seconds": 3, "spam_mute_minutes": 30}
    clean_msg = message(chat_id=chat_id2, from_user=user(5), text="سلام دوستان")
    clean_msg.content_type = "text"
    result = await antispam.apply_normal_member_restrictions(clean_msg)
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


# ---------------------------------------------------------------- #
# 11) Role hierarchy: owner2 can manage admin/vip but not another owner2
#     or the owner; admin can only manage vip. See utils/permissions.py.
# ---------------------------------------------------------------- #
async def test_role_hierarchy_can_assign_role():
    from utils.permissions import can_assign_role

    await reset()
    core.db.get_user_role.return_value = "owner"
    check("owner_can_assign_owner2", await can_assign_role(core.db, 1, 10, "owner2") is True)
    check("owner_can_assign_admin", await can_assign_role(core.db, 1, 10, "admin") is True)

    core.db.get_user_role.return_value = "owner2"
    check("owner2_can_assign_admin", await can_assign_role(core.db, 1, 10, "admin") is True)
    check("owner2_cannot_assign_owner2", await can_assign_role(core.db, 1, 10, "owner2") is False)

    core.db.get_user_role.return_value = "admin"
    check("admin_can_assign_vip", await can_assign_role(core.db, 1, 10, "vip") is True)
    check("admin_cannot_assign_admin", await can_assign_role(core.db, 1, 10, "admin") is False)
    check("admin_cannot_assign_owner2", await can_assign_role(core.db, 1, 10, "owner2") is False)


# ---------------------------------------------------------------- #
# 12) Ban/mute protection is hierarchy-aware: an admin cannot ban an
#     owner2 or another admin (outranks() must be False in both cases).
# ---------------------------------------------------------------- #
async def test_ban_protection_respects_hierarchy():
    await reset()
    admin = user(1)
    owner2_target = user(7, first="Boss2")

    async def role_side_effect(chat_id, uid):
        return "admin" if uid == 1 else "owner2"

    core.db.get_user_role.side_effect = role_side_effect
    msg = message(from_user=admin, text="بن", reply_to_message=message(from_user=owner2_target))
    await admin_commands.ban_user(msg)
    check("admin_cannot_ban_owner2", not core.bot.ban_chat_member.called)
    reply_text = core.bot.reply_to.await_args.args[1]
    check("admin_cannot_ban_owner2_explains", "رتبه" in reply_text, reply_text)


# ---------------------------------------------------------------- #
# 13) Global Admin (ادمین کل): dynamically promoted, cached in memory,
#     gets identical access to a hardcoded Global Owner in ANY chat.
# ---------------------------------------------------------------- #
async def test_global_admin_cache_grants_full_access():
    from utils import global_admins
    from utils.permissions import is_authorized_admin, is_super_admin

    await reset()
    core.db.list_global_admins.return_value = [(555, 999)]
    await global_admins.load(core.db)
    try:
        check("global_admin_is_super_admin", is_super_admin(555) is True)
        core.db.get_user_role.return_value = "normal"  # even with no per-chat role at all
        result = await is_authorized_admin(core.db, chat_id=123, user_id=555)
        check("global_admin_authorized_without_chat_role", result is True)
    finally:
        await global_admins.remove(core.db, 555)  # don't leak into other tests


# ---------------------------------------------------------------- #
# 14) Message registry (utils/messages.py): override applies immediately,
#     reset reverts, malformed template never crashes a live reply.
# ---------------------------------------------------------------- #
async def test_message_registry_override_and_reset():
    from utils import messages

    await reset()
    core.db.get_message_overrides.return_value = {}
    await messages.load(core.db)

    default_text = messages.get("ban.success", name="Ali", funny_line="bye")
    check("message_registry_default_renders", "Ali" in default_text)

    await messages.set_override(core.db, "ban.success", "CUSTOM {name} - {funny_line}")
    overridden_text = messages.get("ban.success", name="Sara", funny_line="later")
    check("message_registry_override_applies", "CUSTOM Sara - later" == overridden_text, overridden_text)

    await messages.set_override(core.db, "ban.success", "Broken {this_key_does_not_exist}")
    fallback_text = messages.get("ban.success", name="Reza", funny_line="ok")
    check("message_registry_bad_template_falls_back", "Reza" in fallback_text and "Broken" not in fallback_text)

    await messages.reset_override(core.db, "ban.success")
    check("message_registry_reset_clears_override", not messages.is_overridden("ban.success"))


# ---------------------------------------------------------------- #
# 15) Banners (عکس/گیف/ویدیو) for بن/میوت, and utils/banners.py itself
# ---------------------------------------------------------------- #
async def test_ban_sends_registered_banner_instead_of_plain_reply():
    await reset()
    core.db.get_user_role.side_effect = lambda chat_id, uid: "owner" if uid == 1 else "normal"
    core.db.get_asset.return_value = {"file_id": "FILE123", "content_type": "photo"}
    admin, target = user(1), user(2, first="Sara")
    msg = message(from_user=admin, text="بن", reply_to_message=message(from_user=target))

    await admin_commands.ban_user(msg)

    check("ban_banner_send_photo_called", core.bot.send_photo.await_args is not None)
    check("ban_banner_no_plain_reply", core.bot.reply_to.await_args is None)
    if core.bot.send_photo.await_args:
        _args, kwargs = core.bot.send_photo.call_args
        check("ban_banner_caption_has_name", "Sara" in kwargs.get("caption", ""), kwargs)


async def test_mute_sends_registered_animation_banner():
    await reset()
    core.db.get_user_role.side_effect = lambda chat_id, uid: "owner" if uid == 1 else "normal"
    core.db.get_asset.return_value = {"file_id": "GIF123", "content_type": "animation"}
    admin, target = user(1), user(2, first="Sara")
    msg = message(from_user=admin, text="میوت", reply_to_message=message(from_user=target))

    await admin_commands.mute_user(msg)

    check("mute_banner_send_animation_called", core.bot.send_animation.await_args is not None)
    check("mute_banner_no_photo_sent", core.bot.send_photo.await_args is None)
    check("mute_banner_no_plain_reply", core.bot.reply_to.await_args is None)


async def test_ban_falls_back_to_plain_reply_when_no_banner_registered():
    await reset()
    core.db.get_user_role.side_effect = lambda chat_id, uid: "owner" if uid == 1 else "normal"
    # core.db.get_asset already defaults to None via reset() above
    admin, target = user(1), user(2, first="Sara")
    msg = message(from_user=admin, text="بن", reply_to_message=message(from_user=target))

    await admin_commands.ban_user(msg)

    check("ban_no_banner_falls_back_to_reply", core.bot.reply_to.await_args is not None)
    check("ban_no_banner_no_send_photo", core.bot.send_photo.await_args is None)


async def test_set_image_accepts_gif_and_video():
    owner = user(999)  # matches OWNER_USER_IDS in the test env

    await reset()
    gif_reply = SimpleNamespace(content_type="animation", animation=SimpleNamespace(file_id="GIFXYZ"))
    msg = message(from_user=owner, text="ثبت تصویر ban_banner", reply_to_message=gif_reply)
    await admin_commands.set_image(msg)
    check("set_image_gif_stores_correct_type", core.db.set_asset.await_args is not None)
    if core.db.set_asset.await_args:
        args, kwargs = core.db.set_asset.call_args
        check(
            "set_image_gif_args_correct",
            args[0] == "ban_banner" and args[1] == "GIFXYZ" and kwargs.get("content_type") == "animation",
            (args, kwargs),
        )

    await reset()
    video_reply = SimpleNamespace(content_type="video", video=SimpleNamespace(file_id="VIDXYZ"))
    msg2 = message(from_user=owner, text="ثبت تصویر mute_banner", reply_to_message=video_reply)
    await admin_commands.set_image(msg2)
    if core.db.set_asset.await_args:
        args, kwargs = core.db.set_asset.call_args
        check(
            "set_image_video_args_correct",
            args[0] == "mute_banner" and args[1] == "VIDXYZ" and kwargs.get("content_type") == "video",
            (args, kwargs),
        )

    await reset()
    text_reply = message(from_user=user(2))  # content_type defaults to "text" - not a valid banner
    msg3 = message(from_user=owner, text="ثبت تصویر ban_banner", reply_to_message=text_reply)
    await admin_commands.set_image(msg3)
    check("set_image_rejects_non_media_reply", core.db.set_asset.await_args is None)


async def test_send_banner_helper_directly():
    from utils.banners import send_banner

    await reset()
    core.db.get_asset.return_value = None
    result = await send_banner(100, "no_such_key", "caption text")
    check("send_banner_returns_false_when_unregistered", result is False)
    check("send_banner_sends_nothing_when_unregistered", core.bot.send_photo.await_args is None)

    await reset()
    core.db.get_asset.return_value = {"file_id": "VID1", "content_type": "video"}
    result = await send_banner(100, "some_key", "caption text")
    check("send_banner_returns_true_when_registered", result is True)
    check("send_banner_dispatches_to_send_video", core.bot.send_video.await_args is not None)


async def test_handler_modules_are_not_swapped():
    """
    Regression guard: on 2026-07, handlers/start_command.py was accidentally
    overwritten with handlers/stats_commands.py's content (same docstring,
    same functions) - /start silently stopped working because the module
    bot.py imports for its side effects no longer registered a "start"
    command handler at all. Nothing else caught this because no test
    actually imports handlers.start_command. This just checks each module
    defines what it's supposed to, so a copy/paste mix-up like that fails
    the test suite instead of shipping silently.
    """
    from handlers import help_command, panel_command, start_command, stats_commands

    check("start_command_module_has_start_handler", hasattr(start_command, "start_command"))
    check("start_command_module_no_stats_functions", not hasattr(start_command, "daily_stats"))
    check("stats_commands_module_has_daily_stats", hasattr(stats_commands, "daily_stats"))
    check("stats_commands_module_has_total_stats", hasattr(stats_commands, "total_stats"))
    check("help_command_module_has_send_help", hasattr(help_command, "send_help"))
    check("panel_command_module_has_open_panel", hasattr(panel_command, "open_panel"))


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
        test_role_hierarchy_can_assign_role,
        test_ban_protection_respects_hierarchy,
        test_global_admin_cache_grants_full_access,
        test_message_registry_override_and_reset,
        test_ban_sends_registered_banner_instead_of_plain_reply,
        test_mute_sends_registered_animation_banner,
        test_ban_falls_back_to_plain_reply_when_no_banner_registered,
        test_set_image_accepts_gif_and_video,
        test_send_banner_helper_directly,
        test_handler_modules_are_not_swapped,
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