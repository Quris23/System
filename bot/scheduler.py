"""
Reminder scheduler.
Runs as a background asyncio task, checks every 60 s for due reminders.
"""
import asyncio
import logging
from datetime import datetime

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

from db import get_due_reminders, mark_reminder_sent

logger = logging.getLogger(__name__)


def _reminder_kb(reminder_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Выполнено", callback_data=f"done:{reminder_id}"),
        InlineKeyboardButton(text="❌ Отмена",    callback_data=f"remind_dismiss:{reminder_id}"),
    ]])


async def check_reminders(bot) -> int:
    """Send all overdue reminders. Returns count of sent messages."""
    now = datetime.now()
    reminders = await get_due_reminders(now)
    sent = 0
    for r in reminders:
        try:
            pts_text = f"  (+{r['points']} ✦)" if r.get("points") else ""
            await bot.send_message(
                chat_id=r["user_id"],
                text=f"🔔 <b>Напоминание:</b> {r['text']}{pts_text}",
                parse_mode="HTML",
                reply_markup=_reminder_kb(r["id"]),
            )
            await mark_reminder_sent(r["id"])
            sent += 1
            logger.info(f"Reminder {r['id']} sent to user {r['user_id']}")
        except Exception as e:
            logger.warning(f"Failed to send reminder {r['id']} to {r['user_id']}: {e}")
    return sent


async def run_scheduler(bot, interval: int = 60):
    """Background loop. Pass interval in seconds (default 60)."""
    logger.info(f"[Scheduler] Started (interval={interval}s)")
    while True:
        try:
            await check_reminders(bot)
        except Exception as e:
            logger.error(f"[Scheduler] Unexpected error: {e}", exc_info=True)
        await asyncio.sleep(interval)
