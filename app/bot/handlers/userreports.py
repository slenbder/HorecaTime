import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.db.models import get_user, get_rate, get_rate_for_period
from app.services.google_sheets import GoogleSheetsClient, MONTH_NAMES_RU
from config import DB_PATH

reports_router = Router()
logger = logging.getLogger(__name__)

try:
    sheets_client = GoogleSheetsClient()
    logger.info("userreports: GoogleSheetsClient успешно инициализирован")
except Exception:
    logger.exception("userreports: Ошибка при инициализации GoogleSheetsClient")
    sheets_client = None

_ALLOWED_ROLES = {"user", "admin_hall", "admin_bar", "admin_kitchen", "superadmin", "developer"}

# Позиции, у которых AH = тусовочные часы с повышенной ставкой
_BAR_POSITIONS = {"Бармен", "Барбэк"}


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

    if position in _BAR_POSITIONS:
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

    if position in _BAR_POSITIONS:
        earnings_second = h2 * base + ah2 * (extra or base)
        earnings_total = h_tot * base + ah_tot * (extra or base)
    else:
        earnings_second = h2 * base
        earnings_total = h_tot * base

    lines.append(f"💰 Заработок: {_fmt_money(earnings_second)} р")
    lines.append("")
    lines.append(f"Всего за месяц: {_fmt(h_tot)} ч")
    if ah_tot > 0 and position not in _BAR_POSITIONS:
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
    if not position:
        logger.warning("hours_first: у пользователя %s не установлена позиция", tg_id)
    rate = await get_rate(DB_PATH, position) if position else None

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
    if not position:
        logger.warning("hours_second: у пользователя %s не установлена позиция", tg_id)
    rate = await get_rate(DB_PATH, position) if position else None

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
    if not position:
        logger.warning("hours_last: у пользователя %s не установлена позиция", tg_id)
    now = datetime.now(ZoneInfo("Europe/Moscow"))
    prev_month = now.month - 1 if now.month > 1 else 12
    prev_year = now.year if now.month > 1 else now.year - 1
    rate = await get_rate_for_period(DB_PATH, position, prev_month, prev_year) if position else None

    lines = _build_hours_second_lines(data, position, rate, sheet_label=sheet_name)
    await message.answer("\n".join(lines))
