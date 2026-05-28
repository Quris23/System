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
    Найти запись user_state по telegram_id, хранящемуся в player.telegram_id внутри JSONB state.
    Фильтруем в Python — надёжнее, чем вложенный JSONB-фильтр в URL.
    """
    if not _configured():
        return None
    url = f"{SUPABASE_URL}/rest/v1/user_state?select=user_id,state"
    async with aiohttp.ClientSession() as s:
        async with s.get(url, headers=_HEADERS) as r:
            rows = await r.json()
    if not isinstance(rows, list):
        return None
    tg_id_str = str(telegram_id)
    for row in rows:
        state  = row.get("state") or {}
        player = state.get("player") or {}
        stored = player.get("telegram_id")
        if stored is not None and str(stored) == tg_id_str:
            return row["user_id"], state
    return None


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
                    "id":           q["id"],
                    "title":        q["title"],
                    "deadline":     dl,          # YYYY-MM-DD
                    "reward":       q.get("reward", 0),
                    "system_title": sys["title"],
                    "block_title":  blk["title"],
                })
    quests.sort(key=lambda q: q["deadline"])
    return quests


async def mark_quest_done(telegram_id: int, quest_id: str) -> bool:
    """Пометить квест как выполненный в Supabase."""
    result = await _get_state_by_tg(telegram_id)
    if not result:
        return False
    user_id, state = result

    marked = False
    for sys in state.get("systems", []):
        for blk in sys.get("blocks", []):
            for q in blk.get("quests", []):
                if q.get("id") == quest_id:
                    q["done"] = True
                    marked = True
                    break
            if marked:
                break
        if marked:
            break

    if not marked:
        # Поищем в notes
        for n in state.get("notes", []):
            if n.get("id") == quest_id:
                n["done"] = True
                marked = True
                break

    if not marked:
        return False

    url = f"{SUPABASE_URL}/rest/v1/user_state?user_id=eq.{user_id}"
    payload = {"state": state, "updated_at": datetime.now(timezone.utc).isoformat()}
    async with aiohttp.ClientSession() as s:
        async with s.patch(url, headers=_HEADERS, json=payload) as r:
            return r.status in (200, 204)


async def update_quest(telegram_id: int, quest_id: str,
                       title: str | None = None,
                       deadline: str | None = None,
                       reward: int | None = None) -> bool:
    """Обновить поля квеста или заметки в Supabase."""
    result = await _get_state_by_tg(telegram_id)
    if not result:
        return False
    user_id, state = result

    updated = False
    for src_list in [
        [q for sys in state.get("systems", []) for blk in sys.get("blocks", []) for q in blk.get("quests", [])],
        state.get("notes", []),
    ]:
        for item in src_list:
            if item.get("id") == quest_id:
                if title    is not None: item["title"]    = title
                if deadline is not None: item["deadline"] = deadline[:10]
                if reward   is not None: item["reward"]   = reward
                updated = True
                break
        if updated:
            break

    if not updated:
        return False

    url = f"{SUPABASE_URL}/rest/v1/user_state?user_id=eq.{user_id}"
    payload = {"state": state, "updated_at": datetime.now(timezone.utc).isoformat()}
    async with aiohttp.ClientSession() as s:
        async with s.patch(url, headers=_HEADERS, json=payload) as r:
            return r.status in (200, 204)


async def add_note(telegram_id: int, title: str, deadline: str, reward: int) -> bool:
    """
    Добавить заметку в state.notes (без привязки к системе).
    Отображается в разделе «Запланированные» на сайте.
    """
    result = await _get_state_by_tg(telegram_id)
    if not result:
        return False
    user_id, state = result

    note = {
        "id":           _uid(),
        "title":        title,
        "description":  "",
        "deadline":     deadline[:10],  # YYYY-MM-DD
        "remindBefore": "",
        "reward":       reward,
        "done":         False,
    }
    state.setdefault("notes", []).append(note)

    url = f"{SUPABASE_URL}/rest/v1/user_state?user_id=eq.{user_id}"
    payload = {
        "state":      state,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    async with aiohttp.ClientSession() as s:
        async with s.patch(url, headers=_HEADERS, json=payload) as r:
            return r.status in (200, 204)


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
