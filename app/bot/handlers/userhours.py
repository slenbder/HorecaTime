import asyncio
import html
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
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
from config import ADMIN_BAR_IDS, ADMIN_HALL_IDS, ADMIN_KITCHEN_IDS, SUPERADMIN_IDS

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

    try:
        user_info = sheets_client.get_user_from_techlist(tg_id)
    except Exception:
        error_logger.exception("cmd_shift: ошибка получения данных пользователя %s из техлиста", tg_id)
        await message.answer("❌ Ошибка получения данных. Попробуйте позже.")
        return

    position = user_info.get("position", "") if user_info else ""

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
            "📎 Прикрепите фото чеков/карт (если есть)"
        )
        await state.set_state(ShiftStates.waiting_shift_input)
    else:
        await message.answer("❌ Команда /shift пока недоступна для вашей позиции.")
        await state.clear()


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
        await _process_waiter_shift_input(message, state)
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
        "Смена записана: user=%s (%s), date=%s, H=%s, position=Официант (без фото)",
        tg_id, full_name, date, _fmt_h(h),
    )

    await state.clear()
    await message.answer(f"✅ Смена {date} записана\nЧасы смены = {_fmt_h(h)} ч")

    recipients = list(set(ADMIN_HALL_IDS + SUPERADMIN_IDS))
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
                return

            ctx = _mg_context.pop(mgid)
            _mg_photos.pop(mgid)
            _mg_scheduled.discard(mgid)
            _mg_locks.pop(mgid, None)

        message = ctx["message"]
        state = ctx["state"]
        caption = (ctx["caption"] or "").strip()

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

    recipients = list(set(ADMIN_HALL_IDS + SUPERADMIN_IDS))
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
    except Exception:
        error_logger.exception("_write_and_finish_bar: ошибка записи смены для %s", tg_id)
        await message.answer("❌ Ошибка записи. Попробуйте позже.")
        await state.clear()
        return

    user_data = get_user(tg_id)
    full_name = user_data["full_name"] if user_data else str(tg_id)

    logger.info(
        "Смена записана: user=%s (%s), date=%s, H=%s, AH=%s, position=%s",
        tg_id, full_name, date, _fmt_h(h), _fmt_h(ah), position,
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

    recipients = list(set(ADMIN_BAR_IDS + SUPERADMIN_IDS))
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
        recipients = list(set(ADMIN_KITCHEN_IDS + SUPERADMIN_IDS))
    else:
        recipients = list(set(ADMIN_HALL_IDS + SUPERADMIN_IDS))

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
            "Смена записана: user=%s (%s), date=%s, H=%s, position=%s",
            tg_id, full_name, date, _fmt_h(h), position,
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

    recipients = list(set(ADMIN_HALL_IDS + SUPERADMIN_IDS))
    for admin_id in recipients:
        try:
            await message.bot.send_message(chat_id=admin_id, text=admin_text, parse_mode="HTML", link_preview_options=LinkPreviewOptions(is_disabled=True))
            logger.info("Notified admin %s", admin_id)
        except Exception as e:
            error_logger.error("Не удалось уведомить admin %s: %s", admin_id, e)

    await state.clear()
