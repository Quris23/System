"""
SYSTEM Telegram Bot — секретарь с панелью кнопок, 4-шаговым созданием задач и записью в SYSTEM.
"""
import asyncio
import logging
import re as _re
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove,
)

from config import TELEGRAM_TOKEN
from db import (
    init_db, save_reminder, list_reminders,
    mark_reminder_sent, get_reminder, update_reminder,
)
from agent import Agent
from scheduler import run_scheduler
from supabase_api import get_systems, add_quest_to_block, get_upcoming_quests, add_note, mark_quest_done, update_quest

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

bot   = Bot(token=TELEGRAM_TOKEN)
dp    = Dispatcher(storage=MemoryStorage())
agent = Agent()


# ── FSM States ────────────────────────────────────────────────────────────────

class CreateTask(StatesGroup):
    info    = State()   # шаг 1: описание
    deadline= State()   # шаг 2: дедлайн
    points  = State()   # шаг 3: сложность (inline)
    planet  = State()   # шаг 4: привязка к системе/блоку (inline)

class EditTask(StatesGroup):
    pass  # редактирование через _edit_state dict


# ── Клавиатуры ────────────────────────────────────────────────────────────────

MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [
            KeyboardButton(text="📝 Создать задачу"),
            KeyboardButton(text="📋 Ближайшие задачи"),
        ],
        [
            KeyboardButton(text="✏️ Изменить задачу"),
        ],
    ],
    resize_keyboard=True,
    persistent=True,
)

POINTS_KB = InlineKeyboardMarkup(inline_keyboard=[
    [InlineKeyboardButton(text="⚡ До 30 мин  — 5 ✦",          callback_data="pts:5")],
    [InlineKeyboardButton(text="🔧 30 мин – 2 ч  — 10 ✦",     callback_data="pts:10")],
    [InlineKeyboardButton(text="🏋️ 2 ч+  — 20 ✦",             callback_data="pts:20")],
    [InlineKeyboardButton(text="📦 Блок / 1–3 дня  — 40 ✦",   callback_data="pts:40")],
    [InlineKeyboardButton(text="🗻 Тяжёлый / неделя+  — 80 ✦", callback_data="pts:80")],
])


