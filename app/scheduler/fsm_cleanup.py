import logging

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)


async def cleanup_expired_fsm_states() -> None:
    """Очистка FSM состояний старше 15 минут."""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            cursor = await db.execute(
                "DELETE FROM fsm_storage WHERE updated_at < datetime('now', '-15 minutes')"
            )
            deleted = cursor.rowcount
            await db.commit()

        if deleted > 0:
            logger.info("Очищено %d устаревших FSM состояний (TTL 15 мин)", deleted)
    except Exception as e:
        logger.error("Ошибка при очистке FSM состояний: %s", e, exc_info=True)
