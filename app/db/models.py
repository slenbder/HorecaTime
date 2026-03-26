import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict
from zoneinfo import ZoneInfo

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)

_DEFAULT_RATES = [
    ("Бармен",            350.0, 500.0),
    ("Барбэк",            250.0, 400.0),
    ("Официант",          250.0, None),
    ("Раннер",            200.0, 300.0),
    ("Хостесс",           200.0, None),
    ("Менеджер",          350.0, None),
    ("Горячий цех",       280.0, None),
    ("Холодный цех",      250.0, None),
    ("Кондитерский цех",  280.0, None),
    ("Заготовочный цех",  230.0, None),
    ("Коренной цех",      230.0, None),
    ("Грузчик",           180.0, None),
    ("Закупщик",          180.0, None),
    ("Клининг",           200.0, None),
    ("Котломой",          200.0, None),
    ("Су-шеф",            500.0, None),
]


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
                position TEXT,
                hourly_rate REAL,
                created_at TEXT NOT NULL
            )
        ''')
        # Миграция: добавить колонку position для уже существующих баз
        try:
            cursor.execute('ALTER TABLE users ADD COLUMN position TEXT')
        except sqlite3.OperationalError:
            pass  # колонка уже существует

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS fsm_storage (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                bot_id  INTEGER NOT NULL,
                state   TEXT,
                data    TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (chat_id, user_id, bot_id)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rates (
                position   TEXT PRIMARY KEY,
                base_rate  REAL NOT NULL,
                extra_rate REAL,
                updated_at TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS rates_history (
                position   TEXT NOT NULL,
                base_rate  REAL NOT NULL,
                extra_rate REAL,
                month      INTEGER NOT NULL,
                year       INTEGER NOT NULL,
                PRIMARY KEY (position, month, year)
            )
        ''')
        # Вставить дефолтные ставки, если таблица пустая
        cursor.execute('SELECT COUNT(*) FROM rates')
        if cursor.fetchone()[0] == 0:
            now_str = datetime.now(ZoneInfo("Europe/Moscow")).isoformat()
            cursor.executemany(
                'INSERT INTO rates (position, base_rate, extra_rate, updated_at) VALUES (?, ?, ?, ?)',
                [(pos, base, extra, now_str) for pos, base, extra in _DEFAULT_RATES],
            )
            logger.info("Дефолтные ставки вставлены в таблицу rates")
        else:
            # Миграция: добавить новые позиции если они отсутствуют
            now_str = datetime.now(ZoneInfo("Europe/Moscow")).isoformat()
            cursor.executemany(
                'INSERT OR IGNORE INTO rates (position, base_rate, extra_rate, updated_at) VALUES (?, ?, ?, ?)',
                [(pos, base, extra, now_str) for pos, base, extra in _DEFAULT_RATES],
            )
            logger.info("Миграция ставок: добавлены недостающие позиции")
        conn.commit()
    logger.info("База данных успешно инициализирована")


def save_user(telegram_id: int, full_name: str, role: str,
              department: Optional[str] = None, hourly_rate: Optional[float] = None,
              position: Optional[str] = None):
    """
    Сохраняет или обновляет пользователя в БД.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO users
                    (telegram_id, full_name, role, department, position, hourly_rate, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (telegram_id, full_name, role, department, position, hourly_rate,
                  datetime.now(ZoneInfo("Europe/Moscow")).isoformat()))
            conn.commit()
        logger.info("Пользователь %s (%s) сохранён в БД с ролью %s", telegram_id, full_name, role)
    except sqlite3.Error as e:
        logger.error("Ошибка при сохранении пользователя %s в БД: %s", telegram_id, e)
        raise


def get_user(telegram_id: int) -> Optional[Dict]:
    """
    Возвращает данные пользователя из БД.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT telegram_id, full_name, role, department, position, hourly_rate '
                'FROM users WHERE telegram_id = ?',
                (telegram_id,)
            )
            row = cursor.fetchone()
            if row:
                return {
                    "telegram_id": row[0],
                    "full_name": row[1],
                    "role": row[2],
                    "department": row[3],
                    "position": row[4],
                    "hourly_rate": row[5],
                }
    except sqlite3.Error as e:
        logger.error("Ошибка при получении пользователя %s из БД: %s", telegram_id, e)
    return None


def get_users_by_role(db_path: str, role: str) -> list[dict]:
    """
    Возвращает список пользователей с указанной ролью.
    """
    try:
        with sqlite3.connect(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT telegram_id, full_name, department FROM users WHERE role = ?',
                (role,)
            )
            rows = cursor.fetchall()
            return [
                {"telegram_id": row[0], "full_name": row[1], "department": row[2]}
                for row in rows
            ]
    except sqlite3.Error as e:
        logger.error("Ошибка при получении пользователей с ролью %s: %s", role, e)
    return []