async def _systems_kb(telegram_id: int) -> InlineKeyboardMarkup:
    """Кнопки со списком систем + «Без системы»."""
    systems = await get_systems(telegram_id)
    rows = []
    for sys in systems:
        rows.append([InlineKeyboardButton(
            text=f"● {sys['title']}",
            callback_data=f"sys:{sys['id']}",
        )])
    if not rows:
        rows.append([InlineKeyboardButton(
            text="⚠️ Telegram не привязан на сайте",
            callback_data="planet_skip",
        )])
    rows.append([InlineKeyboardButton(text="➡️ Без системы", callback_data="planet_skip")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _blocks_kb(system: dict) -> InlineKeyboardMarkup:
    """Кнопки с блоками выбранной системы."""
    rows = []
    for blk in system.get("blocks", []):
        rows.append([InlineKeyboardButton(
            text=f"📦 {blk['title']}",
            callback_data=f"blk:{system['id']}:{blk['id']}",
        )])
    rows.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="planet_back")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── /start ────────────────────────────────────────────────────────────────────

@dp.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    name = msg.from_user.first_name or "Игрок"
    await msg.answer(
        f"⚡ Привет, {name}!\n\n"
        "Я — твой личный секретарь системы SYSTEM.\n\n"
        "Используй кнопки внизу или просто пиши задачи текстом:\n"
        "«напомни завтра в 10 про встречу с куратором»",
        reply_markup=MAIN_KB,
    )


# ── Кнопка: Создать задачу — шаг 1 ───────────────────────────────────────────

@dp.message(F.text == "📝 Создать задачу")
async def btn_create(msg: Message, state: FSMContext):
    await state.set_state(CreateTask.info)
    await msg.answer(
        "📝 Шаг 1 из 4\n\n"
        "Опиши задачу — что нужно сделать?",
        reply_markup=ReplyKeyboardRemove(),
    )


@dp.message(CreateTask.info)
async def create_info(msg: Message, state: FSMContext):
    await state.update_data(info=msg.text.strip())
    await state.set_state(CreateTask.deadline)
    await msg.answer(
        "🕐 Шаг 2 из 4\n\n"
        "Когда дедлайн?\n\n"
        "Примеры: «завтра в 10», «в пятницу в 15», «2026-06-05 14:00»"
    )


@dp.message(CreateTask.deadline)
async def create_deadline(msg: Message, state: FSMContext):
    dt_str = _parse_datetime(msg.text.strip())
    if not dt_str:
        await msg.answer(
            "Не понял формат. Попробуй:\n"
            "«завтра в 10», «в пятницу в 15», «2026-06-05 14:00»"
        )
        return
    await state.update_data(deadline=dt_str)
    await state.set_state(CreateTask.points)
    await msg.answer("💎 Шаг 3 из 4\n\nВыбери сложность задачи:", reply_markup=POINTS_KB)


@dp.callback_query(CreateTask.points, F.data.startswith("pts:"))
async def create_points(cb: CallbackQuery, state: FSMContext):
    pts = int(cb.data.split(":")[1])
    await state.update_data(points=pts)
    await state.set_state(CreateTask.planet)

    data = await state.get_data()
    await cb.message.edit_text(
        f"✅ Сложность: +{pts} ✦\n\n"
        f"📝 {data['info']}\n"
        f"🗓 {data['deadline'][:16]}"
    )
    await cb.message.answer(
        "🪐 Шаг 4 из 4\n\nОтносится ли задача к какой-то системе?",
        reply_markup=await _systems_kb(cb.from_user.id),
    )
    await cb.answer()


# ── Шаг 4: выбор системы ─────────────────────────────────────────────────────

@dp.callback_query(CreateTask.planet, F.data == "planet_skip")
async def planet_skip(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    await state.clear()
    # Сохраняем как заметку в SYSTEM (Supabase), чтобы появилось в Запланированных
    ok = await add_note(
        cb.from_user.id,
        title    = data["info"],
        deadline = data["deadline"],
        reward   = data["points"],
    )
    await _save_and_confirm(cb, data, system_title=None, block_title=None, supabase_ok=ok)


@dp.callback_query(CreateTask.planet, F.data.startswith("sys:"))
async def planet_sys_select(cb: CallbackQuery, state: FSMContext):
    sys_id = cb.data.split(":")[1]
    systems = await get_systems(cb.from_user.id)
    sys = next((s for s in systems if s["id"] == sys_id), None)
    if not sys or not sys.get("blocks"):
        await cb.answer("У этой системы нет блоков.", show_alert=True)
        return
    await state.update_data(system_id=sys_id, system_title=sys["title"])
    await cb.message.edit_text(
        f"📦 Выбери блок в системе «{sys['title']}»:",
        reply_markup=_blocks_kb(sys),
    )
    await cb.answer()


@dp.callback_query(CreateTask.planet, F.data == "planet_back")
async def planet_back(cb: CallbackQuery, state: FSMContext):
    await cb.message.edit_text(
        "🪐 Шаг 4 из 4\n\nОтносится ли задача к какой-то системе?",
        reply_markup=await _systems_kb(),
    )
    await cb.answer()


@dp.callback_query(CreateTask.planet, F.data.startswith("blk:"))
async def planet_blk_select(cb: CallbackQuery, state: FSMContext):
    _, sys_id, blk_id = cb.data.split(":")
    data = await state.get_data()

    # Найти название блока
    systems = await get_systems(cb.from_user.id)
    sys  = next((s for s in systems if s["id"] == sys_id), None)
    blk  = next((b for b in sys.get("blocks", []) if b["id"] == blk_id), None) if sys else None

    await state.clear()

    # Записать квест в SYSTEM (Supabase)
    ok = await add_quest_to_block(
        cb.from_user.id, sys_id, blk_id,
        title    = data["info"],
        deadline = data["deadline"],
        reward   = data["points"],
    )

    await _save_and_confirm(
        cb, data,
        system_title = data.get("system_title", "?"),
        block_title  = blk["title"] if blk else "?",
        supabase_ok  = ok,
    )


# ── Финальное подтверждение + сохранение напоминания ─────────────────────────

async def _save_and_confirm(cb: CallbackQuery, data: dict,
                             system_title, block_title, supabase_ok=None):
    remind_at = datetime.strptime(data["deadline"], "%Y-%m-%d %H:%M:%S")
    await save_reminder(cb.from_user.id, remind_at, data["info"], data["points"])

    lines = [
        "✅ Задача создана!\n",
        f"📝 {data['info']}",
        f"🗓 {data['deadline'][:16]}",
        f"💎 +{data['points']} ✦",
    ]
    if system_title:
        planet_line = f"🪐 {system_title} → 📦 {block_title}"
        planet_line += "  ✅" if supabase_ok else "  ⚠️ (не удалось записать в SYSTEM)"
        lines.append(planet_line)
    elif supabase_ok:
        lines.append("📋 Добавлено в Запланированные на сайте ✅")
    else:
        lines.append("💾 Только в боте")

    await cb.message.edit_text("\n".join(lines))
    await cb.message.answer("Что дальше?", reply_markup=MAIN_KB)
    await cb.answer()


# ── Недельный вид задач ───────────────────────────────────────────────────────

async def _week_message(user_id: int, week_offset: int) -> tuple[str, InlineKeyboardMarkup]:
    """Каждая задача — отдельная кнопка. Клик → детальный вид с Выполнена/Отмена."""
    today      = datetime.now().date()
    week_start = today + timedelta(days=week_offset * 7)
    week_end   = week_start + timedelta(days=7)

    items = []  # {date, icon, title, type, id}

    # Локальные задачи бота
    for r in await list_reminders(user_id):
        try:
            dt = datetime.strptime(r["remind_at"][:10], "%Y-%m-%d").date()
        except ValueError:
            continue
        if week_start <= dt < week_end:
            items.append({"date": dt, "icon": "📌", "title": r["text"],
                          "type": "bot", "id": str(r["id"])})

    # Квесты из SYSTEM (Supabase)
    for q in await get_upcoming_quests(user_id):
        try:
            dt = datetime.strptime(q["deadline"], "%Y-%m-%d").date()
        except ValueError:
            continue
        if week_start <= dt < week_end:
            items.append({"date": dt, "icon": "🪐", "title": q["title"],
                          "type": "sys", "id": q["id"]})

    items.sort(key=lambda x: x["date"])

    header = (
        f"📅 <b>{week_start.strftime('%d.%m')} — "
        f"{(week_end - timedelta(days=1)).strftime('%d.%m')}</b>"
    )
    text = header if items else f"{header}\n\nНет задач на эту неделю."

    rows = []
    for it in items:
        title_s = it["title"][:30] + ("…" if len(it["title"]) > 30 else "")
        btn_txt = f"{it['icon']} {it['date'].strftime('%d.%m')}  {title_s}"
        cb_data = f"task:{it['type']}:{it['id']}:{week_offset}"
        rows.append([InlineKeyboardButton(text=btn_txt, callback_data=cb_data)])

    nav = []
    if week_offset > 0:
        nav.append(InlineKeyboardButton(text="← Пред.", callback_data=f"week:{week_offset-1}"))
    nav.append(InlineKeyboardButton(text="Сл. неделя →", callback_data=f"week:{week_offset+1}"))
    rows.append(nav)

    return text, InlineKeyboardMarkup(inline_keyboard=rows)


@dp.message(F.text == "📋 Ближайшие задачи")
async def btn_tasks(msg: Message, state: FSMContext):
    await state.clear()
    text, kb = await _week_message(msg.from_user.id, week_offset=0)
    await msg.answer(text, reply_markup=kb, parse_mode="HTML")


@dp.callback_query(F.data.startswith("week:"))
async def cb_week(cb: CallbackQuery):
    offset = int(cb.data.split(":")[1])
    text, kb = await _week_message(cb.from_user.id, week_offset=offset)
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


# ── Детальный вид задачи ──────────────────────────────────────────────────────

@dp.callback_query(F.data.startswith("task:"))
async def cb_task_view(cb: CallbackQuery):
    _, task_type, task_id, week_str = cb.data.split(":", 3)
    week_offset = int(week_str)
    back_kb_row = [InlineKeyboardButton(text="⬅️ К списку", callback_data=f"week:{week_offset}")]

    if task_type == "bot":
        task = await get_reminder(int(task_id))
        if not task:
            await cb.answer("Задача не найдена", show_alert=True)
            return
        dt  = task["remind_at"][:16]
        pts = f"\n💎 +{task['points']} ✦" if task.get("points") else ""
        text = f"📌 <b>{task['text']}</b>\n🗓 {dt}{pts}"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выполнена",  callback_data=f"done:{task_id}"),
                InlineKeyboardButton(text="❌ Отмена",     callback_data=f"remind_dismiss:{task_id}"),
            ],
            back_kb_row,
        ])

    else:  # sys — квест из SYSTEM
        quests = await get_upcoming_quests(cb.from_user.id)
        quest  = next((q for q in quests if q.get("id") == task_id), None)
        if not quest:
            await cb.answer("Квест не найден", show_alert=True)
            return
        pts = f"\n💎 +{quest['reward']} ✦" if quest.get("reward") else ""
        src = f"{quest['system_title']} → {quest['block_title']}"
        text = f"🪐 <b>{quest['title']}</b>\n🗓 {quest['deadline']}{pts}\n<i>{src}</i>"
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выполнена", callback_data=f"sys_done:{task_id}:{week_offset}"),
                InlineKeyboardButton(text="❌ Отмена",    callback_data=f"week:{week_offset}"),
            ],
            back_kb_row,
        ])

    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


