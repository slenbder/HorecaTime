import logging
import aiosqlite
from datetime import datetime, timedelta
from pathlib import Path

from config import DB_PATH, DEVELOPER_ID

logger = logging.getLogger(__name__)


def count_errors_in_log(filepath: str = "logs/errors.log", hours: int = 1) -> int:
    """
    Подсчитывает количество ERROR записей за последние N часов.
    Парсит строки формата: "2026-04-10 12:34:56 | ... | ERROR | ..."
    """
    try:
        path = Path(filepath)
        if not path.exists():
            return 0

        cutoff = datetime.now() - timedelta(hours=hours)
        error_count = 0

        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if ' | ERROR | ' not in line:
                    continue

                try:
                    # Извлекаем "2026-04-10 12:34:56" (первые 19 символов)
                    timestamp_str = line[:19]
                    log_time = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")

                    if log_time >= cutoff:
                        error_count += 1
                except (ValueError, IndexError):
                    continue  # строка не в ожидаемом формате

        return error_count

    except Exception as e:
        logger.warning("Не удалось подсчитать ошибки в логе: %s", e)
        return 0


async def healthcheck(bot) -> None:
    """
    Проверяет здоровье критичных компонентов.
    Вызывается каждые 30 минут через APScheduler.
    """
    logger.info("Запуск healthcheck")
    issues = []

    # 1. Google Sheets доступен?
    try:
        from app.services.google_sheets import GoogleSheetsClient
        sheets = GoogleSheetsClient()
        sheets._get_techlist_worksheet()
        logger.info("Healthcheck: Google Sheets ✅")
    except Exception as e:
        issues.append(f"❌ Google Sheets недоступен: {type(e).__name__}")
        logger.error("Healthcheck: Google Sheets ❌ — %s", e)

    # 2. SQLite не locked?
    try:
        async with aiosqlite.connect(DB_PATH, timeout=5) as db:
            await db.execute("SELECT 1")
        logger.info("Healthcheck: SQLite ✅")
    except Exception as e:
        issues.append(f"❌ SQLite locked/недоступен: {type(e).__name__}")
        logger.error("Healthcheck: SQLite ❌ — %s", e)

    # 3. Errors.log растёт слишком быстро?
    error_count = count_errors_in_log(hours=1)
    if error_count > 50:
        issues.append(f"⚠️ {error_count} ошибок за последний час")
        logger.warning("Healthcheck: высокий уровень ошибок — %s/час", error_count)
    else:
        logger.info("Healthcheck: уровень ошибок в норме (%s/час)", error_count)

    # Отправляем алерт если есть проблемы
    if issues:
        alert = "🔍 Healthcheck Issues:\n\n" + "\n".join(issues)
        try:
            await bot.send_message(DEVELOPER_ID, alert)
            logger.info("Healthcheck алерт отправлен девелоперу")
        except Exception as e:
            logger.error("Не удалось отправить healthcheck алерт: %s", e)
    else:
        logger.info("Healthcheck: все системы в норме ✅")
