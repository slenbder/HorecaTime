import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from app.bot.fsm.shift_states import ShiftStates
from app.db.models import get_user
from app.services.google_sheets import GoogleSheetsClient
from app.services.timeparsing import parse_shift
from config import ADMIN_HALL_IDS

userhours_router = Router()
logger = logging.getLogger("app")
error_logger = logging.getLogger("errors")

try:
    sheets_client = GoogleSheetsClient()
    logger.info("userhours: GoogleSheetsClient успешно инициализирован")
except Exception:
    logger.exception("userhours: Ошибка при инициализации GoogleSheetsClient")
    sheets_client = None


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------

def _fmt_h(v: float) -> str:
    """8.0 → '8', 8.5 → '8.5'"""
    return str(int(v)) if v == int(v) else str(v)


def _fmt_time(t: float) -> str:
    """Часы как float → 'HH:MM'"""
    h = int(t)
    m = int(round((t - h) * 60))
    return f"{h:02d}:{m:02d}"


def _date_str(day: int, month: int, year: int) -> str:
    return f"{day:02d}.{month:02d}.{str(year)[2:]}"


# ---------------------------------------------------------------------------
# Шаг 1 — /shift
# ---------------------------------------------------------------------------

@userhours_router.message(Command("shift"))
async def cmd_shift(message: Message, state: FSMContext):
    tg_id = message.from_user.id

    user_data = get_user(tg_id)
    if not user_data or user_data.get("role") != "user":
        return

    if sheets_client is None:
        await message.answer("❌ Ошибка подключения к таблице. Обратитесь к администратору.")
        return

    try:
        user_info = sheets_client.get_user_from_techlist(tg_id)
    except Exception:
        error_logger.exception("cmd_shift: ошибка получения данных пользователя %s из техлиста", tg_id)
        await message.answer("❌ Ошибка получения данных. Попробуйте позже.")
        return

    position = user_info.get("position", "") if user_info else ""

    if position != "Раннер":
        await message.answer("❌ Команда /shift пока доступна только для раннеров.")
        return

    await state.update_data(position=position)
    await message.answer(
        "Введите смену в формате:\n\n"
        "<code>13.03 10:00-20:00</code>"
    )
    await state.set_state(ShiftStates.waiting_shift_input)


# ---------------------------------------------------------------------------
# Шаг 2 — ввод даты и времени
# ---------------------------------------------------------------------------

@userhours_router.message(ShiftStates.waiting_shift_input)
async def process_shift_input(message: Message, state: FSMContext):
    data = await state.get_data()
    position = data.get("position", "Раннер")

    result = parse_shift(message.text or "", position)

    if result is None:
        await message.answer(
            "❌ Не удалось распознать формат. Попробуйте ещё раз:\n\n"
            "<code>13.03 10:00-20:00</code>"
        )
        return

    await state.update_data(**result)

    h = result["h"]
    is_weekend = result["is_weekend"]
    date = _date_str(result["day"], result["month"], result["year"])
    weekend_note = " (выходной день)" if is_weekend else ""

    await message.answer(
        f"⏱ Смена {date}: Часы смены = {_fmt_h(h)} ч{weekend_note}\n\n"
        f"Введите доп. часы или 0:"
    )
    await state.set_state(ShiftStates.waiting_ah_input)


# ---------------------------------------------------------------------------
# Шаг 3 — ввод AH
# ---------------------------------------------------------------------------

@userhours_router.message(ShiftStates.waiting_ah_input)
async def process_ah_input(message: Message, state: FSMContext):
    text = (message.text or "").strip().replace(",", ".")

    try:
        ah = float(text)
        if ah < 0:
            raise ValueError
    except ValueError:
        await message.answer("❌ Введите число, например: 3 или 2.5")
        return

    await state.update_data(ah=ah)

    if ah == 0:
        await _write_and_finish(message, state)
        return

    await message.answer("💬 Добавьте комментарий к доп. часам:")
    await state.set_state(ShiftStates.waiting_ah_comment)


# ---------------------------------------------------------------------------
# Шаг 4 — комментарий к AH
# ---------------------------------------------------------------------------

@userhours_router.message(ShiftStates.waiting_ah_comment)
async def process_ah_comment(message: Message, state: FSMContext):
    await state.update_data(comment=(message.text or "").strip())
    await _write_and_finish(message, state)


# ---------------------------------------------------------------------------
# Запись в таблицу + уведомления
# ---------------------------------------------------------------------------

async def _write_and_finish(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    data = await state.get_data()

    day      = data["day"]
    month    = data["month"]
    year     = data["year"]
    h        = data["h"]
    ah       = data.get("ah", 0.0)
    comment  = data.get("comment", "")
    is_weekend = data.get("is_weekend", False)
    start    = data.get("start", 0.0)
    end      = data.get("end", 0.0)

    date = _date_str(day, month, year)

    if sheets_client is None:
        await message.answer("❌ Ошибка записи. Попробуйте позже.")
        await state.clear()
        return

    try:
        sheets_client.write_shift(tg_id, day, month, year, h, ah)
    except Exception:
        error_logger.exception("_write_and_finish: ошибка записи смены для %s", tg_id)
        await message.answer("❌ Ошибка записи. Попробуйте позже.")
        await state.clear()
        return

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)

    logger.info(
        "Смена записана: user=%s (%s), date=%s, H=%s, AH=%s",
        tg_id, full_name, date, h, ah,
    )

    # Ответ пользователю
    if ah > 0:
        await message.answer(
            f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(h)} ч | Доп. часы = {_fmt_h(ah)} ч"
        )
    else:
        await message.answer(f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(h)} ч")

    # Уведомление admin_hall
    weekend_mark = " 🌟 (выходной)" if is_weekend else ""
    time_range = f"{_fmt_time(start)}–{_fmt_time(end)}"

    if ah > 0:
        admin_text = (
            f"📋 Раннер внёс смену\n\n"
            f"👤 {full_name}\n"
            f"📅 {date}\n"
            f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч{weekend_mark}\n"
            f"🔢 Доп. часы = {_fmt_h(ah)} ч\n"
            f"💬 {comment}"
        )
    else:
        admin_text = (
            f"📋 Раннер внёс смену\n\n"
            f"👤 {full_name}\n"
            f"📅 {date}\n"
            f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч{weekend_mark}"
        )

    for admin_id in ADMIN_HALL_IDS:
        try:
            await message.bot.send_message(chat_id=admin_id, text=admin_text)
            logger.info("Notified admin %s", admin_id)
        except Exception as e:
            error_logger.error("Не удалось уведомить admin_hall %s: %s", admin_id, e)

    await state.clear()
