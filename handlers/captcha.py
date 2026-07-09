"""
handlers/captcha.py
----------------------
Optional per-group captcha for join requests (گروه‌هایی که «تایید درخواست
عضویت» تلگرام را فعال دارند). OFF by default - enable per group with
«روشن کردن کپچا» (see the toggle in handlers/admin_commands.py / the panel's
تنظیمات پیشرفته section).

Flow:
  1. Someone sends a join request to a group with captcha ON.
  2. Bot DMs them a simple math question with 4 tappable answers. Telegram
     explicitly allows a bot to message a user who has a pending join
     request, even if that user never started a chat with the bot.
  3. Correct answer within 60 seconds -> approve_chat_join_request.
     Wrong answer, OR no answer within 60 seconds -> decline_chat_join_request.

Pending state is kept in memory (not the DB) - it's short-lived (60s) and
losing it on a bot restart just means that one pending requester falls
back to normal manual admin review, which is an acceptable edge case for
a UX nicety like this.
"""

import asyncio
import random
from dataclasses import dataclass, field

from telebot.types import CallbackQuery, ChatJoinRequest, InlineKeyboardButton, InlineKeyboardMarkup

from core import bot, db

CAPTCHA_TIMEOUT_SECONDS = 60


@dataclass
class _Pending:
    correct_answer: int
    dm_chat_id: int
    dm_message_id: int
    timeout_task: "asyncio.Task | None" = field(default=None)


_pending: dict[tuple, _Pending] = {}


def _make_question():
    a, b = random.randint(1, 9), random.randint(1, 9)
    correct = a + b
    options = {correct}
    while len(options) < 4:
        options.add(random.randint(2, 18))
    options = list(options)
    random.shuffle(options)
    return a, b, correct, options


def _captcha_keyboard(chat_id: int, user_id: int, options, correct: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=4)
    kb.add(*[
        InlineKeyboardButton(str(opt), callback_data=f"cap:{chat_id}:{user_id}:{opt}:{correct}")
        for opt in options
    ])
    return kb


@bot.chat_join_request_handler()
async def handle_join_request(update: ChatJoinRequest):
    settings = await db.get_chat_settings(update.chat.id)
    if not settings["join_captcha_enabled"]:
        return  # captcha off for this group - admins review requests manually as usual

    a, b, correct, options = _make_question()
    try:
        chat = await bot.get_chat(update.chat.id)
        group_name = chat.title or "این گروه"
    except Exception:
        group_name = "این گروه"

    text = (
        f"👋 سلام! برای عضویت در «{group_name}» لطفاً ظرف {CAPTCHA_TIMEOUT_SECONDS} ثانیه به این سؤال ساده جواب بده:\n\n"
        f"❓ {a} + {b} = ?"
    )
    try:
        sent = await bot.send_message(
            update.from_user.id, text,
            reply_markup=_captcha_keyboard(update.chat.id, update.from_user.id, options, correct),
        )
    except Exception:
        return  # couldn't DM them (blocked the bot, etc.) - leave the request pending for manual review

    key = (update.chat.id, update.from_user.id)
    pending = _Pending(correct_answer=correct, dm_chat_id=sent.chat.id, dm_message_id=sent.message_id)
    _pending[key] = pending
    pending.timeout_task = asyncio.create_task(_expire_after_timeout(key))


async def _expire_after_timeout(key):
    await asyncio.sleep(CAPTCHA_TIMEOUT_SECONDS)
    pending = _pending.pop(key, None)
    if pending is None:
        return  # already answered
    chat_id, user_id = key
    try:
        await bot.decline_chat_join_request(chat_id, user_id)
    except Exception:
        pass
    try:
        await bot.edit_message_text(
            "⏰ زمان تمام شد و درخواست عضویت شما رد شد. می‌توانید دوباره درخواست بدهید.",
            chat_id=pending.dm_chat_id, message_id=pending.dm_message_id,
        )
    except Exception:
        pass


@bot.callback_query_handler(func=lambda c: c.data.startswith("cap:"))
async def handle_captcha_answer(call: CallbackQuery):
    _, chat_id_str, user_id_str, chosen_str, correct_str = call.data.split(":")
    chat_id, user_id, chosen, correct = int(chat_id_str), int(user_id_str), int(chosen_str), int(correct_str)

    if call.from_user.id != user_id:
        await bot.answer_callback_query(call.id, "این کپچا برای شما نیست.", show_alert=True)
        return

    key = (chat_id, user_id)
    pending = _pending.pop(key, None)
    if pending and pending.timeout_task:
        pending.timeout_task.cancel()

    await bot.answer_callback_query(call.id)

    if chosen == correct:
        try:
            await bot.approve_chat_join_request(chat_id, user_id)
            await bot.edit_message_text(
                "✅ آفرین، درست بود! درخواست عضویت شما تایید شد.",
                chat_id=call.message.chat.id, message_id=call.message.message_id,
            )
        except Exception as e:
            await bot.edit_message_text(
                f"⚠️ پاسخ درست بود اما تایید خودکار با خطا مواجه شد ({e}). لطفاً به ادمین‌های گروه اطلاع دهید.",
                chat_id=call.message.chat.id, message_id=call.message.message_id,
            )
    else:
        try:
            await bot.decline_chat_join_request(chat_id, user_id)
        except Exception:
            pass
        await bot.edit_message_text(
            "❌ پاسخ اشتباه بود. درخواست عضویت شما رد شد؛ می‌توانید دوباره درخواست بدهید.",
            chat_id=call.message.chat.id, message_id=call.message.message_id,
        )