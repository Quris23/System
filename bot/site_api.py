"""
SYSTEM site API client.

Currently returns stub data.
When backend endpoint is ready — replace get_user_context() with a real aiohttp call.

Expected endpoint: GET {SITE_API_URL}/api/context
Response JSON shape:
{
  "global_goals": ["..."],
  "daily_quests": [{"title": "...", "description": "..."}],
  "planned":      [{"title": "...", "deadline": "YYYY-MM-DD", "system": "..."}]
}
"""
import aiohttp
from config import SITE_API_URL

# ── Stub data (replace with real API later) ───────────────────────────────────

STUB_CONTEXT = {
    "global_goals": [
        "Сдать сессию по Методам Оптимизации",
        "Поддерживать здоровые ежедневные привычки",
        "Развивать навыки программирования",
    ],
    "daily_quests": [
        {"title": "Вечерняя Рутина",    "description": "Умыться, почистить зубы, витамины"},
        {"title": "Дефицит Каллорий",   "description": "+12 ✦"},
    ],
    "planned": [
        {"title": "Метод Ньютона: теория + Вариант 3",  "deadline": "2026-06-01", "system": "Мет Оптов"},
        {"title": "Самостоятельно решить транспортную задачу", "deadline": "2026-06-10", "system": "Мет Оптов"},
    ],
}


async def get_user_context(user_id: int | None = None) -> dict:
    """
    Load user context.
    TODO: uncomment real request when API endpoint is ready.
    """
    # ─── Real request (uncomment when ready) ──────────────────────────────────
    # try:
    #     async with aiohttp.ClientSession() as session:
    #         async with session.get(
    #             f"{SITE_API_URL}/api/context",
    #             params={"user_id": user_id},
    #             timeout=aiohttp.ClientTimeout(total=5),
    #         ) as resp:
    #             resp.raise_for_status()
    #             return await resp.json()
    # except Exception as e:
    #     print(f"[site_api] Failed to fetch context: {e}, using stub")
    # ─────────────────────────────────────────────────────────────────────────
    return STUB_CONTEXT


def format_context(ctx: dict) -> str:
    """Render context dict as plain text for system prompt."""
    parts: list[str] = []

    if ctx.get("global_goals"):
        parts.append("🎯 Глобальные цели пользователя:")
        parts.extend(f"  • {g}" for g in ctx["global_goals"])

    if ctx.get("daily_quests"):
        parts.append("\n📋 Активные ежедневные квесты:")
        for q in ctx["daily_quests"]:
            desc = f" — {q['description']}" if q.get("description") else ""
            parts.append(f"  • {q['title']}{desc}")

    if ctx.get("planned"):
        parts.append("\n⏰ Ближайшие дедлайны:")
        for p in ctx["planned"]:
            parts.append(f"  • {p['title']}  [{p.get('deadline','?')}]  ({p.get('system','')})")

    return "\n".join(parts) if parts else "Данные о целях не загружены."
