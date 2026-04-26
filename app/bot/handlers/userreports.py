import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile

from app.db.models import get_user, get_user_rate, get_user_rate_history
from app.services.google_sheets import GoogleSheetsClient, MONTH_NAMES_RU
from app.services.pdfservice import PDFService
from config import DB_PATH, GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID, SUPERADMIN_IDS, DEVELOPER_ID, SHEET_URL, POSITIONS_WITH_EXTRA

reports_router = Router()
logger = logging.getLogger(__name__)
error_logger = logging.getLogger("errors")

try:
    sheets_client = GoogleSheetsClient()
    logger.info("userreports: GoogleSheetsClient успешно инициализирован")
except Exception:
    logger.exception("userreports: Ошибка при инициализации GoogleSheetsClient")
    sheets_client = None

try:
    pdf_service = PDFService(GOOGLE_CREDENTIALS_PATH, SPREADSHEET_ID)
    logger.info("userreports: PDFService успешно инициализирован")
except Exception:
    logger.exception("userreports: Ошибка при инициализации PDFService")
    pdf_service = None

_ALLOWED_ROLES = {"user", "admin_hall", "admin_bar", "admin_kitchen", "superadmin", "developer"}

# Позиции, у которых AH = тусовочные часы с повышенной ставкой
_BAR_POSITIONS = POSITIONS_WITH_EXTRA - {"Раннер"}


def _get_current_sheet_name() -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    return f"{MONTH_NAMES_RU[now.month]} {now.year}"


def _get_last_month_sheet_name() -> str:
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    month = now.month - 1 if now.month > 1 else 12
    year = now.year if now.month > 1 else now.year - 1
    return f"{MONTH_NAMES_RU[month]} {year}"


def _fmt(v: float) -> str:
    return str(int(v)) if v == int(v) else str(v)


def _fmt_money(v: float) -> str:
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def _build_runner_earnings_lines(
    h: float,
    ah: float,
    h_weekend: float,
    base: float,
    extra: float,
) -> list[str]:
    """Строки заработка для Раннера с разбивкой обычные/выходные."""
    h_regular = h - h_weekend
    earnings_regular = h_regular * base
    earnings_weekend = h_weekend * (extra or base)
    earnings_ah = ah * base
    total = earnings_regular + earnings_weekend + earnings_ah
    lines = []
    if h_weekend > 0:
        lines.append(
            f"• {_fmt(h_regular)} ч × {_fmt_money(base)} р = {_fmt_money(earnings_regular)} р (обычные дни)"
        )
        lines.append(
            f"• {_fmt(h_weekend)} ч × {_fmt_money(extra or base)} р = {_fmt_money(earnings_weekend)} р (выходные дни)"
        )
        if ah > 0:
            lines.append(
                f"• {_fmt(ah)} ч × {_fmt_money(base)} р = {_fmt_money(earnings_ah)} р (доп. часы)"
            )
        lines.append(f"💰 Итого: {_fmt_money(total)} р")
    else:
        lines.append(f"💰 Заработок: {_fmt_money(total)} р")
    return lines


def _build_hours_first_lines(data: dict, position: str | None, rate: dict | None) -> list[str]:
    h = data["h_first"]
    ah = data["ah_first"]
    lines = [
        "📊 Первая половина месяца (1–15)",
        f"Отработано: {_fmt(h)} ч",
    ]
    if position in _BAR_POSITIONS and ah > 0:
        lines.append(f"Доп. часы: {_fmt(ah)} ч")

    if rate is None:
        if ah > 0 and position not in _BAR_POSITIONS:
            lines.append(f"Доп. часы: {_fmt(ah)} ч")
        lines.append("(ставка не установлена — обратитесь к администратору)")
        return lines

    base = rate["base_rate"]
    extra = rate["extra_rate"]

    if position == "Раннер":
        h_weekend = data.get("h_weekend_first", 0.0)
        lines += _build_runner_earnings_lines(h, ah, h_weekend, base, extra or base)
    elif position in _BAR_POSITIONS:
        earnings_h = h * base
        earnings_ah = ah * (extra or base)
        total = earnings_h + earnings_ah
        lines.append(f"• {_fmt(h)} ч × {_fmt_money(base)} р = {_fmt_money(earnings_h)} р")
        if ah > 0:
            lines.append(f"• Доп. часы: {_fmt(ah)} ч × {_fmt_money(extra or base)} р = {_fmt_money(earnings_ah)} р")
        lines.append(f"💰 Итого: {_fmt_money(total)} р")
    else:
        if ah > 0:
            lines.append(f"Доп. часы: {_fmt(ah)} ч")
        earnings = h * base
        lines.append(f"💰 Заработок: {_fmt_money(earnings)} р")

    return lines


