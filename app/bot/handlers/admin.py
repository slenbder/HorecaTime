import asyncio
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from app.bot.fsm.auth_states import AuthStates
from app.bot.fsm.admin_states import SetRateStates
from app.db.models import get_users_by_department, get_all_users, get_users_rates_by_department, set_user_rate, get_user_role
from config import DB_PATH, SUPERADMIN_IDS, DEVELOPER_ID, POSITIONS_WITH_EXTRA, EXTRA_RATE_LABELS

admin_router = Router()
logger = logging.getLogger(__name__)
error_logger = logging.getLogger("errors")

_ALLOWED_ROLES = {"admin_hall", "admin_bar", "admin_kitchen", "superadmin", "developer"}

_ROLE_TO_DEPT = {
    "admin_hall":    "Зал",
    "admin_bar":     "Бар",
    "admin_kitchen": "Кухня",
}

_DEPT_BUTTONS = ["Зал", "Бар", "Кухня", "МОП"]

_DEPT_POSITIONS = {
    "Зал":   ["Менеджер", "Официант", "Раннер", "Хостесс"],
    "Бар":   ["Бармен", "Барбэк"],
    "Кухня": ["Руководящий состав", "Горячий цех", "Холодный цех", "Кондитерский цех",
               "Заготовочный цех", "Коренной цех", "Грузчик", "Закупщик"],
    "МОП":   ["Клининг", "Котломой"],
}

ROLE_TO_SENDER = {
    "admin_hall":    "администратора Зала",
    "admin_bar":     "администратора Бара",
    "admin_kitchen": "администратора Кухни",
    "superadmin":    "администрации",
    "developer":     "администрации",
}


async def _resolve_sender_role(tg_id: int) -> str | None:
    if tg_id in SUPERADMIN_IDS or tg_id == DEVELOPER_ID:
        return "superadmin"
    return await get_user_role(DB_PATH, tg_id)


def _positions_for_dept(dept: str) -> list[str]:
    """Возвращает список позиций для управления ставками.
    admin_hall управляет МОП, поэтому Зал включает позиции МОП."""
    positions = list(_DEPT_POSITIONS.get(dept, []))
    if dept == "Зал":
        positions += _DEPT_POSITIONS.get("МОП", [])
    return positions


