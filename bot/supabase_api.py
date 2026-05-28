"""
Supabase API — чтение систем/блоков и запись задач в SYSTEM.
Использует service_role key (обходит RLS).
Пользователь ищется по telegram_id, хранящемуся в player.telegram_id внутри JSONB state.
"""
import uuid
import aiohttp
from datetime import datetime, timezone
from config import SUPABASE_URL, SUPABASE_SERVICE_KEY

_HEADERS = {
    "apikey": SUPABASE_SERVICE_KEY,
    "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
    "Content-Type": "application/json",
}

def _uid() -> str:
    return uuid.uuid4().hex[:16]

def _configured() -> bool:
    return bool(SUPABASE_SERVICE_KEY)


async def _get_state_by_tg(telegram_id: int) -> tuple[str, dict] | None:
    """
    Найти запись user_state по telegram_id, хранящемуся в state->player->>telegram_id.
    Возвращает (user_id, state) или None если не найдено.
    """
    if not _configured():
        return None
    url = (
        f"{SUPABASE_URL}/rest/v1/user_state"
        f"?state->player->>telegram_id=eq.{telegram_id}"
        f"&select=user_id,state"
    )
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=_HEADERS) as r:
            rows = await r.json()
    if not rows:
        return None
    return rows[0]["user_id"], rows[0]["state"]


async def get_systems(telegram_id: int) -> list[dict]:
    """Вернуть список систем [{id, title, color, blocks:[{id, title}]}]."""
    result = await _get_state_by_tg(telegram_id)
    if not result:
        return []
    _, state = result
    return state.get("systems", [])


async def get_upcoming_quests(telegram_id: int) -> list[dict]:
    """
    Вернуть все незавершённые квесты с дедлайном из всех систем/блоков.
    Каждый элемент: {title, deadline, reward, system_title, block_title}
    Отсортировано по дедлайну.
    """
    result = await _get_state_by_tg(telegram_id)
    if not result:
        return []
    _, state = result
    quests = []
    for sys in state.get("systems", []):
        for blk in sys.get("blocks", []):
            for q in blk.get("quests", []):
                if q.get("done"):
                    continue
                dl = q.get("deadline", "")
                if not dl:
                    continue
                quests.append({
                    "title":        q["title"],
                    "deadline":     dl,          # YYYY-MM-DD
                    "reward":       q.get("reward", 0),
                    "system_title": sys["title"],
                    "block_title":  blk["title"],
                })
    quests.sort(key=lambda q: q["deadline"])
    return quests


async def add_quest_to_block(telegram_id: int, system_id: str, block_id: str,
                              title: str, deadline: str, reward: int) -> bool:
    """
    Добавить квест в блок.
    deadline — строка "YYYY-MM-DD HH:MM:SS", в базу пишется только дата.
    """
    result = await _get_state_by_tg(telegram_id)
    if not result:
        return False
    user_id, state = result

    quest = {
        "id":          _uid(),
        "title":       title,
        "description": "",
        "deadline":    deadline[:10],   # только YYYY-MM-DD
        "reward":      reward,
        "done":        False,
    }

    inserted = False
    for sys in state.get("systems", []):
        if sys["id"] == system_id:
            for blk in sys.get("blocks", []):
                if blk["id"] == block_id:
                    blk.setdefault("quests", []).append(quest)
                    inserted = True
                    break
        if inserted:
            break

    if not inserted:
        return False

    url = f"{SUPABASE_URL}/rest/v1/user_state?user_id=eq.{user_id}"
    payload = {
        "state":      state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    async with aiohttp.ClientSession() as s:
        async with s.patch(url, headers=_HEADERS, json=payload) as r:
            return r.status in (200, 204)
