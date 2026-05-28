"""
SYSTEM Telegram Bot — личный секретарь с очками и редактированием задач.
"""
import asyncio
import logging
import re as _re
from datetime import datetime

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from config import TELEGRAM_TOKEN
from db import (
    init_db, save_reminder, list_reminders,
    mark_reminder_sent, get_reminder, update_reminder,
)
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

# user_id → {"mode": "text"|"time"|"points", "task_id": int, "msg_id": int}
_edit_state: dict[int, dict] = {}


# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message):
    name = msg.from_user.first_name or "Игрок"
    await msg.answer(
        f"⚡ Привет, {name}!\n\n"
        "Я — твой личный секретарь.\n\n"
        "Просто пиши задачи:\n"
        "• «напомни завтра в 10 про встречу»\n"
        "• «в пятницу в 18 сдать лабу по мет. оптим.»\n"
        "• «через 2 часа позвонить маме»\n\n"
        "Я сам оценю задачу в очках по твоей системе.\n\n"
        "/tasks — список задач\n"
        "/help — справка"
    )


# ── /help ─────────────────────────────────────────────────────────────────────

@dp.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer(
        "📖 Команды:\n\n"
        "/tasks — активные задачи\n"
        "/start — приветствие\n\n"
        "В каждой задаче есть кнопки:\n"
        "✅ Выполнено — закрыть задачу\n"
        "✏️ Текст — изменить описание\n"
        "🕐 Время — изменить дату/время\n"
        "💎 Очки — изменить количество очков"
    )


# ── /tasks ────────────────────────────────────────────────────────────────────

@dp.message(Command("tasks"))
async def cmd_tasks(msg: Message):
    await show_tasks(msg.from_user.id, msg)


async def show_tasks(user_id: int, msg: Message):
    rows = await list_reminders(user_id)
    if not rows:
        await msg.answer("Нет активных задач. Просто напиши что запомнить 👇")
        return
    for r in rows:
        await msg.answer(
            _task_text(r),
            reply_markup=_task_kb(r["id"]),
        )


def _task_text(r: dict) -> str:
    dt = r["remind_at"][:16]
    pts = f"+{r['points']} ✦" if r.get("points") else "без очков"
    return f"🗓 {dt}  |  {pts}\n{r['text']}"


def _task_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Выполнено", callback_data=f"done:{task_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Текст",  callback_data=f"edit_text:{task_id}"),
            InlineKeyboardButton(text="🕐 Время",  callback_data=f"edit_time:{task_id}"),
            InlineKeyboardButton(text="💎 Очки",   callback_data=f"edit_pts:{task_id}"),
        ],
    ])