@dp.callback_query(F.data.startswith("sys_done:"))
async def cb_sys_done(cb: CallbackQuery):
    _, quest_id, week_str = cb.data.split(":", 2)
    week_offset = int(week_str)
    ok = await mark_quest_done(cb.from_user.id, quest_id)
    if ok:
        text = "✅ Квест выполнен!"
    else:
        text = "⚠️ Не удалось обновить на сайте. Отметь вручную."
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="⬅️ К списку", callback_data=f"week:{week_offset}"),
    ]])
    await cb.message.edit_text(text, reply_markup=kb, parse_mode="HTML")
    await cb.answer()


# ── Кнопка: Изменить задачу ───────────────────────────────────────────────────

def _sys_task_edit_kb(quest_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"sys_mark_done:{quest_id}")],
        [
            InlineKeyboardButton(text="✏️ Текст",  callback_data=f"sys_edit_text:{quest_id}"),
            InlineKeyboardButton(text="🕐 Время",  callback_data=f"sys_edit_time:{quest_id}"),
            InlineKeyboardButton(text="💎 Очки",   callback_data=f"sys_edit_pts:{quest_id}"),
        ],
    ])

_sys_edit_state: dict[int, dict] = {}   # {user_id: {mode, quest_id}}

@dp.message(F.text == "✏️ Изменить задачу")
async def btn_edit(msg: Message, state: FSMContext):
    await state.clear()
    user_id = msg.from_user.id
    local  = await list_reminders(user_id)
    system = await get_upcoming_quests(user_id)

    if not local and not system:
        await msg.answer("Нет активных задач.", reply_markup=MAIN_KB)
        return

    for r in local[:5]:
        await msg.answer(_task_text(r), reply_markup=_task_edit_kb(r["id"]))

    for q in system[:10]:
        pts = f"+{q['reward']} ✦" if q.get("reward") else "без очков"
        text = (f"🗓 {q['deadline']}  |  {pts}\n"
                f"{q['title']}\n"
                f"<i>{q['system_title']} → {q['block_title']}</i>")
        await msg.answer(text, reply_markup=_sys_task_edit_kb(q["id"]), parse_mode="HTML")


