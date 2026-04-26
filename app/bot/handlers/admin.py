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
from app.bot.fsm.shift_states import SetRateStates
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

@admin_router.message(Command("set_rate"))
async def cmd_set_rate(message: Message, state: FSMContext) -> None:
    user_id = message.from_user.id
    user_role = await _resolve_sender_role(user_id)

    if user_role not in ("admin_hall", "admin_bar", "admin_kitchen") and \
       user_id not in SUPERADMIN_IDS and user_id != DEVELOPER_ID:
        await message.answer("⛔️ У вас нет прав для изменения ставок.")
        return

    logger.info("/set_rate: запрос от %s (role=%s)", user_id, user_role)

    if user_role in ("admin_hall", "admin_bar", "admin_kitchen"):
        dept = _ROLE_TO_DEPT.get(user_role)
        if not dept:
            await message.answer("⚠️ Не удалось определить ваш отдел.")
            return

        await state.update_data(department=dept)
        await state.set_state(SetRateStates.waiting_position)

        positions = _positions_for_dept(dept)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=pos, callback_data=f"setrate_pos:{pos}")]
            for pos in positions
        ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_set_rate")]])

        await message.answer(f"Выберите позицию ({dept}):", reply_markup=kb)
    else:
        await state.set_state(SetRateStates.waiting_department)

        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=dept, callback_data=f"setrate_dept:{dept}")]
            for dept in ["Зал", "Бар", "Кухня", "МОП"]
        ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_set_rate")]])

        await message.answer("Выберите отдел:", reply_markup=kb)


@admin_router.callback_query(SetRateStates.waiting_department, F.data.startswith("setrate_dept:"))
async def process_department(callback: CallbackQuery, state: FSMContext) -> None:
    dept = callback.data.split(":", 1)[1]
    logger.info("/set_rate: суперадмин %s выбрал отдел %s", callback.from_user.id, dept)

    await state.update_data(department=dept)
    await state.set_state(SetRateStates.waiting_position)

    positions = _positions_for_dept(dept)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=pos, callback_data=f"setrate_pos:{pos}")]
        for pos in positions
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_set_rate")]])

    await callback.message.edit_text(f"Выберите позицию ({dept}):", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(SetRateStates.waiting_position, F.data.startswith("setrate_pos:"))
async def process_position(callback: CallbackQuery, state: FSMContext) -> None:
    position = callback.data.split(":", 1)[1]
    data = await state.get_data()
    dept = data.get("department")
    logger.info("/set_rate: выбрана позиция %s (отдел %s)", position, dept)

    await state.update_data(position=position)
    await state.set_state(SetRateStates.waiting_employee)

    employees = await get_users_rates_by_department(DB_PATH, dept)
    if dept == "Зал":
        employees += await get_users_rates_by_department(DB_PATH, "МОП")
    employees = [e for e in employees if e.get("position") == position]

    if not employees:
        await callback.message.edit_text(
            f"⚠️ В отделе {dept} нет сотрудников с позицией {position}."
        )
        await state.clear()
        await callback.answer()
        return

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text=e["full_name"],
            callback_data=f"setrate_emp:{e['telegram_id']}",
        )]
        for e in employees
    ] + [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_set_rate")]])

    await callback.message.edit_text(f"Выберите сотрудника ({position}):", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(SetRateStates.waiting_employee, F.data.startswith("setrate_emp:"))
async def process_employee(callback: CallbackQuery, state: FSMContext) -> None:
    telegram_id = int(callback.data.split(":", 1)[1])
    logger.info("/set_rate: выбран сотрудник %s", telegram_id)

    await state.update_data(target_telegram_id=telegram_id)
    await state.set_state(SetRateStates.waiting_period_choice)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 С текущего месяца", callback_data="setrate_period:current")],
        [InlineKeyboardButton(text="📆 Со следующего месяца", callback_data="setrate_period:next")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel_set_rate")],
    ])

    await callback.message.edit_text("Когда применить изменение ставки?", reply_markup=kb)
    await callback.answer()


@admin_router.callback_query(F.data == "cancel_set_rate")
async def cancel_set_rate(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("❌ Установка ставки отменена.")
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
