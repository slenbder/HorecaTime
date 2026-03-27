import logging

import aiosqlite
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from app.bot.commands import set_commands_for_role
from app.bot.fsm.auth_states import AuthStates, SetRateStates
from app.db.fsm_storage import SQLiteStorage
from app.db.models import get_all_rates, update_rate, get_user
from app.scheduler.monthly_switch import switch_month, notify_switch_done, get_next_sheet_name
from app.services.google_sheets import GoogleSheetsClient
from app.services.roles_cache import RolesCacheService
from config import DB_PATH, SUPERADMIN_IDS, DEVELOPER_ID

_sheets_client = GoogleSheetsClient()

superadmin_router = Router()
logger = logging.getLogger(__name__)


def _is_allowed(tg_id: int) -> bool:
    return tg_id in SUPERADMIN_IDS or tg_id == DEVELOPER_ID

# Позиции, у которых есть повышенная ставка
_POSITIONS_WITH_EXTRA = {"Бармен", "Барбэк", "Раннер"}

# Порядок позиций для отображения
_POSITIONS_ORDER = [
    "Бармен", "Барбэк",
    "Официант", "Раннер", "Хостесс", "Менеджер",
    "Горячий цех", "Холодный цех", "Кондитерский цех",
    "Заготовочный цех", "Коренной цех", "МОП", "Су-шеф",
]