# ── /tasks ────────────────────────────────────────────────────────────────────

@dp.message(Command("tasks"))
async def cmd_tasks(msg: Message):
    rows = await list_reminders(msg.from_user.id)
    if not rows:
        await msg.answer("Нет активных задач.", reply_markup=MAIN_KB)
        return
    for r in rows:
        await msg.answer(_task_text(r), reply_markup=_task_edit_kb(r["id"]))


# ── Inline: Выполнено / Отмена напоминания ───────────────────────────────────

@dp.callback_query(F.data.startswith("done:"))
async def cb_done(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    task = await get_reminder(task_id)
    pts_text = f"  +{task['points']} ✦ начислено!" if task and task.get("points") else ""
    await mark_reminder_sent(task_id)
    await cb.message.edit_text(f"✅ Выполнено!{pts_text}", reply_markup=None)
    await cb.answer("Готово!")


@dp.callback_query(F.data.startswith("remind_dismiss:"))
async def cb_remind_dismiss(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    await mark_reminder_sent(task_id)
    await cb.message.edit_text("❌ Напоминание отклонено.", reply_markup=None)
    await cb.answer()


# ── Inline: Редактировать ─────────────────────────────────────────────────────

_edit_state: dict[int, dict] = {}

@dp.callback_query(F.data.startswith("edit_text:"))
async def cb_edit_text(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    _edit_state[cb.from_user.id] = {"mode": "text", "task_id": task_id}
    await cb.message.answer("✏️ Введи новый текст:", reply_markup=ReplyKeyboardRemove())
    await cb.answer()


@dp.callback_query(F.data.startswith("edit_time:"))
async def cb_edit_time(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    _edit_state[cb.from_user.id] = {"mode": "time", "task_id": task_id}
    await cb.message.answer(
        "🕐 Введи новую дату/время:\n«завтра в 11», «2026-06-05 14:00»",
        reply_markup=ReplyKeyboardRemove(),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("edit_pts:"))
async def cb_edit_pts(cb: CallbackQuery):
    task_id = int(cb.data.split(":")[1])
    _edit_state[cb.from_user.id] = {"mode": "points", "task_id": task_id}
    await cb.message.answer("💎 Выбери новую сложность:", reply_markup=POINTS_KB)
    await cb.answer()


@dp.callback_query(F.data.startswith("pts:"))
async def cb_pts_edit(cb: CallbackQuery):
    """pts: вне FSM — редактирование бот-задачи или SYSTEM-квеста."""
    user_id = cb.from_user.id
    pts = int(cb.data.split(":")[1])

    # SYSTEM-квест
    if user_id in _sys_edit_state and _sys_edit_state[user_id]["mode"] == "points":
        quest_id = _sys_edit_state.pop(user_id)["quest_id"]
        ok = await update_quest(user_id, quest_id, reward=pts)
        suffix = " ✅" if ok else " ⚠️ не синхронизировано"
        await cb.message.edit_text(f"💎 Очки обновлены: +{pts} ✦{suffix}")
        await cb.message.answer("Что дальше?", reply_markup=MAIN_KB)
        await cb.answer()
        return

    # Бот-задача
    if user_id not in _edit_state or _edit_state[user_id]["mode"] != "points":
        return
    task_id = _edit_state.pop(user_id)["task_id"]
    await update_reminder(task_id, points=pts)
    task = await get_reminder(task_id)
    await cb.message.edit_text(f"✅ Очки обновлены: +{pts} ✦\n\n{_task_text(task)}")
    await cb.message.answer("Что дальше?", reply_markup=MAIN_KB)
    await cb.answer()


# ── Inline: Редактировать SYSTEM-квест ───────────────────────────────────────

@dp.callback_query(F.data.startswith("sys_mark_done:"))
async def cb_sys_mark_done(cb: CallbackQuery):
    quest_id = cb.data.split(":", 1)[1]
    ok = await mark_quest_done(cb.from_user.id, quest_id)
    await cb.message.edit_text("✅ Выполнено!" if ok else "⚠️ Не удалось обновить.", reply_markup=None)
    await cb.answer()

@dp.callback_query(F.data.startswith("sys_edit_text:"))
async def cb_sys_edit_text(cb: CallbackQuery):
    quest_id = cb.data.split(":", 1)[1]
    _sys_edit_state[cb.from_user.id] = {"mode": "text", "quest_id": quest_id}
    await cb.message.answer("✏️ Введи новый текст:", reply_markup=ReplyKeyboardRemove())
    await cb.answer()

@dp.callback_query(F.data.startswith("sys_edit_time:"))
async def cb_sys_edit_time(cb: CallbackQuery):
    quest_id = cb.data.split(":", 1)[1]
    _sys_edit_state[cb.from_user.id] = {"mode": "time", "quest_id": quest_id}
    await cb.message.answer(
        "🕐 Введи новую дату:\n«завтра в 11», «2026-06-05»",
        reply_markup=ReplyKeyboardRemove(),
    )
    await cb.answer()

@dp.callback_query(F.data.startswith("sys_edit_pts:"))
async def cb_sys_edit_pts(cb: CallbackQuery):
    quest_id = cb.data.split(":", 1)[1]
    _sys_edit_state[cb.from_user.id] = {"mode": "points", "quest_id": quest_id}
    await cb.message.answer("💎 Выбери новую сложность:", reply_markup=POINTS_KB)
    await cb.answer()


async def handle_sys_edit(msg: Message):
    user_id = msg.from_user.id
    st = _sys_edit_state.pop(user_id)
    quest_id, mode = st["quest_id"], st["mode"]

    if mode == "text":
        ok = await update_quest(user_id, quest_id, title=msg.text.strip())
        suffix = " ✅" if ok else " ⚠️ не синхронизировано"
        await msg.answer(f"✅ Текст обновлён{suffix}", reply_markup=MAIN_KB)

    elif mode == "time":
        dt_str = _parse_datetime(msg.text.strip())
        if not dt_str:
            _sys_edit_state[user_id] = st
            await msg.answer("Не понял формат. Попробуй: «завтра в 11», «2026-06-05»")
            return
        ok = await update_quest(user_id, quest_id, deadline=dt_str)
        suffix = " ✅" if ok else " ⚠️ не синхронизировано"
        await msg.answer(f"✅ Дата обновлена{suffix}", reply_markup=MAIN_KB)


# ── Обычные сообщения ─────────────────────────────────────────────────────────

@dp.message(F.text)
async def on_message(msg: Message, state: FSMContext):
    user_id = msg.from_user.id

    if user_id in _edit_state:
        await handle_edit(msg)
        return

    if user_id in _sys_edit_state:
        await handle_sys_edit(msg)
        return

    await msg.bot.send_chat_action(msg.chat.id, "typing")
    try:
        text, reminder = await agent.handle(user_id, msg.text)
        clean = _strip_json(text)
        if reminder:
            await save_reminder(user_id, reminder["remind_at"], reminder["text"], reminder.get("points", 0))
            pts = reminder.get("points", 0)
            suffix = f"\n💎 Оценка: +{pts} ✦" if pts else ""
            await msg.answer((clean or "Записал!") + suffix, reply_markup=MAIN_KB)
        else:
            await msg.answer(clean or "Записал!", reply_markup=MAIN_KB)
    except Exception as e:
        logger.error(f"Error uid={user_id}: {e}", exc_info=True)
        await msg.answer("Произошла ошибка. Попробуй ещё раз.", reply_markup=MAIN_KB)


# ── Edit handler ──────────────────────────────────────────────────────────────

async def handle_edit(msg: Message):
    user_id = msg.from_user.id
    st      = _edit_state.pop(user_id)
    task_id, mode = st["task_id"], st["mode"]
    task = await get_reminder(task_id)
    if not task:
        await msg.answer("Задача не найдена.", reply_markup=MAIN_KB)
        return

    if mode == "text":
        await update_reminder(task_id, text=msg.text.strip())
        task["text"] = msg.text.strip()
        await msg.answer(f"✅ Текст обновлён!\n\n{_task_text(task)}", reply_markup=_task_edit_kb(task_id))
        await msg.answer("Что дальше?", reply_markup=MAIN_KB)

    elif mode == "time":
        dt_str = _parse_datetime(msg.text.strip())
        if not dt_str:
            _edit_state[user_id] = st
            await msg.answer("Не понял формат. Попробуй: «завтра в 11», «2026-06-05 14:00»")
            return
        await update_reminder(task_id, remind_at=dt_str)
        task["remind_at"] = dt_str
        await msg.answer(f"✅ Время обновлено!\n\n{_task_text(task)}", reply_markup=_task_edit_kb(task_id))
        await msg.answer("Что дальше?", reply_markup=MAIN_KB)


# ── UI helpers ────────────────────────────────────────────────────────────────

def _task_text(r: dict) -> str:
    dt  = r["remind_at"][:16]
    pts = f"+{r['points']} ✦" if r.get("points") else "без очков"
    return f"🗓 {dt}  |  {pts}\n{r['text']}"

def _task_done_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Выполнено", callback_data=f"done:{task_id}"),
    ]])

def _task_edit_kb(task_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Выполнено", callback_data=f"done:{task_id}")],
        [
            InlineKeyboardButton(text="✏️ Текст",  callback_data=f"edit_text:{task_id}"),
            InlineKeyboardButton(text="🕐 Время",  callback_data=f"edit_time:{task_id}"),
            InlineKeyboardButton(text="💎 Очки",   callback_data=f"edit_pts:{task_id}"),
        ],
    ])

