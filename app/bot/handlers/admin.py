import asyncio
import logging

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
)

from app.bot.fsm.auth_states import AuthStates, SetRateStates
from app.db.models import get_users_by_department, get_all_users, get_all_rates, update_rate
from config import DB_PATH, SUPERADMIN_IDS, DEVELOPER_ID, ADMIN_HALL_IDS, ADMIN_BAR_IDS, ADMIN_KITCHEN_IDS

admin_router = Router()
logger = logging.getLogger(__name__)
error_logger = logging.getLogger("errors")

_ALLOWED_ROLES = {"admin_hall", "admin_bar", "admin_kitchen", "superadmin", "developer"}

_ROLE_TO_DEPT = {
    "admin_hall":    "Зал",
    "admin_bar":     "Бар",
    "admin_kitchen": "Кухня",
}

_DEPT_BUTTONS = ["Зал", "Бар", "Кухня"]

_DEPT_POSITIONS = {
    "Зал":   ["Менеджер", "Официант", "Раннер", "Хостесс"],
    "Бар":   ["Бармен", "Барбэк"],
    "Кухня": ["Су-шеф", "Горячий цех", "Холодный цех", "Кондитерский цех",
               "Заготовочный цех", "Коренной цех", "МОП"],
}

_POSITIONS_WITH_EXTRA = {"Бармен", "Барбэк", "Раннер"}
_EXTRA_LABEL = {"Бармен": "тусовочные", "Барбэк": "тусовочные", "Раннер": "выходные"}

ROLE_TO_SENDER = {
    "admin_hall":    "администратора Зала",
    "admin_bar":     "администратора Бара",
    "admin_kitchen": "администратора Кухни",
    "superadmin":    "администрации",
    "developer":     "администрации",
}


def _resolve_sender_role(tg_id: int) -> str:
    if tg_id in SUPERADMIN_IDS or tg_id == DEVELOPER_ID:
        return "superadmin"
    if tg_id in ADMIN_HALL_IDS:
        return "admin_hall"
    if tg_id in ADMIN_BAR_IDS:
        return "admin_bar"
    if tg_id in ADMIN_KITCHEN_IDS:
        return "admin_kitchen"
    return "superadmin"


