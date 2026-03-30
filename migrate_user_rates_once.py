# Одноразовый скрипт. Запущен 2026-03-28. Оставлен как документация миграции.
# Копирует шаблонные ставки из rates в user_rates для всех существующих юзеров.

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH
from app.db.models import get_all_users, get_rate, set_user_rate

logging.basicConfig(
    filename="logs/app.log",
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

KNOWN_POSITIONS = {
    "Официант", "Раннер", "Хостесс", "Менеджер", "Бармен", "Барбэк",
    "Горячий цех", "Холодный цех", "Кондитерский цех", "Заготовочный цех",
    "Коренной цех", "Грузчик", "Закупщик", "Клининг", "Котломой",
    "Руководящий состав",
}
FALLBACK_POSITION = "Руководящий состав"
FALLBACK_RATE = (250.0, None)


async def migrate() -> None:
    logger.info("Migration started")
    try:
        users = await get_all_users(DB_PATH)
    except Exception:
        logger.error("Failed to fetch users", exc_info=True)
        return

    count = 0
    for user in users:
        telegram_id = user["telegram_id"]
        full_name = user["full_name"]
        position = user.get("position") or ""

        normalized = position if position in KNOWN_POSITIONS else FALLBACK_POSITION

        try:
            rate = await get_rate(DB_PATH, normalized)
        except Exception:
            logger.error("Failed to get rate for %s (%s)", full_name, normalized, exc_info=True)
            rate = None

        if rate is None:
            base_rate, extra_rate = FALLBACK_RATE
        else:
            base_rate = rate["base_rate"]
            extra_rate = rate["extra_rate"]

        try:
            await set_user_rate(DB_PATH, telegram_id, base_rate, extra_rate)
        except Exception:
            logger.error("Failed to set user_rate for %s (%s)", full_name, telegram_id, exc_info=True)
            continue

        logger.info("Migrated %s (%s): %s/%s р/ч", full_name, position, base_rate, extra_rate)
        count += 1

    logger.info("Migration completed: %d users", count)


if __name__ == "__main__":
    asyncio.run(migrate())