def delete_user(telegram_id: int) -> None:
    """
    Удаляет пользователя из таблицы users по telegram_id.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            cursor.execute('DELETE FROM users WHERE telegram_id = ?', (telegram_id,))
            conn.commit()
        logger.info("Пользователь %s удалён из БД", telegram_id)
    except sqlite3.Error as e:
        logger.error("Ошибка при удалении пользователя %s из БД: %s", telegram_id, e)
        raise


# --- Выборки пользователей (async, aiosqlite) ---

async def get_users_by_department(db_path: str, department: str) -> list[dict]:
    """
    Возвращает всех пользователей с указанным department
    (исключая superadmin и developer).
    """
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            'SELECT telegram_id, full_name, role, department '
            'FROM users WHERE department = ? AND role NOT IN ("superadmin", "developer")',
            (department,)
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {"telegram_id": r[0], "full_name": r[1], "role": r[2], "department": r[3]}
        for r in rows
    ]


async def get_all_users(db_path: str) -> list[dict]:
    """
    Возвращает всех пользователей кроме superadmin и developer.
    """
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            'SELECT telegram_id, full_name, role, department '
            'FROM users WHERE role NOT IN ("superadmin", "developer")'
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {"telegram_id": r[0], "full_name": r[1], "role": r[2], "department": r[3]}
        for r in rows
    ]


# --- Ставки (async, aiosqlite) ---

async def get_rate(db_path: str, position: str) -> Optional[Dict]:
    """
    Возвращает ставку для позиции: {"position", "base_rate", "extra_rate"} или None.
    """
    logger.info("get_rate: position=%s", position)
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            'SELECT position, base_rate, extra_rate FROM rates WHERE position = ?',
            (position,)
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return {"position": row[0], "base_rate": row[1], "extra_rate": row[2]}


async def get_all_rates(db_path: str) -> list[dict]:
    """
    Возвращает все ставки, отсортированные по позиции.
    """
    logger.info("get_all_rates: запрос всех ставок")
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            'SELECT position, base_rate, extra_rate FROM rates ORDER BY position'
        ) as cursor:
            rows = await cursor.fetchall()
    return [{"position": r[0], "base_rate": r[1], "extra_rate": r[2]} for r in rows]


async def snapshot_rates(db_path: str, month: int, year: int) -> None:
    """
    Копирует текущие ставки из rates в rates_history для указанного месяца/года.
    Если запись уже существует — не перезаписывает (INSERT OR IGNORE).
    """
    logger.info("snapshot_rates: сохранение снимка ставок для %d/%d", month, year)
    async with aiosqlite.connect(db_path) as db:
        async with db.execute('SELECT position, base_rate, extra_rate FROM rates') as cursor:
            rows = await cursor.fetchall()
        await db.executemany(
            'INSERT OR IGNORE INTO rates_history (position, base_rate, extra_rate, month, year) '
            'VALUES (?, ?, ?, ?, ?)',
            [(r[0], r[1], r[2], month, year) for r in rows],
        )
        await db.commit()
    logger.info("snapshot_rates: сохранено %d записей для %d/%d", len(rows), month, year)


async def get_rate_for_period(db_path: str, position: str, month: int, year: int) -> Optional[Dict]:
    """
    Читает ставку из rates_history для указанной позиции и периода.
    Если не найдено — возвращает текущую ставку из rates как fallback.
    """
    logger.info("get_rate_for_period: position=%s month=%d year=%d", position, month, year)
    async with aiosqlite.connect(db_path) as db:
        async with db.execute(
            'SELECT position, base_rate, extra_rate FROM rates_history '
            'WHERE position = ? AND month = ? AND year = ?',
            (position, month, year),
        ) as cursor:
            row = await cursor.fetchone()
    if row is not None:
        return {"position": row[0], "base_rate": row[1], "extra_rate": row[2]}
    logger.warning(
        "get_rate_for_period: снимок для %s %d/%d не найден, используем текущую ставку",
        position, month, year,
    )
    return await get_rate(db_path, position)


async def update_rate(db_path: str, position: str, base_rate: float,
                      extra_rate: Optional[float] = None) -> None:
    """
    Обновляет ставку для позиции.
    """
    now_str = datetime.now(ZoneInfo("Europe/Moscow")).isoformat()
    logger.info("update_rate: position=%s base_rate=%s extra_rate=%s", position, base_rate, extra_rate)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            'INSERT OR REPLACE INTO rates (position, base_rate, extra_rate, updated_at) VALUES (?, ?, ?, ?)',
            (position, base_rate, extra_rate, now_str),
        )
        await db.commit()
