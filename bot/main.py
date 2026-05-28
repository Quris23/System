"""
SYSTEM Telegram Bot  —  entry point.
Stack: Python 3.12, aiogram 3, Groq (llama-3.3-70b), SQLite
"""
import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message

from config import TELEGRAM_TOKEN
from db import init_db, save_reminder, list_reminders
from agent import Agent
from scheduler import run_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot = Bot(token=TELEGRAM_TOKEN)
dp  = Dispatcher()
agent = Agent()


# ── Commands ───────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message):
    name = msg.from_user.first_name or "Игрок"
    await msg.answer(
        f"⚡ Привет, {name}!\n\n"
        "Я — твой личный ИИ-ассистент системы SYSTEM.\n\n"
        "Что умею:\n"
        "• Отвечать на вопросы с учётом твоих целей\n"
        "• Помогать писать тексты (пост, письмо, эссе)\n"
        "• Ставить напоминания — просто скажи когда и о чём\n\n"
        "Примеры:\n"
        "«напомни завтра в 10 про встречу с куратором»\n"
        "«напиши пост про мою учёбу»\n"
        "«что мне нужно сдать по мет. оптимизации?»\n\n"
        "Просто пиши 👇"
    )


@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "📖 Команды:\n\n"
        "/start — приветствие\n"
        "/help — эта справка\n"
        "/reminders — активные напоминания\n\n"
        "Бот помнит последние 10 сообщений диалога.\n"
        "Для переключения провайдера ИИ — измени AI_PROVIDER в .env."
    )


@dp.message(Command("reminders"))
async def cmd_reminders(msg: Message):
    rows = await list_reminders(msg.from_user.id)
    if not rows:
        await msg.answer("Нет активных напоминаний.")
        return
    lines = ["⏰ Активные напоминания:\n"]
    for r in rows:
        lines.append(f"• {r['remind_at'][:16]}  —  {r['text']}")
    await msg.answer("\n".join(lines))


# ── Main message handler ───────────────────────────────────────────────────────

@dp.message(F.text)
async def on_message(msg: Message):
    user_id = msg.from_user.id

    await msg.bot.send_chat_action(msg.chat.id, "typing")

    try:
        text, reminder = await agent.handle(user_id, msg.text)

        if reminder:
            await save_reminder(user_id, reminder["remind_at"], reminder["text"])
            logger.info(f"Reminder saved for user {user_id}: {reminder}")

        await msg.answer(text)

    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}", exc_info=True)
        await msg.answer("Произошла ошибка. Попробуй ещё раз.")


# ── Startup ────────────────────────────────────────────────────────────────────

async def main():
    await init_db()
    logger.info("Database ready")

    asyncio.create_task(run_scheduler(bot))

    logger.info("Bot polling started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
