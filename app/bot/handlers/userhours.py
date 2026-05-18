import asyncio
import html
import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    LinkPreviewOptions,
    Message,
)

from app.bot.fsm.shift_states import ShiftStates
from app.db.models import get_user
from app.services.google_sheets import GoogleSheetsClient
from app.services.timeparsing import parse_shift, check_overlap, parse_time, round_to_half
from app.utils.text_utils import make_mention
from config import DB_PATH
from app.db.models import get_admins_by_department

userhours_router = Router()
logger = logging.getLogger(__name__)
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
# Константы позиций
# ---------------------------------------------------------------------------

KITCHEN_POSITIONS = {
    "Руководящий состав", "Горячий цех", "Холодный цех",
    "Кондитерский цех", "Заготовочный цех", "Коренной цех",
    "Грузчик", "Закупщик",
}
HALL_SIMPLE_POSITIONS = {"Хостесс", "Менеджер"}
MOP_POSITIONS = {"Клининг", "Котломой"}

# Позиции с механикой «только H, одна ставка, несколько смен одним сообщением»
SIMPLE_H_POSITIONS = KITCHEN_POSITIONS | HALL_SIMPLE_POSITIONS | MOP_POSITIONS

BAR_POSITIONS = {"Бармен", "Барбэк"}


def _shift_example() -> str:
    """Возвращает актуальный пример смены на основе текущего времени МСК."""
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    date_str = now.strftime("%d.%m")

    total_half_hours = (now.hour * 60 + now.minute) // 30
    end_hour = total_half_hours // 2
    end_min = 30 if total_half_hours % 2 else 0
    end_str = f"{end_hour:02d}:{end_min:02d}"

    start_total = total_half_hours - 20  # 20 получасов = 10 часов
    if start_total < 0:
        start_total += 48
    start_hour = (start_total // 2) % 24
    start_min = 30 if start_total % 2 else 0
    start_str = f"{start_hour:02d}:{start_min:02d}"

    return f"{date_str} {start_str}-{end_str}"


# ---------------------------------------------------------------------------
# Буферы для накопления медиагрупп (Официант)
# ---------------------------------------------------------------------------

# mgid → [file_id, ...]
_mg_photos: dict[str, list[str]] = {}
# mgid → {"caption": str|None, "message": Message, "state": FSMContext}
_mg_context: dict[str, dict] = {}
# mgids уже запланированных для обработки
_mg_scheduled: set[str] = set()
# asyncio.Lock per mgid — защита от race condition при параллельной доставке фото
_mg_locks: dict[str, asyncio.Lock] = {}

# Буферы для карт лояльности
_mg_loyalty_photos: dict[str, list[str]] = {}
_mg_loyalty_context: dict[str, dict] = {}
_mg_loyalty_scheduled: set[str] = set()
_mg_loyalty_locks: dict[str, asyncio.Lock] = {}

# Буферы для наполняемости чеков
_mg_filling_photos: dict[str, list[str]] = {}
_mg_filling_context: dict[str, dict] = {}
_mg_filling_scheduled: set[str] = set()
_mg_filling_locks: dict[str, asyncio.Lock] = {}

# Pending контексты для апрува
_pending_loyalty: dict[str, dict] = {}
_pending_filling: dict[str, dict] = {}


# ---------------------------------------------------------------------------
# Шаг 1 — /shift
# ---------------------------------------------------------------------------

@userhours_router.message(Command("shift"))
async def cmd_shift(message: Message, state: FSMContext):
    tg_id = message.from_user.id

    user_data = get_user(tg_id)
    role = user_data.get("role") if user_data else None
    if not user_data or role not in ("user", "admin_hall", "admin_bar", "admin_kitchen"):
        await message.answer("❌ Внесение смен недоступно для вашей роли.")
        return

    if sheets_client is None:
        await message.answer("❌ Ошибка подключения к таблице. Обратитесь к администратору.")
        return

    position = user_data.get("position", "")
    logger.info("cmd_shift: user_id=%s, role=%s, position=%s", tg_id, role, position)

    await state.update_data(position=position)

    example = _shift_example()

    if position == "Раннер":
        await message.answer(
            "Введите смену в формате:\n\n"
            f"<code>{example}</code>"
        )
        await state.set_state(ShiftStates.waiting_shift_input)
    elif position in SIMPLE_H_POSITIONS:
        await message.answer(
            "Введите смену или несколько смен:\n\n"
            f"<code>{example}</code>"
        )
        await state.set_state(ShiftStates.waiting_shift_input)
    elif position in BAR_POSITIONS:
        await message.answer(
            "Введите смену:\n\n"
            f"<code>{example}</code>"
        )
        await state.set_state(ShiftStates.waiting_shift_input)
    elif position == "Официант":
        logger.info("cmd_shift: Официант, user=%s, устанавливаем waiting_shift_input", tg_id)
        await message.answer(
            "Введите смену:\n\n"
            f"<code>{example}</code>\n\n"
            "Можно отменить ввод командой /cancel"
        )
        await state.set_state(ShiftStates.waiting_shift_input)
    else:
        await message.answer("❌ Команда /shift пока недоступна для вашей позиции.")
        await state.clear()


# ---------------------------------------------------------------------------
# /cancel — отмена текущего действия
# ---------------------------------------------------------------------------

@userhours_router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    """Отменить текущее действие (внесение смены)."""
    current_state = await state.get_state()
    user_id = message.from_user.id

    if current_state is None:
        await message.answer("Нет активных действий для отмены.")
        return

    # Edge case: Официант с медиагруппой в обработке.
    # mgid не хранится в FSM state — ищем по user_id в глобальных буферах.
    for mgid, ctx in list(_mg_context.items()):
        if ctx["message"].from_user.id == user_id:
            ctx["cancelled"] = True
            logger.info(
                "cmd_cancel: установлен флаг отмены для mgid=%s (user_id=%s)",
                mgid, user_id,
            )
            break

    for mgid, ctx in list(_mg_loyalty_context.items()):
        if ctx["message"].from_user.id == user_id:
            ctx["cancelled"] = True
            logger.info(
                "cmd_cancel: установлен флаг отмены для loyalty mgid=%s (user_id=%s)",
                mgid, user_id,
            )
            break

    for mgid, ctx in list(_mg_filling_context.items()):
        if ctx["message"].from_user.id == user_id:
            ctx["cancelled"] = True
            logger.info(
                "cmd_cancel: установлен флаг отмены для filling mgid=%s (user_id=%s)",
                mgid, user_id,
            )
            break

    await state.clear()
    await message.answer(
        "✅ Действие отменено. Данные не сохранены.\n\n"
        "Чтобы внести смену заново, используйте /shift"
    )
    logger.info(
        "cmd_cancel: пользователь %s отменил FSM из состояния %s",
        user_id, current_state,
    )


# ---------------------------------------------------------------------------
# Шаг 2 — ввод даты и времени
# ---------------------------------------------------------------------------

@userhours_router.message(ShiftStates.waiting_shift_input)
async def process_shift_input(message: Message, state: FSMContext):
    data = await state.get_data()
    position = data.get("position", "Раннер")

    if position in SIMPLE_H_POSITIONS:
        await _process_simple_h_shifts(message, state, position)
        return

    if position in BAR_POSITIONS:
        await _process_bar_shift_input(message, state, position)
        return

    if position == "Официант":
        result = parse_shift(message.text or "", "Официант")
        if result is None:
            await message.answer(
                "❌ Не удалось распознать формат смены. Попробуйте ещё раз:\n\n"
                "<code>13.03 10:00-20:00</code>"
            )
            return

        tg_id = message.from_user.id
        if sheets_client is None:
            await message.answer("❌ Ошибка подключения к таблице. Попробуйте позже.")
            await state.clear()
            return

        try:
            sheets_client.write_shift(tg_id, result["day"], result["month"], result["year"], result["h"], 0.0)
        except Exception:
            error_logger.exception("process_shift_input: ошибка записи смены для %s", tg_id)
            await message.answer("❌ Ошибка записи. Попробуйте позже.")
            await state.clear()
            return

        date = _date_str(result["day"], result["month"], result["year"])
        logger.info(
            "Смена записана: user=%s, date=%s, H=%s, position=Официант",
            tg_id, date, _fmt_h(result["h"]),
        )
        await state.update_data(shift_date=date, shift_hours=result["h"])
        await message.answer(f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(result['h'])} ч")
        await _ask_about_loyalty_cards(message, state)
        return

    # --- Раннер: одна смена, затем AH ---
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
    data = await state.get_data()
    position = data.get("position", "Раннер")

    if position in BAR_POSITIONS:
        await _process_bar_ah_input(message, state, position)
        return

    # --- Раннер ---
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
# Официант — шаг 2: накопление медиагруппы + запись
# ---------------------------------------------------------------------------

async def _process_waiter_shift_input(message: Message, state: FSMContext) -> None:
    tg_id = message.from_user.id
    logger.info(
        "_process_waiter_shift_input: вызван, user=%s, has_photo=%s, "
        "has_caption=%s, media_group_id=%s",
        tg_id,
        bool(message.photo),
        bool(message.caption),
        message.media_group_id,
    )

    if not message.photo:
        # Без фото — парсим текст и записываем сразу
        text = (message.text or "").strip()
        result = parse_shift(text, "Официант")
        if result is None:
            await message.answer(
                "❌ Не удалось распознать формат смены. Попробуйте ещё раз:\n\n"
                "<code>13.03 10:00-20:00</code>"
            )
            return
        await _write_waiter_no_photo(message, state, tg_id, result)
        return

    photo_file_id = message.photo[-1].file_id
    mgid = message.media_group_id

    if mgid:
        # Медиагруппа: накапливаем фото, caption читаем из любого фото группы
        lock = _mg_locks.setdefault(mgid, asyncio.Lock())
        async with lock:
            if mgid not in _mg_photos:
                _mg_photos[mgid] = []
                _mg_context[mgid] = {"caption": None, "message": message, "state": state}

            if _mg_photos[mgid] is None:
                # Группа уже помечена как ошибочная — игнорируем последующие фото
                return

            if message.caption and _mg_context[mgid]["caption"] is None:
                _mg_context[mgid]["caption"] = message.caption
                logger.info(
                    "_process_waiter_shift_input: caption получен от фото в группе %s, user=%s",
                    mgid, tg_id,
                )

            _mg_photos[mgid].append(photo_file_id)

            if mgid not in _mg_scheduled:
                _mg_scheduled.add(mgid)
                asyncio.create_task(_delayed_process_waiter(mgid))
    else:
        # Одиночное фото
        text = (message.caption or message.text or "").strip()
        result = parse_shift(text, "Официант")
        if result is None:
            await message.answer("❌ Не удалось распознать формат смены.")
            return
        await _send_waiter_report(message, state, tg_id, result, [photo_file_id])


async def _write_waiter_no_photo(
    message: Message,
    state: FSMContext,
    tg_id: int,
    result: dict,
) -> None:
    """Смена без фото — записываем сразу с AH=0, уведомляем без кнопок."""
    day   = result["day"]
    month = result["month"]
    year  = result["year"]
    h     = result["h"]
    start = result["start"]
    end   = result["end"]
    date  = _date_str(day, month, year)

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)

    if sheets_client is None:
        await message.answer("❌ Ошибка записи. Попробуйте позже.")
        await state.clear()
        return

    try:
        sheets_client.write_shift(tg_id, day, month, year, h, 0.0)
    except Exception:
        error_logger.exception("_write_waiter_no_photo: ошибка записи для %s", tg_id)
        await message.answer("❌ Ошибка записи. Попробуйте позже.")
        await state.clear()
        return

    logger.info(
        "Смена записана: user=%s, date=%s, H=%s, position=Официант (без фото)",
        tg_id, date, _fmt_h(h),
    )

    await state.clear()
    await message.answer(f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(h)} ч")

    hall_admin_ids = await get_admins_by_department(DB_PATH, "Зал")
    recipients = hall_admin_ids
    if not recipients:
        logger.warning("_write_waiter_no_photo: получатели пустые, уведомление не отправлено")
        return

    mention = make_mention(message.from_user.username, full_name)
    time_range = f"{_fmt_time(start)}–{_fmt_time(end)}"
    admin_text = (
        f"📋 Официант внёс смену\n\n"
        f"👤 {mention}\n"
        f"📅 {date}\n"
        f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч"
    )
    for admin_id in recipients:
        try:
            await message.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
            logger.info("_write_waiter_no_photo: уведомлен %s", admin_id)
        except Exception as e:
            error_logger.error("_write_waiter_no_photo: не удалось уведомить %s: %s", admin_id, e)


