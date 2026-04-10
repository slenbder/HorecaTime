import time
import logging
import traceback
from pathlib import Path
from collections import deque
from datetime import datetime
from typing import Dict, Set

from aiogram.types import BufferedInputFile, ErrorEvent

from config import DEVELOPER_ID


# Handlers где любая ошибка = CRITICAL
CRITICAL_HANDLERS: Set[str] = {
    'process_approve',
    'dismiss_user',
    'write_shift',
    'ensure_user_in_current_month_hours',
    'snapshot_user_rates_history',
    'switch_month',
    '_copy_month_sheet',
    '_transfer_active_users',
    'process_set_rate',
    'process_promote_confirm',
}

# Handlers без throttle (алертим мгновенно)
IMMEDIATE_ALERTS: Set[str] = {
    'switch_month',
    'snapshot_user_rates_history',
    'dismiss_user',
}

# Handlers с коротким throttle (2 минуты)
SHORT_THROTTLE: Set[str] = {
    'process_approve',
    'write_shift',
}

# Типы критичных исключений (независимо от handler)
CRITICAL_EXCEPTION_TYPES: Set[str] = {
    'HttpAccessTokenRefreshError',  # oauth2client auth failed
    'SpreadsheetNotFound',          # gspread
    'IntegrityError',               # sqlite3/aiosqlite
}

# Глобальный state для rate limiting
_last_error_alerts: Dict[str, float] = {}


def extract_handler_name(event: ErrorEvent) -> str:
    """
    Извлекает имя handler из traceback.
    Ищет последнюю функцию из app/bot/handlers/* или app/scheduler/*
    """
    tb = traceback.extract_tb(event.exception.__traceback__)

    for frame in reversed(tb):
        if 'app/bot/handlers/' in frame.filename or 'app/scheduler/' in frame.filename:
            return frame.name

    return 'unknown_handler'


def is_critical_exception(exception: Exception) -> bool:
    """Проверяет тип исключения на критичность."""
    exc_type = type(exception).__name__
    exc_str = str(exception)

    if exc_type in CRITICAL_EXCEPTION_TYPES:
        return True

    # 403 Forbidden в APIError gspread
    if exc_type == 'APIError' and '403' in exc_str:
        return True

    return False


def get_throttle_duration(handler_name: str) -> int:
    """
    Возвращает throttle в секундах.

    0   = без throttle (IMMEDIATE_ALERTS)
    120 = 2 мин (SHORT_THROTTLE)
    600 = 10 мин (остальные)
    """
    if handler_name in IMMEDIATE_ALERTS:
        return 0
    elif handler_name in SHORT_THROTTLE:
        return 120
    else:
        return 600


def should_send_alert(handler_name: str, exception: Exception) -> bool:
    """Rate limiting: проверяет, можно ли слать алерт прямо сейчас."""
    throttle_key = f"{handler_name}:{type(exception).__name__}"
    now = time.time()

    duration = get_throttle_duration(handler_name)
    if duration == 0:
        return True  # IMMEDIATE — всегда шлём

    last_sent = _last_error_alerts.get(throttle_key, 0)
    if now - last_sent < duration:
        return False

    _last_error_alerts[throttle_key] = now
    return True


def read_log_tail(filepath: str, lines: int = 50) -> str:
    """Читает последние N строк из файла лога."""
    try:
        path = Path(filepath)
        if not path.exists():
            return f"Лог-файл не найден: {filepath}"

        with open(path, 'r', encoding='utf-8') as f:
            return ''.join(deque(f, maxlen=lines))
    except Exception as e:
        return f"Ошибка чтения лога: {e}"


def format_traceback(exception: Exception, lines: int = 10) -> str:
    """Форматирует последние N строк traceback исключения."""
    tb_lines = traceback.format_exception(
        type(exception),
        exception,
        exception.__traceback__,
    )

    tail = tb_lines[-lines:] if len(tb_lines) > lines else tb_lines
    return ''.join(tail)


def extract_context(event: ErrorEvent) -> Dict[str, object]:
    """Извлекает контекст из ErrorEvent для включения в алерт."""
    update = event.update
    context: Dict[str, object] = {
        'user_id': None,
        'username': None,
        'handler': extract_handler_name(event),
        'file': 'unknown',
        'update_type': type(update).__name__ if update else 'unknown',
        'message_text': None,
    }

    if update:
        if hasattr(update, 'message') and update.message:
            user = update.message.from_user
            context['user_id'] = user.id
            context['username'] = f"@{user.username}" if user.username else 'N/A'
            context['message_text'] = update.message.text or update.message.caption or 'N/A'
        elif hasattr(update, 'callback_query') and update.callback_query:
            user = update.callback_query.from_user
            context['user_id'] = user.id
            context['username'] = f"@{user.username}" if user.username else 'N/A'

    tb = traceback.extract_tb(event.exception.__traceback__)
    if tb:
        last_frame = tb[-1]
        filename = Path(last_frame.filename).name
        context['file'] = f"{filename}:{last_frame.lineno}"

    return context


async def send_critical_alert(bot, exception: Exception, context: Dict[str, object]) -> None:
    """Отправляет CRITICAL алерт девелоперу с прикреплёнными логами."""
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    alert = (
        f"🚨 КРИТИЧНАЯ ОШИБКА\n\n"
        f"⏰ {timestamp} MSK\n"
        f"👤 {context.get('username', 'N/A')} ({context.get('user_id', 'N/A')})\n"
        f"📍 {context['handler']} ({context['file']})\n\n"
        f"❌ {type(exception).__name__}: {str(exception)[:200]}\n\n"
        f"📋 Traceback (последние 10 строк):\n"
        f"{format_traceback(exception, lines=10)}\n\n"
        f"🔍 Контекст:\n"
        f"- Update type: {context['update_type']}\n"
        f"- Message: {str(context.get('message_text', 'N/A'))[:100]}\n"
    )

    try:
        await bot.send_message(DEVELOPER_ID, alert)

        log_tail = read_log_tail('logs/errors.log', lines=50)
        await bot.send_document(
            DEVELOPER_ID,
            BufferedInputFile(
                log_tail.encode('utf-8'),
                filename=f"error_{int(time.time())}.log",
            ),
        )
    except Exception as e:
        logging.getLogger("errors").exception(
            "Не удалось отправить CRITICAL алерт: %s", e
        )


async def send_warning_alert(bot, exception: Exception, context: Dict[str, object]) -> None:
    """Отправляет WARNING алерт девелоперу без прикреплённых логов."""
    timestamp = datetime.now().strftime("%d.%m.%Y %H:%M:%S")

    alert = (
        f"⚠️ WARNING\n\n"
        f"⏰ {timestamp} MSK\n"
        f"👤 {context.get('username', 'N/A')} ({context.get('user_id', 'N/A')})\n"
        f"📍 {context['handler']} ({context['file']})\n\n"
        f"❌ {type(exception).__name__}: {str(exception)[:200]}\n\n"
        f"📋 Traceback (последние 5 строк):\n"
        f"{format_traceback(exception, lines=5)}\n"
    )

    try:
        await bot.send_message(DEVELOPER_ID, alert)
    except Exception as e:
        logging.getLogger("errors").exception(
            "Не удалось отправить WARNING алерт: %s", e
        )
