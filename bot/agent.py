"""
Agent — секретарь-напоминалка с авто-оценкой очков.
"""
import json
import re
import logging
from datetime import datetime
from providers import get_provider
from db import get_history, save_message
from site_api import get_user_context, format_context

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
Ты — личный секретарь-ассистент пользователя в системе SYSTEM (геймифицированный планировщик).
Общайся на русском, кратко. Без лишних слов.

КОНТЕКСТ ПОЛЬЗОВАТЕЛЯ:
{context}

ТЕКУЩАЯ ДАТА И ВРЕМЯ: {now}

═══════════════════════════════════════════════════════
СИСТЕМА ОЧКОВ (используй для auto-оценки задач):

Задача мелкая  (до 30 мин):          5 очков
Задача средняя (30 мин – 2 ч):       10 очков
Задача крупная (2 ч+):               20 очков
Блок лёгкий    (несколько часов):    20 очков
Блок средний   (1–3 дня):            40 очков
Блок тяжёлый   (неделя+):            80 очков
Daily (каждый день):                 8 очков
Weekly (каждую неделю):              20 очков
Периодическое:                       12 очков

═══════════════════════════════════════════════════════
ПРАВИЛА:

1. ЗАПИСАТЬ ЗАДАЧУ
   Если пользователь говорит «напомни», «запиши», «не забудь», называет время и задачу —
   ответь коротко по-русски (1–2 предложения) и добавь JSON в конце:
   {"action":"set_reminder","remind_at":"YYYY-MM-DD HH:MM","text":"текст задачи","points":10}

   Оценивай points по системе выше исходя из смысла задачи.
   Если задача явно крупная (написать курсовую, подготовиться к экзамену) — ставь 20.
   Если мелкая (купить хлеб, позвонить) — ставь 5.
   При неопределённости — 10.

   Правила времени:
   - «завтра в 10» → следующий день 10:00
   - «через 2 часа» → текущее время + 2ч
   - «в пятницу в 15» → ближайшая пятница 15:00
   - «сегодня вечером» → сегодня 20:00
   - Если время не указано → 09:00 указанного дня

2. ПОКАЗАТЬ ЗАДАЧИ
   Если «что у меня», «мои задачи», «список» → ответь что список по команде /tasks.

3. ОБЫЧНЫЙ ВОПРОС
   Просто ответь кратко с учётом целей пользователя.
═══════════════════════════════════════════════════════\
"""


class Agent:
    def __init__(self):
        self.provider = get_provider()

    async def handle(self, user_id: int, text: str) -> tuple[str, dict | None]:
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


def _extract_reminder(response: str) -> dict | None:
    try:
        match = re.search(r'\{[^{}]*"action"\s*:\s*"set_reminder"[^{}]*\}', response)
        if not match:
            return None
        data = json.loads(match.group())
        remind_at = datetime.strptime(data["remind_at"], "%Y-%m-%d %H:%M")
        points = int(data.get("points", 0))
        return {"remind_at": remind_at, "text": data.get("text", "Напоминание"), "points": points}
    except Exception as e:
        logger.debug(f"Reminder parse failed: {e}")
        return None