async def _delayed_process_waiter(mgid: str) -> None:
    """Ждёт 1 сек, чтобы все фото группы успели накопиться, затем обрабатывает."""
    try:
        await asyncio.sleep(1.0)

        lock = _mg_locks.setdefault(mgid, asyncio.Lock())
        async with lock:
            photo_ids = _mg_photos.get(mgid)
            if photo_ids is None:
                _mg_photos.pop(mgid, None)
                _mg_context.pop(mgid, None)
                _mg_scheduled.discard(mgid)
                _mg_locks.pop(mgid, None)
                return
            if not photo_ids:
                _mg_photos.pop(mgid, None)
                _mg_context.pop(mgid, None)
                _mg_scheduled.discard(mgid)
                _mg_locks.pop(mgid, None)
                return

            ctx = _mg_context.pop(mgid)
            _mg_photos.pop(mgid)
            _mg_scheduled.discard(mgid)
            _mg_locks.pop(mgid, None)

        message = ctx["message"]
        state = ctx["state"]
        caption = (ctx["caption"] or "").strip()

        # Проверка флага отмены (пользователь нажал /cancel пока накапливалась группа)
        if ctx.get("cancelled"):
            logger.info(
                "_delayed_process_waiter: mgid=%s отменён пользователем, пропускаем запись",
                mgid,
            )
            await state.clear()
            return

        logger.info(
            "_delayed_process_waiter: mgid=%s, photos=%d, caption=%r",
            mgid, len(photo_ids), caption,
        )

        result = parse_shift(caption, "Официант")
        if result is None:
            await message.answer("❌ Не удалось распознать формат смены.")
            await state.clear()
            return

        await _send_waiter_report(message, state, message.from_user.id, result, photo_ids)

    except Exception as e:
        error_logger.exception("_delayed_process_waiter: необработанная ошибка mgid=%s: %s", mgid, e)

        lock = _mg_locks.get(mgid)
        ctx = _mg_context.get(mgid)
        if ctx:
            try:
                await ctx["message"].answer("❌ Произошла ошибка при обработке фото. Попробуйте ещё раз.")
                await ctx["state"].clear()
            except Exception:
                error_logger.exception("_delayed_process_waiter: не удалось уведомить пользователя mgid=%s", mgid)

        if lock:
            async with lock:
                _mg_photos.pop(mgid, None)
                _mg_context.pop(mgid, None)
                _mg_scheduled.discard(mgid)
            _mg_locks.pop(mgid, None)
        else:
            _mg_photos.pop(mgid, None)
            _mg_context.pop(mgid, None)
            _mg_scheduled.discard(mgid)