def _build_hours_second_lines(data: dict, position: str | None, rate: dict | None,
                               sheet_label: str = "Вторая половина месяца (16–конец)") -> list[str]:
    h2 = data["h_second"]
    ah2 = data["ah_second"]
    h_tot = data["h_total"]
    ah_tot = data["ah_total"]

    lines = [
        f"📊 {sheet_label}",
        f"Отработано: {_fmt(h2)} ч",
    ]
    if ah2 > 0:
        lines.append(f"Доп. часы: {_fmt(ah2)} ч")

    if rate is None:
        lines.append("(ставка не установлена — обратитесь к администратору)")
        lines.append("")
        lines.append(f"Всего за месяц: {_fmt(h_tot)} ч")
        if ah_tot > 0 and position not in _BAR_POSITIONS:
            lines.append(f"Доп. часы за месяц: {_fmt(ah_tot)} ч")
        return lines

    base = rate["base_rate"]
    extra = rate["extra_rate"]

    if position == "Раннер":
        h_weekend_second = data.get("h_weekend_second", 0.0)
        h_weekend_total = data.get("h_weekend_total", 0.0)
        lines += _build_runner_earnings_lines(h2, ah2, h_weekend_second, base, extra or base)
        lines.append("")
        lines.append(f"Всего за месяц: {_fmt(h_tot)} ч")
        if ah_tot > 0:
            lines.append(f"Доп. часы за месяц: {_fmt(ah_tot)} ч")
        lines += _build_runner_earnings_lines(h_tot, ah_tot, h_weekend_total, base, extra or base)
    elif position in _BAR_POSITIONS:
        earnings_second = h2 * base + ah2 * (extra or base)
        earnings_total = h_tot * base + ah_tot * (extra or base)
        lines.append(f"💰 Заработок: {_fmt_money(earnings_second)} р")
        lines.append("")
        lines.append(f"Всего за месяц: {_fmt(h_tot)} ч")
        lines.append(f"💰 Заработок за месяц: {_fmt_money(earnings_total)} р")
    else:
        earnings_second = h2 * base
        earnings_total = h_tot * base
        lines.append(f"💰 Заработок: {_fmt_money(earnings_second)} р")
        lines.append("")
        lines.append(f"Всего за месяц: {_fmt(h_tot)} ч")
        if ah_tot > 0:
            lines.append(f"Доп. часы за месяц: {_fmt(ah_tot)} ч")
        lines.append(f"💰 Заработок за месяц: {_fmt_money(earnings_total)} р")

    return lines


@reports_router.message(Command("hours_first"))
async def cmd_hours_first(message: Message):
    tg_id = message.from_user.id
    user_data = get_user(tg_id)
    if not user_data or user_data.get("role") not in _ALLOWED_ROLES:
        return

    logger.info("hours_first: запрос от %s", tg_id)

    if sheets_client is None:
        await message.answer("📊 Ошибка подключения к таблице.")
        return

    data = sheets_client.get_summary_hours(tg_id, _get_current_sheet_name())
    if data is None:
        await message.answer("📊 Данные не найдены.")
        return

    position = user_data.get("position") or None
    rate = await get_user_rate(DB_PATH, tg_id)
    if rate is None:
        await message.answer(
            "⚠️ Ваша ставка ещё не установлена.\n"
            "Обратитесь к администратору вашего отдела для установки ставки."
        )
        return

    lines = _build_hours_first_lines(data, position, rate)
    await message.answer("\n".join(lines))


@reports_router.message(Command("hours_second"))
async def cmd_hours_second(message: Message):
    tg_id = message.from_user.id
    user_data = get_user(tg_id)
    if not user_data or user_data.get("role") not in _ALLOWED_ROLES:
        return

    logger.info("hours_second: запрос от %s", tg_id)

    if sheets_client is None:
        await message.answer("📊 Ошибка подключения к таблице.")
        return

    data = sheets_client.get_summary_hours(tg_id, _get_current_sheet_name())
    if data is None:
        await message.answer("📊 Данные не найдены.")
        return

    position = user_data.get("position") or None
    rate = await get_user_rate(DB_PATH, tg_id)
    if rate is None:
        await message.answer(
            "⚠️ Ваша ставка ещё не установлена.\n"
            "Обратитесь к администратору вашего отдела для установки ставки."
        )
        return

    lines = _build_hours_second_lines(data, position, rate)
    await message.answer("\n".join(lines))


