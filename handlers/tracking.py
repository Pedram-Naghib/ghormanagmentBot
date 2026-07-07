"""
handlers/tracking.py
----------------------
Two things:

1. StatsMiddleware - transparently tracks stats for EVERY incoming group
   message (message counts, new-member credit), regardless of which
   handler (if any) processes it afterwards.

2. on_bot_added_to_chat - a `my_chat_member` handler that fires whenever
   the BOT's own status changes in a chat. This is how we auto-detect the
   group's owner: when the bot goes from having no relationship (or
   "left"/"kicked") to "member" or "administrator", Telegram tells us
   exactly who performed that action (`update.from_user`) - that person
   gets role='owner' for this chat, per your role model.
"""

from telebot.asyncio_handler_backends import BaseMiddleware
from telebot.types import ChatMemberUpdated, Message

from core import bot, db

IN_CHAT_STATUSES = {"member", "administrator", "restricted"}


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

        # 2) New members joined -> credit whoever added them.
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

        # 3) A regular message (not a join/leave service message) -> count it.
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
                f"ادمین و عضو ویژه هم تعیین کنه.\nبرای شروع بنویسید: /help",
            )
        except Exception:
            pass