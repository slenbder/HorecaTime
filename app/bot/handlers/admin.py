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
from app.db.models import get_users_by_department, get_all_users
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