async def _send_waiter_report(
    message: Message,
    state: FSMContext,
    tg_id: int,
    result: dict,
    photo_ids: list[str],
) -> None:
    """Отвечает официанту, сбрасывает FSM, отправляет отчёт admin_hall."""
    day   = result["day"]
    month = result["month"]
    year  = result["year"]
    h     = result["h"]
    start = result["start"]
    end   = result["end"]
    date  = _date_str(day, month, year)
    N     = len(photo_ids)

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)

    await state.clear()
    await message.answer("✅ Смена принята, ожидайте подтверждения администратора.")

    hall_admin_ids = await get_admins_by_department(DB_PATH, "Зал")
    recipients = hall_admin_ids
    if not recipients:
        logger.warning(
            "_send_waiter_report: получатели пустые, отчёт официанта %s не отправлен",
            tg_id,
        )
        return

    mention = make_mention(message.from_user.username, full_name)
    time_range = f"{_fmt_time(start)}–{_fmt_time(end)}"
    h_str = _fmt_h(h)
    approval_text = (
        f"👤 {mention} — Официант\n"
        f"📅 {date}\n"
        f"⏱ {time_range} → Часы смены = {h_str} ч\n"
        f"📎 Приложено фото: {N}\n\n"
        f"✅ Сколько фото засчитать как доп. часы?"
    )

    buttons = [
        InlineKeyboardButton(
            text=str(i),
            callback_data=f"approve_ah:{tg_id}:{date}:{h:.1f}:{N}:{i}",
        )
        for i in range(N + 1)
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    for admin_id in recipients:
        try:
            media = [InputMediaPhoto(media=fid) for fid in photo_ids]
            await message.bot.send_media_group(chat_id=admin_id, media=media)
            await message.bot.send_message(
                chat_id=admin_id, text=approval_text, parse_mode="HTML", reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True)
            )
            logger.info("_send_waiter_report: уведомлен %s", admin_id)
        except Exception as e:
            error_logger.error(
                "_send_waiter_report: не удалось уведомить %s: %s", admin_id, e
            )


