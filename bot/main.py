"""
SYSTEM Telegram Bot — личный секретарь.
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from config import TELEGRAM_TOKEN
from db import init_db, save_reminder, list_reminders, mark_reminder_sent
from agent import Agent
from scheduler import run_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot   = Bot(token=TELEGRAM_TOKEN)
dp    = Dispatcher()
agent = Agent()


# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message):
    name = msg.from_user.first_name or "Игрок"
    await msg.answer(
        f"⚡ Привет, {name}!\n\n"
        "Я — твой личный секретарь.\n\n"
        "Просто пиши мне задачи:\n"
        "• «напомни завтра в 10 про встречу с куратором»\n"
        "• «в пятницу в 18 сдать лабу по мет. оптим.»\n"
        "• «через 2 часа позвонить маме»\n\n"
        "Команды:\n"
        "/tasks — список активных задач\n"
        "/help — справка"
    )


# ── /help ─────────────────────────────────────────────────────────────────────

@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "📖 Команды:\n\n"
        "/tasks — активные задачи\n"
        "/start — приветствие\n\n"
        "Как ставить задачи — просто пиши:\n"
        "«напомни завтра в 9 про зарядку»\n"
        "«не забыть в среду в 14 сдать реферат»\n"
        "«через час позвонить в деканат»"
    )


# ── /tasks ────────────────────────────────────────────────────────────────────

@dp.message(Command("tasks"))
async def cmd_tasks(msg: Message):
    await show_tasks(msg.from_user.id, msg)


async def show_tasks(user_id: int, msg: Message):
    rows = await list_reminders(user_id)
    if not rows:
        await msg.answer("Нет активных задач. Просто напиши мне что запомнить 👇")
        return

    for r in rows:
        dt = r["remind_at"][:16]   # "YYYY-MM-DD HH:MM"
        text = f"🗓 {dt}\n{r['text']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✅ Выполнено", callback_data=f"done:{r['id']}"),
        ]])
        await msg.answer(text, reply_markup=kb)


# ── Inline: отметить выполненным ──────────────────────────────────────────────

@dp.callback_query(F.data.startswith("done:"))
async def cb_done(cb: CallbackQuery):
    reminder_id = int(cb.data.split(":")[1])
    await mark_reminder_sent(reminder_id)
    await cb.message.edit_text(
        cb.message.text + "\n\n✅ Выполнено",
        reply_markup=None,
    )
    await cb.answer("Готово!")


# ── Основной обработчик сообщений ─────────────────────────────────────────────

@dp.message(F.text)
async def on_message(msg: Message):
    user_id = msg.from_user.id
    await msg.bot.send_chat_action(msg.chat.id, "typing")

    try:
        text, reminder = await agent.handle(user_id, msg.text)

        # Убираем JSON-блок из ответа пользователю
        clean = _strip_json(text)

        if reminder:
            await save_reminder(user_id, reminder["remind_at"], reminder["text"])
            logger.info(f"Reminder saved: user={user_id} at={reminder['remind_at']} text={reminder['text']!r}")

        await msg.answer(clean or "Записал!")

    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}", exc_info=True)
        await msg.answer("Произошла ошибка. Попробуй ещё раз.")


# ── Helpers ───────────────────────────────────────────────────────────────────

import re as _re

def _strip_json(text: str) -> str:
    """Remove the embedded JSON block from the LLM response before sending to user."""
    return _re.sub(r'\{[^{}]*"action"\s*:\s*"set_reminder"[^{}]*\}', '', text).strip()


# ── Startup ───────────────────────────────────────────────────────────────────

async def main():
    await init_db()
    logger.info("Database ready")
    asyncio.create_task(run_scheduler(bot))
    logger.info("Bot polling started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
