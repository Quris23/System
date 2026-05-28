"""
Agent — секретарь-напоминалка.
Понимает задачи на естественном языке, сохраняет в БД, отвечает о дедлайнах.
"""
import json
import re
import logging
from datetime import datetime
from providers import get_provider
from db import get_history, save_message
from site_api import get_user_context, format_context

logger = logging.getLogger(__name__)

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
Ты — личный секретарь-ассистент пользователя в системе SYSTEM.
Общайся на русском, кратко и по делу. Без лишних слов.

КОНТЕКСТ ПОЛЬЗОВАТЕЛЯ (из его системы целей):
{context}

ТЕКУЩАЯ ДАТА И ВРЕМЯ: {now}

═══════════════════════════════════════════════════════
ПРАВИЛА:

1. ЗАПИСАТЬ ЗАДАЧУ / НАПОМИНАНИЕ
   Если пользователь говорит что-то вроде:
   «напомни», «запомни», «не забудь», «поставь задачу», «запиши»,
   «встреча в 10», «сдать до пятницы», «завтра надо» и т.д. —
   распознай и ответь КОРОТКО по-русски + добавь JSON-блок в конце:
   {"action":"set_reminder","remind_at":"YYYY-MM-DD HH:MM","text":"текст задачи"}

   Правила времени:
   - «завтра в 10» → следующий день 10:00
   - «через 2 часа» → текущее время + 2ч
   - «в пятницу в 15» → ближайшая пятница 15:00
   - «сегодня вечером» → сегодня 20:00
   - Если время не указано → 09:00 указанного дня

2. ПОКАЗАТЬ ЗАДАЧИ
   Если пользователь спрашивает «что у меня», «мои задачи», «список», «что надо сделать» —
   ответь что список покажет команда /tasks.

3. ОБЫЧНЫЙ ВОПРОС
   Просто ответь кратко. Учитывай цели пользователя из контекста.
═══════════════════════════════════════════════════════\
"""


class Agent:
    def __init__(self):
        self.provider = get_provider()

    async def handle(self, user_id: int, text: str) -> tuple[str, dict | None]:
        """
        Returns (response_text, reminder_dict | None)
        reminder_dict = {"remind_at": datetime, "text": str}
        """
        ctx = await get_user_context(user_id)
        system = SYSTEM_PROMPT.format(
            context=format_context(ctx),
            now=datetime.now().strftime("%d.%m.%Y %H:%M, %A"),
        )

        history = await get_history(user_id, limit=10)
        history.append({"role": "user", "content": text})

        response = await self.provider.complete(history, system)

        await save_message(user_id, "user", text)
        await save_message(user_id, "assistant", response)

        reminder = _extract_reminder(response)
        return response, reminder


# ── Reminder extraction ───────────────────────────────────────────────────────

def _extract_reminder(response: str) -> dict | None:
    try:
        match = re.search(r'\{[^{}]*"action"\s*:\s*"set_reminder"[^{}]*\}', response)
        if not match:
            return None
        data = json.loads(match.group())
        remind_at = datetime.strptime(data["remind_at"], "%Y-%m-%d %H:%M")
        return {"remind_at": remind_at, "text": data.get("text", "Напоминание")}
    except Exception as e:
        logger.debug(f"Reminder parse failed: {e}")
        return None
