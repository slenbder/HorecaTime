import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from app.db.models import get_user
from app.services.google_sheets import GoogleSheetsClient, MONTH_NAMES_RU

reports_router = Router()
logger = logging.getLogger(__name__)

try:
    sheets_client = GoogleSheetsClient()
    logger.info("userreports: GoogleSheetsClient успешно инициализирован")
except Exception:
    logger.exception("userreports: Ошибка при инициализации GoogleSheetsClient")
    sheets_client = None

_ALLOWED_ROLES = {"user", "admin_hall", "admin_bar", "admin_kitchen", "superadmin", "developer"}

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

    lines = [
        "📊 Первая половина месяца (1–15)",
        f"Отработано: {_fmt(data['h_first'])} ч",
    ]
    if data["ah_first"] > 0:
        lines.append(f"Доп. часы: {_fmt(data['ah_first'])} ч")

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

    lines = [
        "📊 Вторая половина месяца (16–конец)",
        f"Отработано: {_fmt(data['h_second'])} ч",
    ]
    if data["ah_second"] > 0:
        lines.append(f"Доп. часы: {_fmt(data['ah_second'])} ч")
    lines.append(f"Всего за месяц: {_fmt(data['h_total'])} ч")
    if data["ah_total"] > 0:
        lines.append(f"Доп. часы за месяц: {_fmt(data['ah_total'])} ч")

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
        # Различаем: лист не существует vs пользователь не найден
        await message.answer("📊 Данные за прошлый месяц недоступны.")
        return

    lines = [
        f"📊 {sheet_name}",
        f"Отработано: {_fmt(data['h_total'])} ч",
    ]
    if data["ah_total"] > 0:
        lines.append(f"Доп. часы: {_fmt(data['ah_total'])} ч")

    await message.answer("\n".join(lines))