def _dept_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=dept, callback_data=f"broadcast_dept:{dept}")]
        for dept in _DEPT_BUTTONS
    ]
    buttons.append([InlineKeyboardButton(text="❌ Отмена", callback_data="broadcast_cancel")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _fmt_money(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def _rates_keyboard_for_dept(dept: str) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text=pos, callback_data=f"admin_rate_pos:{pos}")]
        for pos in _DEPT_POSITIONS.get(dept, [])
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# --- /rates ---

@admin_router.message(Command("rates"))
async def cmd_rates(message: Message):
    tg_id = message.from_user.id
    role = _resolve_sender_role(tg_id)
    if role not in _ROLE_TO_DEPT:
        logger.warning("/rates: доступ запрещён для %s (role=%s)", tg_id, role)
        await message.answer("⛔️ Недостаточно прав.")
        return

    dept = _ROLE_TO_DEPT[role]
    positions = _DEPT_POSITIONS[dept]
    logger.info("/rates: %s запрашивает ставки отдела %s", tg_id, dept)

    all_rates = await get_all_rates(DB_PATH)
    rate_map = {r["position"]: r for r in all_rates}

    lines = [f"💰 Ставки отдела {dept}:\n"]
    for pos in positions:
        r = rate_map.get(pos)
        if r is None:
            continue
        base_str = f"{_fmt_money(r['base_rate'])} р/ч"
        if r["extra_rate"] is not None:
            label = _EXTRA_LABEL.get(pos, "повышенная")
            lines.append(f"{pos}: {base_str} ({label}: {_fmt_money(r['extra_rate'])} р/ч)")
        else:
            lines.append(f"{pos}: {base_str}")

    await message.answer("\n".join(lines))


# --- /set_rate ---

@admin_router.message(Command("set_rate"))
async def cmd_set_rate(message: Message, state: FSMContext):
    tg_id = message.from_user.id
    role = _resolve_sender_role(tg_id)
    if role not in _ROLE_TO_DEPT:
        logger.warning("/set_rate: доступ запрещён для %s (role=%s)", tg_id, role)
        await message.answer("⛔️ Недостаточно прав.")
        return

    dept = _ROLE_TO_DEPT[role]
    logger.info("/set_rate: %s (отдел %s) запускает FSM", tg_id, dept)
    await state.update_data(admin_rate_dept=dept)
    await state.set_state(SetRateStates.waiting_set_rate_position)
    await message.answer(
        f"Выберите позицию для изменения ставки ({dept}):",
        reply_markup=_rates_keyboard_for_dept(dept),
    )


@admin_router.callback_query(
    SetRateStates.waiting_set_rate_position,
    F.data.startswith("admin_rate_pos:"),
)
async def cb_admin_rate_position(callback: CallbackQuery, state: FSMContext):
    position = callback.data.split(":", 1)[1]
    await state.update_data(position=position)
    await state.set_state(SetRateStates.waiting_set_rate_base)
    await callback.message.edit_text(
        f"Позиция: <b>{position}</b>\n\nВведите базовую ставку (р/час):"
    )
    await callback.answer()


@admin_router.message(SetRateStates.waiting_set_rate_base)
async def msg_admin_rate_base(message: Message, state: FSMContext):
    # Обрабатываем только если запущено через /set_rate (admin), не /set_rate_all (superadmin)
    data = await state.get_data()
    if "admin_rate_dept" not in data:
        return  # передаём superadmin_router

    text = message.text.strip().replace(",", ".")
    try:
        base_rate = float(text)
        if base_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число больше 0:")
        return

    position = data["position"]
    await state.update_data(base_rate=base_rate)

    if position in _POSITIONS_WITH_EXTRA:
        await state.set_state(SetRateStates.waiting_set_rate_extra)
        extra_label = _EXTRA_LABEL.get(position, "повышенную")
        await message.answer(f"Введите {extra_label} ставку (р/час):")
    else:
        await _admin_save_rate(message, state, position, base_rate, extra_rate=None)


@admin_router.message(SetRateStates.waiting_set_rate_extra)
async def msg_admin_rate_extra(message: Message, state: FSMContext):
    data = await state.get_data()
    if "admin_rate_dept" not in data:
        return  # передаём superadmin_router

    text = message.text.strip().replace(",", ".")
    try:
        extra_rate = float(text)
        if extra_rate <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число больше 0:")
        return

    position = data["position"]
    base_rate = data["base_rate"]
    await _admin_save_rate(message, state, position, base_rate, extra_rate)


async def _admin_save_rate(message: Message, state: FSMContext,
                           position: str, base_rate: float, extra_rate: float | None):
    await update_rate(DB_PATH, position, base_rate, extra_rate)
    await state.clear()

    extra_str = ""
    if extra_rate is not None:
        label = _EXTRA_LABEL.get(position, "повышенная")
        extra_str = f", {label}: {_fmt_money(extra_rate)} р/ч"

    logger.info(
        "set_rate: позиция=%s base=%s extra=%s (от %s)",
        position, base_rate, extra_rate, message.from_user.id,
    )
    await message.answer(
        f"✅ Ставка обновлена: {position} — {_fmt_money(base_rate)} р/ч{extra_str}"
    )


# --- /message_dept ---

@admin_router.message(Command("message_dept"))
async def cmd_message_dept(message: Message, state: FSMContext, user_role: str = "guest"):
    tg_id = message.from_user.id

    if user_role not in _ALLOWED_ROLES:
        logger.warning("/message_dept: доступ запрещён для %s (role=%s)", tg_id, user_role)
        await message.answer("⛔️ Недостаточно прав.")
        return

    if user_role in _ROLE_TO_DEPT:
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
        label = f"сотрудникам отдела {dept}"

    sender_role = _resolve_sender_role(tg_id)
    sender_label = ROLE_TO_SENDER[sender_role]
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
