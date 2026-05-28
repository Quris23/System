"""
Agent: conversation logic, intent detection, writing mode, reminder extraction.
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
Ты — личный ИИ-ассистент пользователя в системе SYSTEM (геймифицированный жизненный менеджер).
Ты помогаешь достигать целей, отвечаешь на вопросы, помогаешь писать тексты и ставишь напоминания.
Общайся на русском, лаконично и по делу. В Telegram не используй **жирный** через звёздочки.

КОНТЕКСТ ПОЛЬЗОВАТЕЛЯ:
{context}

ТЕКУЩАЯ ДАТА И ВРЕМЯ: {now}

─── Правила ───────────────────────────────────────────────────────────────────
1. НАПОМИНАНИЕ: Если пользователь просит напомнить о чём-то — ответь на русском
   и в конце добавь JSON-блок (без markdown-обёртки):
   {{"action":"set_reminder","remind_at":"YYYY-MM-DD HH:MM","text":"текст"}}

2. НАПИСАНИЕ ТЕКСТА: Если пользователь хочет написать текст (пост, письмо, эссе и т.д.) —
   не пиши текст сразу. Задай ровно 2-3 уточняющих вопроса нумерованным списком.

3. ОБЫЧНЫЙ ВОПРОС: Просто ответь.
───────────────────────────────────────────────────────────────────────────────\
"""

WRITING_TRIGGERS = {
    "напиши", "написать", "напишем", "напишите", "составь",
    "придумай текст", "придумай пост", "помоги написать",
    "помоги с текстом", "сгенерируй", "сочини",
}

REMINDER_TRIGGERS = {
    "напомни", "напомните", "поставь напоминание", "напомни мне",
    "не забудь напомнить",
}


# ── Agent class ────────────────────────────────────────────────────────────────

class Agent:
    def __init__(self):
        self.provider = get_provider()
        # user_id -> {"original": str}  — tracks active writing sessions
        self._writing: dict[int, dict] = {}

    async def handle(self, user_id: int, text: str) -> tuple[str, dict | None]:
        """
        Process one user message.
        Returns (response_text, reminder_dict | None).
        reminder_dict = {"remind_at": datetime, "text": str}
        """
        ctx = await get_user_context(user_id)
        system = SYSTEM_PROMPT.format(
            context=format_context(ctx),
            now=datetime.now().strftime("%d.%m.%Y %H:%M, %A"),
        )

        text_lower = text.lower()

        # ── Writing mode: clarify ──
        if any(t in text_lower for t in WRITING_TRIGGERS) and user_id not in self._writing:
            return await self._writing_clarify(user_id, text, system)

        # ── Writing mode: generate ──
        if user_id in self._writing:
            return await self._writing_generate(user_id, text, system)

        # ── Normal conversation ──
        return await self._chat(user_id, text, system)

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _chat(self, user_id: int, text: str, system: str) -> tuple[str, dict | None]:
        history = await get_history(user_id, limit=10)
        history.append({"role": "user", "content": text})

        response = await self.provider.complete(history, system)

        await save_message(user_id, "user", text)
        await save_message(user_id, "assistant", response)

        reminder = _extract_reminder(response)
        return response, reminder

    async def _writing_clarify(self, user_id: int, text: str, system: str) -> tuple[str, None]:
        self._writing[user_id] = {"original": text}

        history = await get_history(user_id, limit=4)
        history.append({"role": "user", "content": text})

        extra = "\n\nПользователь хочет написать текст. Задай ровно 2-3 уточняющих вопроса нумерованным списком — больше ничего не пиши."
        questions = await self.provider.complete(history, system + extra)

        await save_message(user_id, "user", text)
        await save_message(user_id, "assistant", questions)
        return questions, None

    async def _writing_generate(self, user_id: int, answers: str, system: str) -> tuple[str, None]:
        session = self._writing.pop(user_id)

        history = await get_history(user_id, limit=6)
        history.append({"role": "user", "content": answers})

        extra = (
            f"\n\nНапиши текст по запросу «{session['original']}» "
            "с учётом ответов пользователя и его целей. Пиши сразу готовый текст."
        )
        result = await self.provider.complete(history, system + extra)

        await save_message(user_id, "user", answers)
        await save_message(user_id, "assistant", result)
        return result, None


# ── Reminder extraction ────────────────────────────────────────────────────────

def _extract_reminder(response: str) -> dict | None:
    """Parse reminder JSON embedded in the LLM response."""
    try:
        match = re.search(
            r'\{\s*"action"\s*:\s*"set_reminder"[^}]+\}',
            response,
        )
        if not match:
            return None
        data = json.loads(match.group())
        remind_at = datetime.strptime(data["remind_at"], "%Y-%m-%d %H:%M")
        text = data.get("text", "Напоминание")
        return {"remind_at": remind_at, "text": text}
    except Exception as e:
        logger.debug(f"Reminder extraction failed: {e}")
        return None