def _fmt_money(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def _rates_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=pos, callback_data=f"set_rate_pos:{pos}")]
        for pos in _POSITIONS_ORDER
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@superadmin_router.message(Command("message_all"))
async def cmd_message_all(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    logger.info("/message_all: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/message_all: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return

    await state.update_data(broadcast_type="all")
    await state.set_state(AuthStates.waiting_broadcast_text)
    await message.answer("Введите текст сообщения для всех сотрудников:")


@superadmin_router.message(Command("rates_all"))
async def cmd_rates_all(message: Message):
    tg_id = message.from_user.id
    logger.info("/rates_all: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/rates_all: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return

    logger.info("/rates_all: доступ разрешён, загружаю ставки")
    rates = await get_all_rates(DB_PATH)

    # Сортируем в нужном порядке
    rate_map = {r["position"]: r for r in rates}
    lines = ["💰 Ставки сотрудников:\n"]
    for pos in _POSITIONS_ORDER:
        r = rate_map.get(pos)
        if r is None:
            continue
        base_str = f"{_fmt_money(r['base_rate'])} р/ч"
        if r["extra_rate"] is not None:
            extra_label = "тусовочные" if pos in ("Бармен", "Барбэк") else "повышенная"
            line = f"{pos}: {base_str} ({extra_label}: {_fmt_money(r['extra_rate'])} р/ч)"
        else:
            line = f"{pos}: {base_str}"
        lines.append(line)

    await message.answer("\n".join(lines))


@superadmin_router.message(Command("set_rate_all"))
async def cmd_set_rate_all(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    logger.info("/set_rate_all: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/set_rate_all: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return

    logger.info("/set_rate_all: доступ разрешён, запускаю FSM")
    await state.set_state(SetRateStates.waiting_set_rate_position)
    await message.answer(
        "Выберите позицию для изменения ставки:",
        reply_markup=_rates_keyboard(),
    )


@superadmin_router.callback_query(
    SetRateStates.waiting_set_rate_position,
    F.data.startswith("set_rate_pos:"),
)
async def cb_set_rate_position(callback: CallbackQuery, state: FSMContext):
    position = callback.data.split(":", 1)[1]
    await state.update_data(position=position)
    await state.set_state(SetRateStates.waiting_set_rate_base)
    await callback.message.edit_text(
        f"Позиция: <b>{position}</b>\n\nВведите базовую ставку (р/час):"
    )
    await callback.answer()


@superadmin_router.message(SetRateStates.waiting_set_rate_base)
async def msg_set_rate_base(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        base_rate = float(text)
        if base_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число больше 0:")
        return

    data = await state.get_data()
    position = data["position"]
    await state.update_data(base_rate=base_rate)

    if position in _POSITIONS_WITH_EXTRA:
        await state.set_state(SetRateStates.waiting_set_rate_extra)
        extra_label = "тусовочную" if position in ("Бармен", "Барбэк") else "повышенную"
        await message.answer(f"Введите {extra_label} ставку (р/час):")
    else:
        # Нет extra_rate — сразу сохраняем
        await _save_rate(message, state, position, base_rate, extra_rate=None)


@superadmin_router.message(SetRateStates.waiting_set_rate_extra)
async def msg_set_rate_extra(message: Message, state: FSMContext):
    text = message.text.strip().replace(",", ".")
    try:
        extra_rate = float(text)
        if extra_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число больше 0:")
        return

    data = await state.get_data()
    position = data["position"]
    base_rate = data["base_rate"]
    await _save_rate(message, state, position, base_rate, extra_rate)


async def _save_rate(message: Message, state: FSMContext,
                     position: str, base_rate: float, extra_rate: float | None):
    await update_rate(DB_PATH, position, base_rate, extra_rate)
    await state.clear()

    extra_str = ""
    if extra_rate is not None:
        extra_label = "тусовочные" if position in ("Бармен", "Барбэк") else "повышенная"
        extra_str = f", {extra_label}: {_fmt_money(extra_rate)} р/ч"

    logger.info(
        "set_rate_all: позиция=%s base=%s extra=%s (от %s)",
        position, base_rate, extra_rate, message.from_user.id,
    )
    await message.answer(
        f"✅ Ставка обновлена: {position} — {_fmt_money(base_rate)} р/ч{extra_str}"
    )


@superadmin_router.message(Command("switch_month"))
async def cmd_switch_month(message: Message):
    tg_id = message.from_user.id
    logger.info("/switch_month: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/switch_month: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return

    next_name, _, _ = get_next_sheet_name()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, переключить", callback_data="switch_month_confirm"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="switch_month_cancel"),
        ]
    ])
    await message.answer(
        f"⚠️ Переключение месяца\n\n"
        f"Будет создан новый лист <b>{next_name}</b>.\n"
        f"Все активные сотрудники будут перенесены.\n"
        f"Уволенные сотрудники (красные строки) — удалены.\n\n"
        f"Продолжить?",
        reply_markup=keyboard,
    )


@superadmin_router.callback_query(F.data == "switch_month_confirm")
async def cb_switch_month_confirm(callback: CallbackQuery):
    tg_id = callback.from_user.id
    logger.info("switch_month_confirm: от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("switch_month_confirm: доступ запрещён для %s", tg_id)
        await callback.answer("⛔️ Недостаточно прав.", show_alert=True)
        return

    await callback.message.edit_text("⏳ Переключаю месяц, подождите...")
    await callback.answer()

    try:
        result = await switch_month(callback.bot, _sheets_client, DB_PATH)
        await callback.message.edit_text(
            f"✅ Готово!\n\n"
            f"Старый лист: {result['old_sheet']}\n"
            f"Новый лист: {result['new_sheet']}\n"
            f"Перенесено сотрудников: {result['transferred']}\n"
            f"Удалено уволенных: {result['removed']}"
            + (f"\nАномалий: {result['anomalies']}" if result["anomalies"] else "")
        )
        logger.info(
            "switch_month_confirm: переключение завершено. %s → %s",
            result["old_sheet"], result["new_sheet"],
        )
        await notify_switch_done(callback.bot, DB_PATH, result)
    except Exception as e:
        logger.error("switch_month_confirm: ошибка переключения: %s", e)
        await callback.message.edit_text(
            f"❌ Ошибка при переключении месяца:\n\n{type(e).__name__}: {e}"
        )


@superadmin_router.callback_query(F.data == "switch_month_cancel")
async def cb_switch_month_cancel(callback: CallbackQuery):
    logger.info("switch_month_cancel: от %s", callback.from_user.id)
    await callback.message.edit_text("❌ Переключение месяца отменено.")
    await callback.answer()


# --- /promote ---

_PROMOTE_VALID_POSITIONS: dict[str, list[str]] = {
    "Зал":   ["Менеджер", "Официант", "Раннер", "Хостесс"],
    "Бар":   ["Бармен", "Барбэк"],
    "Кухня": ["Шеф/Су-шеф", "Горячий цех", "Холодный цех",
               "Кондитерский цех", "Заготовочный цех", "Коренной цех", "Доп."],
    "МОП":   ["Клининг", "Котломой"],
}

_DEPT_TO_ADMIN_ROLE: dict[str, str] = {
    "Зал":   "admin_hall",
    "Бар":   "admin_bar",
    "Кухня": "admin_kitchen",
    "МОП":   "admin_hall",
}


def _promote_dept_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=dept, callback_data=f"promote_dept:{dept}")]
        for dept in ("Зал", "Бар", "Кухня", "МОП")
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="promote_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _promote_positions_keyboard(dept: str) -> InlineKeyboardMarkup:
    positions = _PROMOTE_VALID_POSITIONS.get(dept, [])
    buttons = [
        [InlineKeyboardButton(text=pos, callback_data=f"promote_pos:{dept}:{pos}")]
        for pos in positions
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="promote_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def _get_users_for_promote(dept: str, position: str) -> list[dict]:
    """Возвращает сотрудников (role=user) в заданном отделе и на заданной позиции."""
    if position == "Шеф/Су-шеф":
        query = (
            "SELECT telegram_id, full_name FROM users "
            "WHERE role = 'user' AND department = ? AND position = ?"
        )
        params: tuple = (dept, "Су-шеф")
    elif position == "Доп.":
        query = (
            "SELECT telegram_id, full_name FROM users "
            "WHERE role = 'user' AND department = ? "
            "AND position IN ('Грузчик', 'Закупщик')"
        )
        params = (dept,)
    else:
        query = (
            "SELECT telegram_id, full_name FROM users "
            "WHERE role = 'user' AND department = ? AND position = ?"
        )
        params = (dept, position)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()

    return [{"telegram_id": r[0], "full_name": r[1]} for r in rows]


async def _set_employee_promote_state(
    bot_id: int, employee_id: int, dept: str, full_name: str
) -> None:
    """Устанавливает состояние waiting_promote_email для сотрудника в его FSM-контексте."""
    storage = SQLiteStorage(DB_PATH)
    key = StorageKey(bot_id=bot_id, chat_id=employee_id, user_id=employee_id)
    ctx = FSMContext(storage=storage, key=key)
    await ctx.set_state(AuthStates.waiting_promote_email)
    await ctx.update_data(promote_dept=dept, promote_full_name=full_name)


@superadmin_router.message(Command("promote"))
async def cmd_promote(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    logger.info("/promote: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/promote: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return
    await state.set_state(AuthStates.waiting_promote_dept)
    await message.answer(
        "⬆️ Повышение сотрудника\n\nВыберите подразделение:",
        reply_markup=_promote_dept_keyboard(),
    )


@superadmin_router.callback_query(AuthStates.waiting_promote_dept, F.data.startswith("promote_dept:"))
async def cb_promote_dept(callback: CallbackQuery, state: FSMContext):
    dept = callback.data.split(":", 1)[1]
    logger.info("promote_dept: суперадмин %s выбрал отдел %s", callback.from_user.id, dept)
    await state.update_data(promote_dept=dept)
    await state.set_state(AuthStates.waiting_promote_position)
    await callback.message.edit_text(
        f"Отдел: <b>{dept}</b>\n\nВыберите позицию:",
        reply_markup=_promote_positions_keyboard(dept),
    )
    await callback.answer()


@superadmin_router.callback_query(AuthStates.waiting_promote_position, F.data.startswith("promote_pos:"))
async def cb_promote_pos(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split(":", 2)
    dept = parts[1]
    position = parts[2]
    logger.info(
        "promote_pos: суперадмин %s выбрал позицию %s в %s",
        callback.from_user.id, position, dept,
    )

    users = await _get_users_for_promote(dept, position)
    if not users:
        await callback.message.edit_text(
            f"В позиции «{position}» отдела «{dept}» нет сотрудников для повышения."
        )
        await callback.answer()
        await state.clear()
        return

    buttons = [
        [InlineKeyboardButton(
            text=u["full_name"],
            callback_data=f"promote_select:{u['telegram_id']}",
        )]
        for u in users
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="promote_cancel")])

    await state.update_data(promote_position=position)
    await state.set_state(AuthStates.waiting_promote_user)
    await callback.message.edit_text(
        f"Отдел: <b>{dept}</b> | Позиция: <b>{position}</b>\n\nВыберите сотрудника:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@superadmin_router.callback_query(AuthStates.waiting_promote_user, F.data.startswith("promote_select:"))
async def cb_promote_select(callback: CallbackQuery, state: FSMContext):
    employee_id = int(callback.data.split(":", 1)[1])

    employee = get_user(employee_id)
    if not employee:
        await callback.answer("Сотрудник не найден.", show_alert=True)
        await state.clear()
        return

    full_name = employee["full_name"]
    position = employee["position"] or ""
    dept = employee["department"] or ""

    logger.info(
        "promote_select: суперадмин %s выбрал сотрудника %s (%s)",
        callback.from_user.id, employee_id, full_name,
    )

    await state.update_data(promote_target_id=employee_id)
    await state.set_state(AuthStates.waiting_promote_confirm)

    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Повысить", callback_data=f"promote_confirm:{employee_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="promote_cancel"),
        ]
    ])
    await callback.message.edit_text(
        f"⬆️ Повысить <b>{full_name}</b> ({position}, {dept}) до администратора отдела?\n\n"
        f"После повышения сотрудник получит расширенные права управления отделом.\n\n"
        f"Это действие можно отменить командой /demote.",
        reply_markup=confirm_keyboard,
    )
    await callback.answer()


@superadmin_router.callback_query(AuthStates.waiting_promote_confirm, F.data.startswith("promote_confirm:"))
async def cb_promote_confirm(callback: CallbackQuery, state: FSMContext):
    employee_id = int(callback.data.split(":", 1)[1])

    employee = get_user(employee_id)
    if not employee:
        await callback.answer("Сотрудник не найден.", show_alert=True)
        await state.clear()
        return

    full_name = employee["full_name"]
    dept = employee["department"] or ""
    position = employee["position"]

    new_role = _DEPT_TO_ADMIN_ROLE.get(dept)
    if not new_role:
        logger.error("promote_confirm: неизвестный отдел '%s' для %s", dept, employee_id)
        await callback.answer("Неизвестный отдел.", show_alert=True)
        await state.clear()
        return

    RolesCacheService.update_user_role(
        telegram_id=employee_id,
        full_name=full_name,
        role=new_role,
        department=dept,
        position=position,
    )
    logger.info(
        "promote_confirm: %s (id=%s) повышен до %s суперадмином %s",
        full_name, employee_id, new_role, callback.from_user.id,
    )

    await set_commands_for_role(callback.bot, employee_id, new_role)

    await _set_employee_promote_state(callback.bot.id, employee_id, dept, full_name)

    try:
        await callback.bot.send_message(
            chat_id=employee_id,
            text=(
                f"🎉 Поздравляем! Вы повышены до администратора отдела {dept}.\n\n"
                f"Теперь вам доступны расширенные функции управления отделом.\n\n"
                f"Для активации полного доступа введите вашу почту Gmail:"
            ),
        )
    except Exception:
        logger.exception("promote_confirm: не удалось уведомить сотрудника %s", employee_id)

    await callback.message.edit_text(
        f"✅ {full_name} повышен до администратора {dept}.\n"
        f"Ожидаем ввода email для предоставления доступа к таблице.",
        reply_markup=None,
    )
    await callback.answer()
    await state.clear()


@superadmin_router.callback_query(F.data == "promote_cancel")
async def cb_promote_cancel(callback: CallbackQuery, state: FSMContext):
    logger.info("promote_cancel: суперадмин %s отменил повышение", callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("Отменено.")
    await callback.answer()


# --- /demote ---

_ADMIN_ROLES = {"admin_hall", "admin_bar", "admin_kitchen"}
_DEPT_TO_ADMIN_ROLES: dict[str, set[str]] = {
    "Зал":   {"admin_hall"},
    "Бар":   {"admin_bar"},
    "Кухня": {"admin_kitchen"},
    "МОП":   {"admin_hall"},
}


async def _get_admins_for_demote(dept: str) -> list[dict]:
    """Возвращает администраторов (admin_hall/bar/kitchen) из заданного подразделения."""
    roles = _DEPT_TO_ADMIN_ROLES.get(dept, set())
    if not roles:
        return []
    placeholders = ",".join("?" * len(roles))
    query = (
        f"SELECT telegram_id, full_name, position FROM users "
        f"WHERE role IN ({placeholders}) AND department = ?"
    )
    params = (*roles, dept)
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
    return [{"telegram_id": r[0], "full_name": r[1], "position": r[2] or ""} for r in rows]


def _demote_dept_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=dept, callback_data=f"demote_dept:{dept}")]
        for dept in ("Зал", "Бар", "Кухня", "МОП")
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="demote_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@superadmin_router.message(Command("demote"))
async def cmd_demote(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    logger.info("/demote: запрос от %s", tg_id)
    if not _is_allowed(tg_id):
        logger.warning("/demote: доступ запрещён для %s", tg_id)
        await message.answer("⛔️ Недостаточно прав.")
        return
    await state.set_state(AuthStates.waiting_demote_dept)
    await message.answer(
        "📉 Понижение администратора\n\nВыберите подразделение:",
        reply_markup=_demote_dept_keyboard(),
    )


@superadmin_router.callback_query(AuthStates.waiting_demote_dept, F.data.startswith("demote_dept:"))
async def cb_demote_dept(callback: CallbackQuery, state: FSMContext):
    dept = callback.data.split(":", 1)[1]
    logger.info("demote_dept: суперадмин %s выбрал отдел %s", callback.from_user.id, dept)

    admins = await _get_admins_for_demote(dept)
    if not admins:
        await callback.message.edit_text(f"В отделе {dept} нет администраторов.")
        await callback.answer()
        await state.clear()
        return

    buttons = [
        [InlineKeyboardButton(
            text=a["full_name"],
            callback_data=f"demote_select:{a['telegram_id']}",
        )]
        for a in admins
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="demote_cancel")])

    await state.update_data(demote_dept=dept)
    await state.set_state(AuthStates.waiting_demote_user)
    await callback.message.edit_text(
        f"Отдел: <b>{dept}</b>\n\nВыберите администратора:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@superadmin_router.callback_query(AuthStates.waiting_demote_user, F.data.startswith("demote_select:"))
async def cb_demote_select(callback: CallbackQuery, state: FSMContext):
    employee_id = int(callback.data.split(":", 1)[1])

    employee = get_user(employee_id)
    if not employee:
        await callback.answer("Администратор не найден.", show_alert=True)
        await state.clear()
        return

    full_name = employee["full_name"]
    position = employee["position"] or ""
    dept = employee["department"] or ""

    logger.info(
        "demote_select: суперадмин %s выбрал администратора %s (%s)",
        callback.from_user.id, employee_id, full_name,
    )

    await state.update_data(demote_target_id=employee_id)
    await state.set_state(AuthStates.waiting_demote_confirm)

    confirm_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, понизить", callback_data=f"demote_confirm:{employee_id}"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="demote_cancel"),
        ]
    ])
    await callback.message.edit_text(
        f"📉 Понизить <b>{full_name}</b> ({position}, {dept})?\n\n"
        f"Сотрудник потеряет права администратора и вернётся "
        f"к обычным функциям сотрудника своей позиции.\n\n"
        f"Это действие можно отменить командой /promote.",
        reply_markup=confirm_keyboard,
    )
    await callback.answer()