# ---------------------------------------------------------------------------
# Официант — карты лояльности
# ---------------------------------------------------------------------------

async def _ask_about_loyalty_cards(message: Message, state: FSMContext) -> None:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📸 Да, есть фото", callback_data="has_loyalty_cards"),
        InlineKeyboardButton(text="❌ Нет", callback_data="no_loyalty_cards"),
    ]])
    await message.answer(
        "🎴 Оформлялись карты лояльности?\n\nМожно отменить ввод командой /cancel",
        reply_markup=keyboard,
    )
    await state.set_state(ShiftStates.waiting_loyalty_cards)


@userhours_router.callback_query(F.data == "has_loyalty_cards")
async def cb_has_loyalty_cards(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("🎴 Жду фото карт лояльности (можно несколько)\n\nДля отмены нажмите /cancel")
    await callback.answer()


@userhours_router.callback_query(F.data == "no_loyalty_cards")
async def cb_no_loyalty_cards(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("🎴 Карты лояльности: нет")
    await _ask_about_check_filling(callback.message, state)
    await callback.answer()


@userhours_router.message(ShiftStates.waiting_loyalty_cards, F.photo)
async def process_loyalty_photo(message: Message, state: FSMContext) -> None:
    photo_file_id = message.photo[-1].file_id
    mgid = message.media_group_id

    if mgid:
        lock = _mg_loyalty_locks.setdefault(mgid, asyncio.Lock())
        async with lock:
            if mgid not in _mg_loyalty_photos:
                _mg_loyalty_photos[mgid] = []
                _mg_loyalty_context[mgid] = {"message": message, "state": state}

            if _mg_loyalty_photos[mgid] is None:
                return

            _mg_loyalty_photos[mgid].append(photo_file_id)

            if mgid not in _mg_loyalty_scheduled:
                _mg_loyalty_scheduled.add(mgid)
                asyncio.create_task(_delayed_process_loyalty(mgid))
    else:
        await _send_loyalty_cards_report(message, state, [photo_file_id])
        await _ask_about_check_filling(message, state)


async def _cleanup_mg_buffers(
    mgid: str,
    photos: dict,
    context: dict,
    scheduled: set,
    locks: dict,
) -> None:
    lock = locks.get(mgid)
    if lock:
        async with lock:
            photos.pop(mgid, None)
            context.pop(mgid, None)
            scheduled.discard(mgid)
        locks.pop(mgid, None)
    else:
        photos.pop(mgid, None)
        context.pop(mgid, None)
        scheduled.discard(mgid)


async def _delayed_process_loyalty(mgid: str) -> None:
    try:
        await asyncio.sleep(1.0)

        ctx_for_error = _mg_loyalty_context.get(mgid)
        lock = _mg_loyalty_locks.setdefault(mgid, asyncio.Lock())
        async with lock:
            photo_ids = _mg_loyalty_photos.get(mgid)
            if not photo_ids:
                _mg_loyalty_photos.pop(mgid, None)
                _mg_loyalty_context.pop(mgid, None)
                _mg_loyalty_scheduled.discard(mgid)
                _mg_loyalty_locks.pop(mgid, None)
                return

            ctx = _mg_loyalty_context.pop(mgid)
            _mg_loyalty_photos.pop(mgid)
            _mg_loyalty_scheduled.discard(mgid)
            _mg_loyalty_locks.pop(mgid, None)

        message = ctx["message"]
        state = ctx["state"]

        if ctx.get("cancelled"):
            logger.info("_delayed_process_loyalty: mgid=%s отменён пользователем", mgid)
            await state.clear()
            return

        logger.info("_delayed_process_loyalty: mgid=%s, photos=%d", mgid, len(photo_ids))
        await _send_loyalty_cards_report(message, state, photo_ids)
        await _ask_about_check_filling(message, state)

    except Exception as e:
        error_logger.exception("_delayed_process_loyalty: ошибка mgid=%s: %s", mgid, e)
        ctx = ctx_for_error
        if ctx:
            try:
                await ctx["message"].answer("❌ Ошибка при обработке фото. Попробуйте ещё раз.")
                await ctx["state"].clear()
            except Exception:
                error_logger.exception("_delayed_process_loyalty: не удалось уведомить пользователя mgid=%s", mgid)
        await _cleanup_mg_buffers(
            mgid,
            _mg_loyalty_photos,
            _mg_loyalty_context,
            _mg_loyalty_scheduled,
            _mg_loyalty_locks,
        )


async def _send_loyalty_cards_report(
    message: Message,
    state: FSMContext,
    photo_ids: list[str],
) -> None:
    tg_id = message.from_user.id
    data = await state.get_data()
    shift_date = data.get("shift_date", "—")
    N = len(photo_ids)

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)
    mention = make_mention(message.from_user.username, full_name)

    callback_key = str(uuid.uuid4())[:8]
    _pending_loyalty[callback_key] = {
        "tg_id": tg_id,
        "shift_date": shift_date,
        "shift_hours": data.get("shift_hours", 0.0),
        "full_name": full_name,
        "photo_ids": photo_ids,
    }

    report_text = (
        f"🎴 Карты лояльности от {mention}\n"
        f"📅 {shift_date}\n"
        f"📸 Фото: {N} шт"
    )
    buttons = [
        InlineKeyboardButton(
            text=str(i),
            callback_data=f"approve_loyalty:{callback_key}:{i}",
        )
        for i in range(N + 1)
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    hall_admin_ids = await get_admins_by_department(DB_PATH, "Зал")
    for admin_id in hall_admin_ids:
        try:
            media = [InputMediaPhoto(media=fid) for fid in photo_ids]
            await message.bot.send_media_group(chat_id=admin_id, media=media)
            await message.bot.send_message(
                chat_id=admin_id, text=report_text, parse_mode="HTML",
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            logger.info("_send_loyalty_cards_report: уведомлен %s", admin_id)
        except Exception as e:
            error_logger.error("_send_loyalty_cards_report: не удалось уведомить %s: %s", admin_id, e)


# ---------------------------------------------------------------------------
# Официант — наполняемость чеков
# ---------------------------------------------------------------------------

async def _ask_about_check_filling(message: Message, state: FSMContext) -> None:
    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📸 Да, есть фото", callback_data="has_check_filling"),
        InlineKeyboardButton(text="❌ Нет", callback_data="no_check_filling"),
    ]])
    await message.answer(
        "💳 Были наполняемости чеков?\n\nМожно отменить ввод командой /cancel",
        reply_markup=keyboard,
    )
    await state.set_state(ShiftStates.waiting_check_filling)