@reports_router.message(Command("hours_last"))
async def cmd_hours_last(message: Message):
    tg_id = message.from_user.id
    user_data = get_user(tg_id)
    if not user_data or user_data.get("role") not in _ALLOWED_ROLES:
        return

    sheet_name = _get_last_month_sheet_name()
    logger.info("hours_last: запрос от %s, лист='%s'", tg_id, sheet_name)

    if sheets_client is None:
        await message.answer("📊 Ошибка подключения к таблице.")
        return

    data = sheets_client.get_summary_hours(tg_id, sheet_name)
    if data is None:
        await message.answer("📊 Данные за прошлый месяц недоступны.")
        return

    position = user_data.get("position") or None
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    prev_month = now.month - 1 if now.month > 1 else 12
    prev_year = now.year if now.month > 1 else now.year - 1

    rate = await get_user_rate_history(DB_PATH, tg_id, prev_month, prev_year)
    if rate is None:
        rate = await get_user_rate(DB_PATH, tg_id)

    if rate is None:
        logger.warning(
            "cmd_hours_last: у пользователя %d нет ставки за %d/%d и текущей ставки",
            tg_id, prev_month, prev_year,
        )
        await message.answer(
            "⚠️ Ваша ставка ещё не установлена.\n"
            "Обратитесь к администратору вашего отдела для установки ставки."
        )
        return

    lines = _build_hours_second_lines(data, position, rate, sheet_label=sheet_name)
    await message.answer("\n".join(lines))


_DEPT_HEADER = {
    "Зал": "ЗАЛ",
    "Бар": "БАР",
    "Кухня": "КУХНЯ",
}

_SUPERADMIN_ROLES = {"superadmin", "developer"}


@reports_router.message(Command("schedule"))
async def cmd_schedule(message: Message):
    tg_id = message.from_user.id
    logger.info("schedule: получена команда от %s", tg_id)

    # superadmin и developer не регистрируются в SQLite — определяем по config
    is_superadmin = tg_id in SUPERADMIN_IDS or tg_id == DEVELOPER_ID
    if is_superadmin:
        role = "developer" if tg_id == DEVELOPER_ID else "superadmin"
    else:
        user_data = get_user(tg_id)
        if not user_data or user_data.get("role") not in _ALLOWED_ROLES:
            return
        role = user_data.get("role")

    logger.info("schedule: запрос от %s (роль=%s)", tg_id, role)

    if sheets_client is None or pdf_service is None:
        await message.answer("❌ Не удалось сгенерировать график. Попробуйте позже.")
        return

    wait_msg = await message.answer("⏳ Генерирую график, подождите...")

    sheet_name = _get_current_sheet_name()
    try:
        sheet_id = sheets_client.get_sheet_id_by_name(sheet_name)
        if sheet_id is None:
            logger.warning("schedule: лист '%s' не найден", sheet_name)
            await wait_msg.delete()
            await message.answer("❌ Не удалось сгенерировать график. Попробуйте позже.")
            return

        if role in _SUPERADMIN_ROLES:
            range_a1 = None  # весь лист
        else:
            department = user_data.get("department")
            dept_header = _DEPT_HEADER.get(department) if department else None
            if dept_header:
                range_a1 = sheets_client.get_section_range(sheet_name, dept_header)
            else:
                range_a1 = None

        pdf_bytes = await pdf_service.get_pdf_bytes(sheet_id, range_a1)
        logger.info(
            "schedule: PDF сгенерирован для %s, лист='%s', range=%s, размер=%d байт",
            tg_id, sheet_name, range_a1, len(pdf_bytes),
        )

        await message.answer_document(
            BufferedInputFile(pdf_bytes, filename=f"График_{sheet_name}.pdf"),
            caption=f"📊 {sheet_name}",
        )
        await wait_msg.delete()

    except Exception as e:
        logger.error("schedule: ошибка генерации PDF для %s: %s", tg_id, e, exc_info=True)
        error_logger.exception("schedule: ошибка генерации PDF для %s: %s", tg_id, e)
        await wait_msg.delete()
        await message.answer("❌ Не удалось сгенерировать график. Попробуйте позже.")


@reports_router.message(Command("sheet"))
async def cmd_sheet(message: Message):
    tg_id = message.from_user.id
    if not SHEET_URL:
        await message.answer("❌ Ссылка на таблицу не настроена.")
        return
    await message.answer(
        f"📊 Ссылка на график:\n{SHEET_URL}"
    )
    logger.info("sheet: ссылка отправлена пользователю %s", tg_id)