def _dept_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=dept, callback_data=f"broadcast_dept:{dept}")]
        for dept in _DEPT_BUTTONS
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _hall_dept_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="Зал", callback_data="broadcast_dept:Зал")],
        [InlineKeyboardButton(text="МОП", callback_data="broadcast_dept:МОП")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _fmt_money(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.2f}"


# --- /rates ---

def _fmt_emp_rate(emp: dict) -> str:
    """Форматирует ставку сотрудника: 'base р/ч' или 'base/extra р/ч' или 'не установлена'."""
    base = emp.get("base_rate")
    if base is None:
        return "не установлена"
    extra = emp.get("extra_rate")
    if extra is not None:
        return f"{_fmt_money(base)}/{_fmt_money(extra)} р/ч"
    return f"{_fmt_money(base)} р/ч"


@admin_router.message(Command("rates"))
async def cmd_rates(message: Message):
    tg_id = message.from_user.id
    role = await _resolve_sender_role(tg_id)
    if role not in _ROLE_TO_DEPT:
        logger.warning("/rates: доступ запрещён для %s (role=%s)", tg_id, role)
        await message.answer("⛔️ Недостаточно прав.")
        return

    dept = _ROLE_TO_DEPT[role]
    logger.info("/rates: %s запрашивает персональные ставки отдела %s", tg_id, dept)

    employees = await get_users_rates_by_department(DB_PATH, dept)
    if dept == "Зал":
        mop_employees = await get_users_rates_by_department(DB_PATH, "МОП")
        employees = employees + mop_employees

    if not employees:
        await message.answer("Нет сотрудников в отделе")
        return

    # Группируем по позиции, порядок — из _positions_for_dept
    by_position: dict[str, list] = {}
    for emp in employees:
        pos = emp.get("position") or "—"
        by_position.setdefault(pos, []).append(emp)

    ordered = _positions_for_dept(dept)
    for pos in by_position:
        if pos not in ordered:
            ordered.append(pos)

    lines = [f"📊 Ставки отдела «{dept}»"]
    for pos in ordered:
        group = by_position.get(pos)
        if not group:
            continue
        n = len(group)
        rates_unique = {(emp.get("base_rate"), emp.get("extra_rate")) for emp in group}
        if len(rates_unique) == 1:
            # Все одинаковые — схлопываем
            rate_str = _fmt_emp_rate(group[0])
            if n > 1:
                lines.append(f"{pos} ({n} чел.): {rate_str}")
            else:
                lines.append(f"{pos}: {rate_str}")
        else:
            # Разные — раскрываем список
            lines.append(f"{pos}:")
            for emp in group:
                lines.append(f"— {emp['full_name']}: {_fmt_emp_rate(emp)}")

    await message.answer("\n".join(lines))


# --- /set_rate ---

async def _setrate_get_employees(dept: str) -> list[dict]:
    """Возвращает сотрудников отдела с персональными ставками. Зал включает МОП."""
    employees = await get_users_rates_by_department(DB_PATH, dept)
    if dept == "Зал":
        employees += await get_users_rates_by_department(DB_PATH, "МОП")
    return employees


@admin_router.message(Command("set_rate"))
async def cmd_set_rate(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    role = await _resolve_sender_role(tg_id)
    if role not in _ROLE_TO_DEPT:
        logger.warning("/set_rate: доступ запрещён для %s (role=%s)", tg_id, role)
        await message.answer("⛔️ Недостаточно прав.")
        return

    dept = _ROLE_TO_DEPT[role]
    logger.info("/set_rate: шаг 1 — выбор позиции, %s, отдел %s", tg_id, dept)

    employees = await _setrate_get_employees(dept)
    if not employees:
        await message.answer("Нет сотрудников в отделе.")
        return

    positions: list[str] = []
    seen: set[str] = set()
    for emp in employees:
        pos = emp.get("position") or "—"
        if pos not in seen:
            positions.append(pos)
            seen.add(pos)

    await state.update_data(set_rate_dept=dept)
    await state.set_state(SetRateStates.waiting_position)

    buttons = [
        [InlineKeyboardButton(text=pos, callback_data=f"setrate_pos:{pos}")]
        for pos in positions
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="setrate_cancel")])
    await message.answer(
        f"Выберите позицию ({dept}):",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@admin_router.callback_query(SetRateStates.waiting_position, F.data.startswith("setrate_pos:"))
async def cb_setrate_position(callback: CallbackQuery, state: FSMContext):
    position = callback.data.split(":", 1)[1]
    data = await state.get_data()
    dept = data["set_rate_dept"]
    logger.info("/set_rate: шаг 2 — выбор сотрудника, позиция=%s", position)

    employees = await _setrate_get_employees(dept)
    group = [emp for emp in employees if (emp.get("position") or "—") == position]
    if not group:
        await callback.answer("Сотрудников нет.", show_alert=True)
        return

    await state.update_data(set_rate_position=position)
    await state.set_state(SetRateStates.waiting_employee)

    buttons = [
        [InlineKeyboardButton(
            text=f"{emp['full_name']} ({_fmt_emp_rate(emp)})",
            callback_data=f"setrate_emp:{emp['telegram_id']}",
        )]
        for emp in group
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="setrate_cancel")])
    await callback.message.edit_text(
        f"Позиция: {position}\nВыберите сотрудника:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )
    await callback.answer()


@admin_router.callback_query(SetRateStates.waiting_employee, F.data.startswith("setrate_emp:"))
async def cb_setrate_employee(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    dept = data["set_rate_dept"]
    position = data["set_rate_position"]
    logger.info("/set_rate: шаг 3 — ввод ставки, сотрудник=%s позиция=%s", target_id, position)

    employees = await _setrate_get_employees(dept)
    emp = next((e for e in employees if e["telegram_id"] == target_id), None)
    full_name = emp["full_name"] if emp else str(target_id)
    current_rate = _fmt_emp_rate(emp) if emp else "не установлена"

    await state.update_data(set_rate_target_id=target_id, set_rate_full_name=full_name)
    await state.set_state(SetRateStates.waiting_new_rate)

    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отмена", callback_data="setrate_cancel")]
    ])
    if position in POSITIONS_WITH_EXTRA:
        prompt = (
            f"Сотрудник: {full_name}\n"
            f"Текущая ставка: {current_rate}\n\n"
            f"Введите базовую ставку (р/ч):"
        )
    else:
        prompt = (
            f"Сотрудник: {full_name}\n"
            f"Текущая ставка: {current_rate}\n\n"
            f"Введите новую ставку (р/ч):"
        )
    await callback.message.edit_text(prompt, reply_markup=cancel_kb)
    await callback.answer()


@admin_router.message(SetRateStates.waiting_new_rate)
async def msg_setrate_new_rate(message: Message, state: FSMContext):
    data = await state.get_data()
    position = data["set_rate_position"]
    target_id = data["set_rate_target_id"]
    full_name = data["set_rate_full_name"]

    text = message.text.strip().replace(",", ".")
    try:
        base_rate = float(text)
        if base_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число больше 0:")
        return

    if position in POSITIONS_WITH_EXTRA:
        await state.update_data(set_rate_base=base_rate)
        await state.set_state(SetRateStates.waiting_extra_rate)
        extra_label = EXTRA_RATE_LABELS.get(position, "повышенную")
        logger.info("/set_rate: base=%s для user_id=%s, запрашиваю %s ставку", base_rate, target_id, extra_label)
        await message.answer(f"Введите повышенную ставку (выходные дни, р/ч):")
    else:
        await set_user_rate(DB_PATH, target_id, base_rate, extra_rate=None)
        await state.clear()
        logger.info("/set_rate: сохранено для user_id=%s: base=%s", target_id, base_rate)
        await message.answer(f"✅ Ставка обновлена: {full_name} — {_fmt_money(base_rate)} р/ч")