@userhours_router.callback_query(F.data == "has_check_filling")
async def cb_has_check_filling(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("💳 Жду фото наполняемости чеков (можно несколько)\n\nДля отмены нажмите /cancel")
    await callback.answer()


@userhours_router.callback_query(F.data == "no_check_filling")
async def cb_no_check_filling(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_text("💳 Наполняемость чеков: нет")
    await state.clear()
    await callback.message.answer("✅ Смена записана!")
    await callback.answer()


@userhours_router.message(ShiftStates.waiting_check_filling, F.photo)
async def process_check_filling_photo(message: Message, state: FSMContext) -> None:
    photo_file_id = message.photo[-1].file_id
    mgid = message.media_group_id

    if mgid:
        lock = _mg_filling_locks.setdefault(mgid, asyncio.Lock())
        async with lock:
            if mgid not in _mg_filling_photos:
                _mg_filling_photos[mgid] = []
                _mg_filling_context[mgid] = {"message": message, "state": state}

            if _mg_filling_photos[mgid] is None:
                return

            _mg_filling_photos[mgid].append(photo_file_id)

            if mgid not in _mg_filling_scheduled:
                _mg_filling_scheduled.add(mgid)
                asyncio.create_task(_delayed_process_filling(mgid))
    else:
        await _send_check_filling_report(message, state, [photo_file_id])
        await state.clear()
        await message.answer("✅ Смена записана!")


async def _delayed_process_filling(mgid: str) -> None:
    try:
        await asyncio.sleep(1.0)

        ctx_for_error = _mg_filling_context.get(mgid)
        lock = _mg_filling_locks.setdefault(mgid, asyncio.Lock())
        async with lock:
            photo_ids = _mg_filling_photos.get(mgid)
            if not photo_ids:
                _mg_filling_photos.pop(mgid, None)
                _mg_filling_context.pop(mgid, None)
                _mg_filling_scheduled.discard(mgid)
                _mg_filling_locks.pop(mgid, None)
                return

            ctx = _mg_filling_context.pop(mgid)
            _mg_filling_photos.pop(mgid)
            _mg_filling_scheduled.discard(mgid)
            _mg_filling_locks.pop(mgid, None)

        message = ctx["message"]
        state = ctx["state"]

        if ctx.get("cancelled"):
            logger.info("_delayed_process_filling: mgid=%s отменён пользователем", mgid)
            await state.clear()
            return

        logger.info("_delayed_process_filling: mgid=%s, photos=%d", mgid, len(photo_ids))
        await _send_check_filling_report(message, state, photo_ids)
        await state.clear()
        await message.answer("✅ Смена записана!")

    except Exception as e:
        error_logger.exception("_delayed_process_filling: ошибка mgid=%s: %s", mgid, e)
        ctx = ctx_for_error
        if ctx:
            try:
                await ctx["message"].answer("❌ Ошибка при обработке фото. Попробуйте ещё раз.")
                await ctx["state"].clear()
            except Exception:
                error_logger.exception("_delayed_process_filling: не удалось уведомить пользователя mgid=%s", mgid)
        await _cleanup_mg_buffers(
            mgid,
            _mg_filling_photos,
            _mg_filling_context,
            _mg_filling_scheduled,
            _mg_filling_locks,
        )


async def _send_check_filling_report(
    message: Message,
    state: FSMContext,
    photo_ids: list[str],
) -> None:
    tg_id = message.from_user.id
    data = await state.get_data()
    shift_date = data.get("shift_date", "—")
    N = len(photo_ids)

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)
    mention = make_mention(message.from_user.username, full_name)

    callback_key = str(uuid.uuid4())[:8]
    _pending_filling[callback_key] = {
        "tg_id": tg_id,
        "shift_date": shift_date,
        "shift_hours": data.get("shift_hours", 0.0),
        "full_name": full_name,
        "photo_ids": photo_ids,
    }

    report_text = (
        f"💳 Наполняемость чеков от {mention}\n"
        f"📅 {shift_date}\n"
        f"📸 Фото: {N} шт"
    )
    buttons = [
        InlineKeyboardButton(
            text=str(i),
            callback_data=f"approve_filling:{callback_key}:{i}",
        )
        for i in range(N + 1)
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])

    hall_admin_ids = await get_admins_by_department(DB_PATH, "Зал")
    for admin_id in hall_admin_ids:
        try:
            media = [InputMediaPhoto(media=fid) for fid in photo_ids]
            await message.bot.send_media_group(chat_id=admin_id, media=media)
            await message.bot.send_message(
                chat_id=admin_id, text=report_text, parse_mode="HTML",
                reply_markup=keyboard,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
            logger.info("_send_check_filling_report: уведомлен %s", admin_id)
        except Exception as e:
            error_logger.error("_send_check_filling_report: не удалось уведомить %s: %s", admin_id, e)


# ---------------------------------------------------------------------------
# Бармен / Барбэк — шаг 2: парсинг основной смены
# ---------------------------------------------------------------------------

async def _process_bar_shift_input(message: Message, state: FSMContext, position: str) -> None:
    result = parse_shift(message.text or "", position)

    if result is None:
        await message.answer(
            "❌ Не удалось распознать формат. Попробуйте ещё раз:\n\n"
            "<code>13.03 10:00-20:00</code>"
        )
        return

    await state.update_data(**result)

    h = result["h"]
    end = result["end"]
    date = _date_str(result["day"], result["month"], result["year"])

    start_hour = int(end) % 24
    start_min = 30 if (end % 1) >= 0.5 else 0
    start_str = f"{start_hour:02d}:{start_min:02d}"

    total_half = int(end * 2) + 8
    end_hour = (total_half // 2) % 24
    end_min = 30 if total_half % 2 else 0
    end_str = f"{end_hour:02d}:{end_min:02d}"

    await message.answer(
        f"⏱ Смена {date}: Часы смены = {_fmt_h(h)} ч\n\n"
        f"Были тусовочные часы?\n"
        f"Введите диапазон или 0:\n\n"
        f"<code>{start_str}-{end_str}</code>"
    )
    await state.set_state(ShiftStates.waiting_ah_input)


# ---------------------------------------------------------------------------
# Бармен / Барбэк — шаг 3: парсинг тусовочных часов + проверка нахлёста
# ---------------------------------------------------------------------------

async def _process_bar_ah_input(message: Message, state: FSMContext, position: str) -> None:
    import re as _re

    text = (message.text or "").strip()
    data = await state.get_data()
    shift_start: float = data["start"]
    shift_end: float = data["end"]

    if text == "0":
        await state.update_data(ah=0.0)
        await _write_and_finish_bar(message, state, position)
        return

    # Нормализуем разделитель (en/em dash и пробелы вокруг тире)
    normalized = _re.sub(r'\s*[–—\-]\s*', '-', text)
    time_result = parse_time(normalized)

    if time_result is None:
        await message.answer(
            "❌ Не удалось распознать формат. "
            "Введите диапазон (например <code>22:00-02:00</code>) или 0:"
        )
        return

    ah_start, ah_end = time_result

    if check_overlap(shift_start, shift_end, ah_start, ah_end):
        s_str = f"{_fmt_time(shift_start)}–{_fmt_time(shift_end)}"
        await message.answer(
            f"❌ Тусовочные часы пересекаются с основной сменой ({s_str}).\n"
            f"Исправьте диапазон:"
        )
        return

    if ah_start > ah_end:
        raw_ah = 24 - ah_start + ah_end
    else:
        raw_ah = ah_end - ah_start

    ah = round_to_half(raw_ah)

    await state.update_data(ah=ah, ah_start=ah_start, ah_end=ah_end)
    await _write_and_finish_bar(message, state, position)


# ---------------------------------------------------------------------------
# Запись + уведомления для Бармена / Барбэка
# ---------------------------------------------------------------------------

async def _write_and_finish_bar(message: Message, state: FSMContext, position: str) -> None:
    tg_id = message.from_user.id
    data = await state.get_data()

    day   = data["day"]
    month = data["month"]
    year  = data["year"]
    h     = data["h"]
    ah    = data.get("ah", 0.0)
    start = data.get("start", 0.0)
    end   = data.get("end", 0.0)

    date = _date_str(day, month, year)

    if sheets_client is None:
        await message.answer("❌ Ошибка записи. Попробуйте позже.")
        await state.clear()
        return

    try:
        sheets_client.write_shift(tg_id, day, month, year, h, ah)
    except ValueError as e:
        if "не найден в листе" in str(e):
            await state.clear()
            await message.answer(
                "❌ Вы не числитесь в графике за указанный месяц.\n\n"
                "Смены можно вносить только за текущий месяц.\n"
                "Если вы уверены, что ошибки нет — обратитесь к администратору или разработчику."
            )
            logger.warning("write_shift: user %s not found in sheet: %s", tg_id, e)
            return
        raise
    except Exception:
        error_logger.exception("_write_and_finish_bar: ошибка записи смены для %s", tg_id)
        await message.answer("❌ Ошибка записи. Попробуйте позже.")
        await state.clear()
        return

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)

    logger.info(
        "Смена записана: user=%s, date=%s, H=%s, AH=%s, position=%s",
        tg_id, date, _fmt_h(h), _fmt_h(ah), position,
    )

    # Ответ пользователю
    if ah > 0:
        await message.answer(
            f"✅ Смена {date} записана\n"
            f"Часы смены = {_fmt_h(h)} ч | Тусовочные = {_fmt_h(ah)} ч"
        )
    else:
        await message.answer(f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(h)} ч")

    # Уведомление администраторам бара
    mention = make_mention(message.from_user.username, full_name)
    time_range = f"{_fmt_time(start)}–{_fmt_time(end)}"
    if ah > 0:
        admin_text = (
            f"📋 {position} внёс смену\n\n"
            f"👤 {mention}\n"
            f"📅 {date}\n"
            f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч\n"
            f"🎉 Тусовочные = {_fmt_h(ah)} ч"
        )
    else:
        admin_text = (
            f"📋 {position} внёс смену\n\n"
            f"👤 {mention}\n"
            f"📅 {date}\n"
            f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч"
        )

    bar_admin_ids = await get_admins_by_department(DB_PATH, "Бар")
    recipients = bar_admin_ids
    for admin_id in recipients:
        try:
            await message.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
            logger.info("Notified admin %s", admin_id)
        except Exception as e:
            error_logger.error("Не удалось уведомить admin %s: %s", admin_id, e)

    await state.clear()


# ---------------------------------------------------------------------------
# Запись смен для позиций с механикой «только H»
# ---------------------------------------------------------------------------

async def _process_simple_h_shifts(message: Message, state: FSMContext, position: str) -> None:
    tg_id = message.from_user.id
    lines = [line.strip() for line in (message.text or "").splitlines() if line.strip()]

    if not lines:
        await message.answer("❌ Сообщение пустое. Введите смену(ы).")
        return

    # Парсим все строки заранее — при ошибке не пишем ничего
    parsed: list[tuple[str, dict]] = []
    for line in lines:
        result = parse_shift(line, position)
        if result is None:
            await message.answer(
                f"❌ Не удалось распознать строку: '{line}'\n\n"
                f"Проверьте формат:\n<code>13.03 10:00-20:00</code>"
            )
            return
        parsed.append((line, result))

    if sheets_client is None:
        await message.answer("❌ Ошибка подключения к таблице. Попробуйте позже.")
        await state.clear()
        return

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)
    mention = make_mention(message.from_user.username, full_name)

    if position in KITCHEN_POSITIONS:
        kitchen_admin_ids = await get_admins_by_department(DB_PATH, "Кухня")
        recipients = kitchen_admin_ids
    else:
        dept = "МОП" if position in MOP_POSITIONS else "Зал"
        hall_admin_ids = await get_admins_by_department(DB_PATH, dept)
        recipients = hall_admin_ids

    written: list[tuple[str, float]] = []

    for _line, result in parsed:
        day, month, year = result["day"], result["month"], result["year"]
        h = result["h"]
        start, end = result["start"], result["end"]
        date = _date_str(day, month, year)

        try:
            sheets_client.write_shift(tg_id, day, month, year, h, 0.0)
        except Exception:
            error_logger.exception(
                "_process_simple_h_shifts: ошибка записи %s для %s", date, tg_id
            )
            await message.answer(f"❌ Ошибка записи {date}. Попробуйте позже.")
            await state.clear()
            return

        logger.info(
            "Смена записана: user=%s, date=%s, H=%s, position=%s",
            tg_id, date, _fmt_h(h), position,
        )
        written.append((date, h))

        time_range = f"{_fmt_time(start)}–{_fmt_time(end)}"
        admin_text = (
            f"📋 {position} внёс смену\n\n"
            f"👤 {mention}\n"
            f"📅 {date}\n"
            f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч"
        )
        for admin_id in recipients:
            try:
                await message.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
                logger.info("Notified admin %s", admin_id)
            except Exception as e:
                error_logger.error("Не удалось уведомить admin %s: %s", admin_id, e)

    if len(written) == 1:
        date, h = written[0]
        await message.answer(f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(h)} ч")
    else:
        lines_out = "\n".join(f"{d}: {_fmt_h(h)} ч" for d, h in written)
        await message.answer(f"✅ Записано смен: {len(written)}\n{lines_out}")

    await state.clear()