# ── Callbacks ─────────────────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("done:"))
async def cb_done(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    task = await get_reminder(task_id)
    pts_text = f"  +{task['points']} ✦ начислено!" if task and task.get("points") else ""
    await mark_reminder_sent(task_id)
    await cb.message.edit_text(
        f"✅ Выполнено!{pts_text}\n\n~~{cb.message.text}~~",
        reply_markup=None,
    )
    await cb.answer("Готово!")


@dp.callback_query(F.data.startswith("edit_text:"))
async def cb_edit_text(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    _edit_state[cb.from_user.id] = {"mode": "text", "task_id": task_id, "msg_id": cb.message.message_id}
    await cb.message.answer("✏️ Введи новый текст задачи:")
    await cb.answer()


@dp.callback_query(F.data.startswith("edit_time:"))
async def cb_edit_time(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    _edit_state[cb.from_user.id] = {"mode": "time", "task_id": task_id, "msg_id": cb.message.message_id}
    await cb.message.answer(
        "🕐 Введи новую дату и время:\n"
        "Примеры: «завтра в 11», «2026-06-05 14:00», «в пятницу в 9»"
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("edit_pts:"))
async def cb_edit_pts(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    _edit_state[cb.from_user.id] = {"mode": "points", "task_id": task_id, "msg_id": cb.message.message_id}
    await cb.message.answer(
        "💎 Введи количество очков (число):\n"
        "Система: мелкая=5, средняя=10, крупная=20, блок лёгкий=20, средний=40, тяжёлый=80"
    )
    await cb.answer()


# ── Основной обработчик ───────────────────────────────────────────────────────

@dp.message(F.text)
async def on_message(msg: Message):
    user_id = msg.from_user.id

    # Режим редактирования
    if user_id in _edit_state:
        await handle_edit(msg)
        return

    await msg.bot.send_chat_action(msg.chat.id, "typing")

    try:
        text, reminder = await agent.handle(user_id, msg.text)
        clean = _strip_json(text)

        if reminder:
            await save_reminder(
                user_id,
                reminder["remind_at"],
                reminder["text"],
                reminder.get("points", 0),
            )
            pts = reminder.get("points", 0)
            pts_line = f"\n💎 Оценка: +{pts} ✦" if pts else ""
            logger.info(f"Reminder saved: uid={user_id} at={reminder['remind_at']} pts={pts}")
            await msg.answer((clean or "Записал!") + pts_line)
        else:
            await msg.answer(clean or "Записал!")

    except Exception as e:
        logger.error(f"Error for user {user_id}: {e}", exc_info=True)
        await msg.answer("Произошла ошибка. Попробуй ещё раз.")


# ── Edit handler ──────────────────────────────────────────────────────────────

async def handle_edit(msg: Message):
    user_id = msg.from_user.id
    state = _edit_state.pop(user_id)
    task_id = state["task_id"]
    mode    = state["mode"]

    task = await get_reminder(task_id)
    if not task:
        await msg.answer("Задача не найдена.")
        return

    if mode == "text":
        await update_reminder(task_id, text=msg.text.strip())
        task["text"] = msg.text.strip()
        await msg.answer(
            f"✅ Текст обновлён:\n\n{_task_text(task)}",
            reply_markup=_task_kb(task_id),
        )

    elif mode == "time":
        dt_str = _parse_datetime(msg.text.strip())
        if not dt_str:
            await msg.answer(
                "Не понял формат. Попробуй: «завтра в 11», «2026-06-05 14:00»"
            )
            return
        await update_reminder(task_id, remind_at=dt_str)
        task["remind_at"] = dt_str
        await msg.answer(
            f"✅ Время обновлено:\n\n{_task_text(task)}",
            reply_markup=_task_kb(task_id),
        )

    elif mode == "points":
        try:
            pts = int(_re.search(r'\d+', msg.text).group())
        except Exception:
            await msg.answer("Введи число, например: 10")
            return
        await update_reminder(task_id, points=pts)
        task["points"] = pts
        await msg.answer(
            f"✅ Очки обновлены:\n\n{_task_text(task)}",
            reply_markup=_task_kb(task_id),
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _strip_json(text: str) -> str:
    return _re.sub(r'\{[^{}]*"action"\s*:\s*"set_reminder"[^{}]*\}', '', text).strip()


def _parse_datetime(text: str) -> str | None:
    """
    Пытается распарсить дату из текста.
    Поддерживает: YYYY-MM-DD HH:MM, DD.MM.YYYY HH:MM
    Для нечётких форматов («завтра в 11») возвращает None — пусть ИИ обработает.
    """
    # ISO format
    m = _re.search(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})', text)
    if m:
        return f"{m.group(1)} {m.group(2)}:00"
    # RU format DD.MM.YYYY HH:MM
    m = _re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})', text)
    if m:
        d, mo, y, h, mi = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:00"
    # "завтра в 11" / "сегодня в 14:30" — natural language
    now = datetime.now()
    m_h = _re.search(r'(\d{1,2})(?::(\d{2}))?', text)
    hour = int(m_h.group(1)) if m_h else 9
    minute = int(m_h.group(2)) if m_h and m_h.group(2) else 0
    if "завтра" in text:
        from datetime import timedelta
        d = now + timedelta(days=1)
        return f"{d.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00"
    if "сегодня" in text or "через" not in text:
        return f"{now.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00"
    return None


# ── Startup ───────────────────────────────────────────────────────────────────

async def main():
    await init_db()
    logger.info("Database ready")
    asyncio.create_task(run_scheduler(bot))
    logger.info("Bot polling started")
    await dp.start_polling(bot, skip_updates=True)


if __name__ == "__main__":
    asyncio.run(main())