def _strip_json(text: str) -> str:
    return _re.sub(r'\{[^{}]*"action"\s*:\s*"set_reminder"[^{}]*\}', '', text).strip()

def _parse_datetime(text: str) -> str | None:
    now = datetime.now()
    m = _re.search(r'(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2})', text)
    if m:
        return f"{m.group(1)} {m.group(2)}:00"
    m = _re.search(r'(\d{2})\.(\d{2})\.(\d{4})\s+(\d{2}):(\d{2})', text)
    if m:
        d, mo, y, h, mi = m.groups()
        return f"{y}-{mo}-{d} {h}:{mi}:00"
    m_h = _re.search(r'(\d{1,2})(?::(\d{2}))?', text)
    hour   = int(m_h.group(1)) if m_h else 9
    minute = int(m_h.group(2)) if m_h and m_h.group(2) else 0
    if "завтра" in text:
        d = now + timedelta(days=1)
        return f"{d.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00"
    if "послезавтра" in text:
        d = now + timedelta(days=2)
        return f"{d.strftime('%Y-%m-%d')} {hour:02d}:{minute:02d}:00"
    m_d = _re.search(r'через\s+(\d+)\s+час', text)
    if m_d:
        d = now + timedelta(hours=int(m_d.group(1)))
        return d.strftime("%Y-%m-%d %H:%M:%S")
    if "сегодня" in text:
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