# ---------------------------------------------------------------------------
# Запись в таблицу + уведомления (Раннер)
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
        sheets_client.write_shift(tg_id, day, month, year, h, ah, is_weekend=is_weekend)
    except ValueError as e:
        if "не найден в листе" in str(e):
            await state.clear()
            await message.answer(
                "❌ Вы не числитесь в графике за указанный месяц.\n\n"
                "Смены можно вносить только за текущий месяц.\n"
                "Если вы уверены, что ошибки нет — обратитесь к администратору или разработчику."
            )
            logger.warning("write_shift: user %s not found in sheet: %s", tg_id, e)
            return
        raise
    except Exception:
        error_logger.exception("_write_and_finish: ошибка записи смены для %s", tg_id)
        await message.answer("❌ Ошибка записи. Попробуйте позже.")
        await state.clear()
        return

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)

    logger.info(
        "Смена записана: user=%s, date=%s, H=%s, AH=%s",
        tg_id, date, h, ah,
    )

    # Ответ пользователю
    if ah > 0:
        await message.answer(
            f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(h)} ч | Доп. часы = {_fmt_h(ah)} ч"
        )
    else:
        await message.answer(f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(h)} ч")

    # Уведомление admin_hall
    mention = make_mention(message.from_user.username, full_name)
    weekend_mark = " 🌟 (выходной)" if is_weekend else ""
    time_range = f"{_fmt_time(start)}–{_fmt_time(end)}"

    if ah > 0:
        admin_text = (
            f"📋 Раннер внёс смену\n\n"
            f"👤 {mention}\n"
            f"📅 {date}\n"
            f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч{weekend_mark}\n"
            f"🔢 Доп. часы = {_fmt_h(ah)} ч\n"
            f"💬 {html.escape(comment)}"
        )
    else:
        admin_text = (
            f"📋 Раннер внёс смену\n\n"
            f"👤 {mention}\n"
            f"📅 {date}\n"
            f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч{weekend_mark}"
        )

    hall_admin_ids = await get_admins_by_department(DB_PATH, "Зал")
    recipients = hall_admin_ids
    for admin_id in recipients:
        try:
            await message.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
            logger.info("Notified admin %s", admin_id)
        except Exception as e:
            error_logger.error("Не удалось уведомить admin %s: %s", admin_id, e)

    await state.clear()
