import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict
from config import DB_PATH

logger = logging.getLogger(__name__)


def init_database():
    """
    Создаёт таблицы, если их нет.
    """
    logger.info(f"Инициализация базы данных: {DB_PATH}")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                department TEXT,
                hourly_rate REAL,
                created_at TEXT NOT NULL
            )
        ''')
        conn.commit()
    logger.info("База данных успешно инициализирована")


def save_user(telegram_id: int, full_name: str, role: str, 
              department: Optional[str] = None, hourly_rate: Optional[float] = None):
    """
    Сохраняет или обновляет пользователя в БД.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (telegram_id, full_name, role, department, hourly_rate, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (telegram_id, full_name, role, department, hourly_rate, datetime.now().isoformat()))
        conn.commit()
    logger.info(f"Пользователь {telegram_id} ({full_name}) сохранён в БД с ролью {role}")


def get_user(telegram_id: int) -> Optional[Dict]:
    """
    Возвращает данные пользователя из БД.
    """
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT telegram_id, full_name, role, department, hourly_rate FROM users WHERE telegram_id = ?', 
                      (telegram_id,))
        row = cursor.fetchone()
        if row:
            return {
                "telegram_id": row[0],
                "full_name": row[1],
                "role": row[2],
                "department": row[3],
                "hourly_rate": row[4]
            }
    return None
