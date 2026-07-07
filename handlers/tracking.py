"""
handlers/tracking.py
----------------------
Class-based middleware (pyTelegramBotAPI) that transparently tracks stats
for EVERY incoming group message, regardless of which handler (if any)
processes it afterwards:

    - keeps `users` fresh (name / username)
    - logs one row per message sent (message_log)
    - logs member additions, crediting whoever added them (member_log)

Registered in bot.py via `bot.setup_middleware(StatsMiddleware())`.
"""

from telebot.asyncio_handler_backends import BaseMiddleware
from telebot.types import Message

from core import db


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
                    new_member.id,
                    new_member.username,
                    new_member.first_name,
                    new_member.last_name,
                )
                if adder_id:
                    await db.log_member_added(adder_id, new_member.id, message.chat.id)

        # 3) A regular message (not a join/leave service message) -> count it.
        elif message.from_user and not message.from_user.is_bot:
            await db.log_message(message.from_user.id, message.chat.id)

    async def post_process(self, message: Message, data: dict, exception=None):
        pass