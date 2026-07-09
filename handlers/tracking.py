"""
handlers/tracking.py
----------------------
Three things:

1. StatsMiddleware - transparently tracks stats for EVERY incoming group
   message (message counts, new-member credit), regardless of which
   handler (if any) processes it afterwards. Also sends the welcome/
   goodbye messages when new_chat_members / left_chat_member service
   messages come through (see _send_welcome / _send_goodbye below).

2. on_bot_added_to_chat - a `my_chat_member` handler that fires whenever
   the BOT's own status changes in a chat. This is how we auto-detect the
   group's owner: when the bot goes from having no relationship (or
   "left"/"kicked") to "member" or "administrator", Telegram tells us
   exactly who performed that action (`update.from_user`) - that person
   gets role='owner' for this chat, per your role model. It also nudges
   whoever added the bot to grant it admin rights, since almost every
   moderation command (ban/mute/delete) silently fails without them.
"""

from telebot.asyncio_handler_backends import BaseMiddleware
from telebot.types import ChatMemberUpdated, Message

from core import bot, db

IN_CHAT_STATUSES = {"member", "administrator", "restricted"}

DEFAULT_WELCOME_TEXT = "👋 {mention} به {group} خوش اومدی!"
DEFAULT_GOODBYE_TEXT = "😢 {name} از {group} رفت. بدرود!"


def _member_name(user) -> str:
    return " ".join(filter(None, [user.first_name, user.last_name])) or (f"@{user.username}" if user.username else str(user.id))


def _member_mention(user) -> str:
    name = _member_name(user)
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def _render_template(template: str, *, user, group_title: str) -> str:
    return template.format(name=_member_name(user), mention=_member_mention(user), group=group_title)


async def _send_welcome(message: Message):
    settings = await db.get_chat_settings(message.chat.id)
    if not settings["welcome_enabled"]:
        return
    template = settings["welcome_text"] or DEFAULT_WELCOME_TEXT
    for new_member in message.new_chat_members:
        if new_member.is_bot:
            continue
        try:
            text = _render_template(template, user=new_member, group_title=message.chat.title or "")
        except Exception:
            text = _render_template(DEFAULT_WELCOME_TEXT, user=new_member, group_title=message.chat.title or "")
        try:
            await bot.send_message(message.chat.id, text)
        except Exception:
            pass


async def _send_goodbye(message: Message):
    left_user = message.left_chat_member
    if not left_user or left_user.is_bot:
        return
    settings = await db.get_chat_settings(message.chat.id)
    if not settings["goodbye_enabled"]:
        return
    template = settings["goodbye_text"] or DEFAULT_GOODBYE_TEXT
    try:
        text = _render_template(template, user=left_user, group_title=message.chat.title or "")
    except Exception:
        text = _render_template(DEFAULT_GOODBYE_TEXT, user=left_user, group_title=message.chat.title or "")
    try:
        await bot.send_message(message.chat.id, text)
    except Exception:
        pass


class StatsMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()
        self.update_types = ["message"]
        self.update_sensitive = False

    async def pre_process(self, message: Message, data: dict):
        if message.chat.type not in ("group", "supergroup"):
            return

        # 1) Keep the sender's profile info fresh.
        if message.from_user and not message.from_user.is_bot:
            await db.upsert_user(
                message.chat.id,
                message.from_user.id,
                message.from_user.username,
                message.from_user.first_name,
                message.from_user.last_name,
            )

        # 2) New members joined -> credit whoever added them + welcome them.
        if message.new_chat_members:
            adder_id = message.from_user.id if message.from_user else None
            for new_member in message.new_chat_members:
                if new_member.is_bot:
                    continue
                await db.upsert_user(
                    message.chat.id,
                    new_member.id,
                    new_member.username,
                    new_member.first_name,
                    new_member.last_name,
                )
                if adder_id:
                    await db.log_member_added(message.chat.id, adder_id, new_member.id)
            await _send_welcome(message)

        # 3) Someone left -> say goodbye.
        elif message.left_chat_member:
            await _send_goodbye(message)

        # 4) A regular message (not a join/leave service message) -> count it.
        elif message.from_user and not message.from_user.is_bot:
            await db.log_message(message.chat.id, message.from_user.id)

    async def post_process(self, message: Message, data: dict, exception=None):
        pass


@bot.my_chat_member_handler()
async def on_bot_added_to_chat(update: ChatMemberUpdated):
    """Auto-record the group's owner: whoever just added/re-added this bot."""
    if update.chat.type not in ("group", "supergroup"):
        return

    was_in_chat = update.old_chat_member.status in IN_CHAT_STATUSES
    is_in_chat = update.new_chat_member.status in IN_CHAT_STATUSES

    if not was_in_chat and is_in_chat and update.from_user:
        await db.set_user_role(
            update.chat.id,
            update.from_user.id,
            "owner",
            username=update.from_user.username,
            first_name=update.from_user.first_name,
            last_name=update.from_user.last_name,
        )
        try:
            await bot.send_message(
                update.chat.id,
                f"👑 {update.from_user.full_name} من رو به این گروه اضافه کرد و "
                f"به‌عنوان <b>مالک این گروه</b> ثبت شد؛ یعنی دسترسی کامل به همهٔ "
                f"دستورات مدیریتی ربات رو (فقط در همین گروه) داره و می‌تونه "
                f"ادمین و عضو ویژه هم تعیین کنه.\n\n"
                f"⚠️ برای اینکه بتونم بن/سکوت/حذف پیام و بقیهٔ کارهای مدیریتی رو انجام بدم، "
                f"لطفاً از تنظیمات گروه من رو <b>ادمین</b> کنید (حداقل با دسترسی‌های «حذف پیام»، "
                f"«محدود کردن اعضا» و «دعوت با لینک»). بدون این دسترسی‌ها، دستورات مدیریتی "
                f"در این گروه کار نمی‌کنن.\n\n"
                f"برای شروع بنویسید: /help یا /panel",
            )
        except Exception:
            pass