@admin_router.message(SetRateStates.waiting_extra_rate)
async def msg_setrate_extra_rate(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data["set_rate_target_id"]
    full_name = data["set_rate_full_name"]
    base_rate = data["set_rate_base"]

    text = message.text.strip().replace(",", ".")
    try:
        extra_rate = float(text)
        if extra_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число больше 0:")
        return

    await set_user_rate(DB_PATH, target_id, base_rate, extra_rate)
    await state.clear()

    logger.info(
        "/set_rate: сохранено для user_id=%s: base=%s extra=%s",
        target_id, base_rate, extra_rate,
    )
    await message.answer(
        f"✅ Ставка обновлена: {full_name} — {_fmt_money(base_rate)}/{_fmt_money(extra_rate)} р/ч"
    )


@admin_router.callback_query(F.data == "setrate_cancel")
async def cb_setrate_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Отменено.")
    await callback.answer()


# --- /message_dept ---

@admin_router.message(Command("message_dept"))
async def cmd_message_dept(message: Message, state: FSMContext, user_role: str = "guest"):
    tg_id = message.from_user.id

    if user_role not in _ALLOWED_ROLES:
        logger.warning("/message_dept: доступ запрещён для %s (role=%s)", tg_id, user_role)
        await message.answer("⛔️ Недостаточно прав.")
        return

    if user_role == "admin_hall":
        await state.set_state(AuthStates.waiting_broadcast_dept)
        logger.info("/message_dept: %s (role=admin_hall) → показываю выбор Зал/МОП", tg_id)
        await message.answer("Выберите отдел для рассылки:", reply_markup=_hall_dept_keyboard())
    elif user_role in _ROLE_TO_DEPT:
        dept = _ROLE_TO_DEPT[user_role]
        await state.update_data(broadcast_type="dept", broadcast_dept=dept)
        await state.set_state(AuthStates.waiting_broadcast_text)
        logger.info("/message_dept: %s (role=%s) → отдел %s, запрашиваю текст", tg_id, user_role, dept)
        await message.answer(f"Введите текст сообщения для отдела {dept}:")
    else:
        # superadmin / developer — выбор отдела
        await state.set_state(AuthStates.waiting_broadcast_dept)
        logger.info("/message_dept: %s (role=%s) → показываю выбор отдела", tg_id, user_role)
        await message.answer("Выберите отдел для рассылки:", reply_markup=_dept_keyboard())


@admin_router.callback_query(AuthStates.waiting_broadcast_dept, F.data.startswith("broadcast_dept:"))
async def cb_broadcast_dept(callback: CallbackQuery, state: FSMContext):
    dept = callback.data.split(":", 1)[1]
    await state.update_data(broadcast_type="dept", broadcast_dept=dept)
    await state.set_state(AuthStates.waiting_broadcast_text)
    await callback.message.edit_text(f"Введите текст сообщения для отдела {dept}:")
    await callback.answer()
    logger.info("broadcast_dept: %s выбрал отдел %s", callback.from_user.id, dept)


@admin_router.callback_query(AuthStates.waiting_broadcast_dept, F.data == "broadcast_cancel")
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Рассылка отменена.")
    await callback.answer()


# --- waiting_broadcast_text (общий для /message_dept и /message_all) ---

@admin_router.message(AuthStates.waiting_broadcast_text)
async def msg_broadcast_text(message: Message, state: FSMContext):
    text = message.text or ""
    data = await state.get_data()
    broadcast_type = data.get("broadcast_type", "dept")
    tg_id = message.from_user.id

    await state.clear()

    if broadcast_type == "all":
        recipients = await get_all_users(DB_PATH)
        label = "всем сотрудникам"
    else:
        dept = data.get("broadcast_dept", "")
        recipients = await get_users_by_department(DB_PATH, dept)
        if dept == "Зал":
            mop_users = await get_users_by_department(DB_PATH, "МОП")
            seen = {u["telegram_id"] for u in recipients}
            recipients += [u for u in mop_users if u["telegram_id"] not in seen]
        label = f"сотрудникам отдела {dept}"

    sender_role = await _resolve_sender_role(tg_id)
    sender_label = ROLE_TO_SENDER.get(sender_role, "администрации")
    broadcast_text = f"📢 Сообщение от {sender_label}\n\n{text}"
    sent = 0
    for user in recipients:
        try:
            await message.bot.send_message(chat_id=user["telegram_id"], text=broadcast_text)
            sent += 1
        except Exception:
            error_logger.exception(
                "broadcast: не удалось отправить сообщение пользователю %s", user["telegram_id"]
            )
        await asyncio.sleep(0.05)

    logger.info(
        "broadcast: %s отправил рассылку %s, получателей: %d/%d",
        tg_id, label, sent, len(recipients),
    )
    await message.answer(f"✅ Сообщение отправлено {sent} {label}")
