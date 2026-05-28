"""
SQLite layer via aiosqlite.
Tables: messages (conversation history), reminders (scheduled tasks).
"""
import aiosqlite
from datetime import datetime
from config import DB_PATH


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                role       TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                created_at TEXT    DEFAULT (datetime('now'))
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                remind_at  TEXT    NOT NULL,
                text       TEXT    NOT NULL,
                points     INTEGER DEFAULT 0,
                sent       INTEGER DEFAULT 0,
                created_at TEXT    DEFAULT (datetime('now'))
            )
        """)
        # Migrate: add points column if missing (for existing DBs)
        try:
            await db.execute("ALTER TABLE reminders ADD COLUMN points INTEGER DEFAULT 0")
        except Exception:
            pass
        await db.execute("CREATE INDEX IF NOT EXISTS idx_msg_user ON messages(user_id, created_at)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_rem_due  ON reminders(remind_at, sent)")
        await db.commit()


# ── History ───────────────────────────────────────────────────────────────────

async def get_history(user_id: int, limit: int = 10) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT role, content FROM messages
               WHERE user_id = ?
               ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ) as cur:
            rows = await cur.fetchall()
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


async def save_message(user_id: int, role: str, content: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO messages (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        await db.execute(
            """DELETE FROM messages WHERE user_id = ? AND id NOT IN (
                   SELECT id FROM messages WHERE user_id = ?
                   ORDER BY created_at DESC LIMIT 20
               )""",
            (user_id, user_id),
        )
        await db.commit()


# ── Reminders / Tasks ─────────────────────────────────────────────────────────

async def save_reminder(user_id: int, remind_at: datetime, text: str, points: int = 0):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO reminders (user_id, remind_at, text, points) VALUES (?, ?, ?, ?)",
            (user_id, remind_at.strftime("%Y-%m-%d %H:%M:%S"), text, points),
        )
        await db.commit()


async def get_reminder(reminder_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, remind_at, text, points FROM reminders WHERE id = ?",
            (reminder_id,),
        ) as cur:
            row = await cur.fetchone()
    if not row:
        return None
    return {"id": row[0], "user_id": row[1], "remind_at": row[2], "text": row[3], "points": row[4]}


async def update_reminder(reminder_id: int, text: str | None = None,
                          remind_at: str | None = None, points: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        if text is not None:
            await db.execute("UPDATE reminders SET text = ? WHERE id = ?", (text, reminder_id))
        if remind_at is not None:
            await db.execute("UPDATE reminders SET remind_at = ? WHERE id = ?", (remind_at, reminder_id))
        if points is not None:
            await db.execute("UPDATE reminders SET points = ? WHERE id = ?", (points, reminder_id))
        await db.commit()


async def get_due_reminders(now: datetime) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, text, points FROM reminders WHERE sent = 0 AND remind_at <= ?",
            (now.strftime("%Y-%m-%d %H:%M:%S"),),
        ) as cur:
            rows = await cur.fetchall()
    return [{"id": r[0], "user_id": r[1], "text": r[2], "points": r[3]} for r in rows]


async def mark_reminder_sent(reminder_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        await db.commit()


async def list_reminders(user_id: int) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id, remind_at, text, points FROM reminders
               WHERE user_id = ? AND sent = 0
               ORDER BY remind_at""",
            (user_id,),
        ) as cur:
            rows = await cur.fetchall()
    return [{"id": r[0], "remind_at": r[1], "text": r[2], "points": r[3]} for r in rows]
