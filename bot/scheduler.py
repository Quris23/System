"""
Reminder scheduler.
Runs as a background asyncio task, checks every 60 s for due reminders.
"""
import asyncio
import logging
from datetime import datetime
from db import get_due_reminders, mark_reminder_sent

logger = logging.getLogger(__name__)


async def check_reminders(bot) -> int:
    """Send all overdue reminders. Returns count of sent messages."""
    now = datetime.now()
    reminders = await get_due_reminders(now)
    sent = 0
    for r in reminders:
        try:
            await bot.send_message(
                chat_id=r["user_id"],
                text=f"🔔 Напоминание: {r['text']}",
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
