import logging
import sqlite3
from typing import Optional, Dict

from app.db.models import get_user, save_user
from config import DB_PATH

logger = logging.getLogger(__name__)


class RolesCacheService:
    """
    Сервис для работы с кешем ролей пользователей.
    Использует SQLite как источник данных.
    """

    @staticmethod
    def get_user_role(telegram_id: int) -> Optional[Dict]:
        """
        Получает данные пользователя из кеша (SQLite).
        Возвращает словарь с полями: telegram_id, full_name, role, department, hourly_rate
        """
        user_data = get_user(telegram_id)
        if user_data:
            logger.debug(f"Пользователь {telegram_id} найден в кеше: {user_data['role']}")
        return user_data

    @staticmethod
    def update_user_role(telegram_id: int, full_name: str, role: str, 
                        department: Optional[str] = None, hourly_rate: Optional[float] = None):
        """
        Обновляет данные пользователя в кеше (SQLite).
        """
        save_user(telegram_id, full_name, role, department, hourly_rate)
        logger.info(f"Кеш обновлён для пользователя {telegram_id}: роль {role}")

    @staticmethod
    def clear_cache():
        """
        Очищает весь кеш (удаляет всех пользователей из БД).
        Используется при смене месяца или для тестирования.
        """
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users')
            conn.commit()
        logger.warning("Кеш ролей полностью очищен")