@superadmin_router.callback_query(AuthStates.waiting_demote_confirm, F.data.startswith("demote_confirm:"))
async def cb_demote_confirm(callback: CallbackQuery, state: FSMContext):
    employee_id = int(callback.data.split(":", 1)[1])

    employee = get_user(employee_id)
    if not employee:
        await callback.answer("Администратор не найден.", show_alert=True)
        await state.clear()
        return

    full_name = employee["full_name"]
    dept = employee["department"] or ""
    position = employee["position"]

    RolesCacheService.update_user_role(
        telegram_id=employee_id,
        full_name=full_name,
        role="user",
        department=dept,
        position=position,
    )
    logger.info(
        "demote_confirm: %s (id=%s) понижен до user суперадмином %s",
        full_name, employee_id, callback.from_user.id,
    )

    await set_commands_for_role(callback.bot, employee_id, "user")

    # Уведомить понижаемого сотрудника
    try:
        await callback.bot.send_message(
            chat_id=employee_id,
            text=(
                f"📉 Ваши права администратора отдела {dept} были отозваны.\n\n"
                f"Вы возвращаетесь к стандартным функциям сотрудника.\n"
                f"По вопросам обращайтесь к управляющему."
            ),
        )
    except Exception:
        logger.exception("demote_confirm: не удалось уведомить сотрудника %s", employee_id)

    # Формируем упоминания для уведомления суперадминов
    admin_username = callback.from_user.username
    admin_name = (
        f"{callback.from_user.first_name or ''} {callback.from_user.last_name or ''}".strip()
        or str(callback.from_user.id)
    )
    admin_mention = (
        f'<a href="https://t.me/{admin_username}">{admin_name}</a>'
        if admin_username else admin_name
    )
    employee_mention = full_name  # username сотрудника не хранится в SQLite

    sa_notify = (
        f"📉 {employee_mention} понижен с должности администратора {dept} "
        f"до сотрудника. Действие выполнил: {admin_mention}"
    )
    for sa_id in SUPERADMIN_IDS:
        if sa_id == callback.from_user.id:
            continue
        try:
            await callback.bot.send_message(chat_id=sa_id, text=sa_notify, parse_mode="HTML")
        except Exception:
            logger.exception("demote_confirm: не удалось уведомить суперадмина %s", sa_id)

    await callback.message.edit_text(
        f"✅ {full_name} понижен до сотрудника отдела {dept}.",
        reply_markup=None,
    )
    await callback.answer()
    await state.clear()


@superadmin_router.callback_query(F.data == "demote_cancel")
async def cb_demote_cancel(callback: CallbackQuery, state: FSMContext):
    logger.info("demote_cancel: суперадмин %s отменил понижение", callback.from_user.id)
    await state.clear()
    await callback.message.edit_text("Отменено.")
    await callback.answer()
