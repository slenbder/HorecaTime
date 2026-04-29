import sqlite3
import logging
from datetime import datetime
from typing import Optional, Dict
from zoneinfo import ZoneInfo

import aiosqlite

from config import DB_PATH

logger = logging.getLogger(__name__)


def init_database():
    """
    Создаёт таблицы, если их нет.
    """
    logger.info(f"Инициализация базы данных: {DB_PATH}")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
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
                chat_id    INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                bot_id     INTEGER NOT NULL,
                state      TEXT,
                data       TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (chat_id, user_id, bot_id)
            )
        ''')
        # Миграция: добавить updated_at если таблица уже существовала без неё
        try:
            cursor.execute(
                "ALTER TABLE fsm_storage ADD COLUMN updated_at TEXT NOT NULL DEFAULT (datetime('now'))"
            )
        except sqlite3.OperationalError:
            pass  # колонка уже существует
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_rates (
                telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id),
                base_rate   REAL NOT NULL,
                extra_rate  REAL,
                updated_at  TEXT NOT NULL
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_rates_history (
                telegram_id INTEGER NOT NULL,
                base_rate   REAL NOT NULL,
                extra_rate  REAL,
                month       INTEGER NOT NULL,
                year        INTEGER NOT NULL,
                PRIMARY KEY (telegram_id, month, year)
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_rates_future (
                telegram_id      INTEGER PRIMARY KEY REFERENCES users(telegram_id) ON DELETE CASCADE,
                base_rate        REAL NOT NULL,
                extra_rate       REAL,
                effective_month  INTEGER NOT NULL,
                effective_year   INTEGER NOT NULL,
                created_at       TEXT NOT NULL
            )
        ''')
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
            cursor.execute('DELETE FROM user_rates_history WHERE telegram_id = ?', (telegram_id,))
            logger.info("delete_user: удалены ставки telegram_id=%s", telegram_id)
            cursor.execute('DELETE FROM user_rates_future WHERE telegram_id = ?', (telegram_id,))
            logger.info("delete_user: удалены ставки telegram_id=%s", telegram_id)
            cursor.execute('DELETE FROM user_rates WHERE telegram_id = ?', (telegram_id,))
            logger.info("delete_user: удалены ставки telegram_id=%s", telegram_id)
            cursor.execute('DELETE FROM users WHERE telegram_id = ?', (telegram_id,))
            conn.commit()
        logger.info("Пользователь %s удалён из БД", telegram_id)
    except sqlite3.Error as e:
        logger.error("Ошибка при удалении пользователя %s из БД: %s", telegram_id, e)
        raise


# --- Выборки пользователей (async, aiosqlite) ---

async def get_user_role(db_path: str, telegram_id: int) -> Optional[str]:
    """
    Возвращает role пользователя из БД или None если не найден.
    """
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        async with db.execute(
            'SELECT role FROM users WHERE telegram_id = ?',
            (telegram_id,)
        ) as cursor:
            row = await cursor.fetchone()
    return row[0] if row else None


async def get_users_by_department(db_path: str, department: str) -> list[dict]:
    """
    Возвращает всех пользователей с указанным department
    (исключая superadmin и developer).
    """
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
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
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        async with db.execute(
            'SELECT telegram_id, full_name, role, department '
            'FROM users WHERE role NOT IN ("superadmin", "developer")'
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {"telegram_id": r[0], "full_name": r[1], "role": r[2], "department": r[3]}
        for r in rows
    ]


# --- Персональные ставки (async, aiosqlite) ---

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


async def get_user_rate(db_path: str, telegram_id: int) -> Optional[Dict]:
    """
    Возвращает персональную ставку сотрудника: {"telegram_id", "base_rate", "extra_rate"} или None.
    """
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT telegram_id, base_rate, extra_rate FROM user_rates WHERE telegram_id = ?',
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return {"telegram_id": row["telegram_id"], "base_rate": row["base_rate"], "extra_rate": row["extra_rate"]}


async def set_user_rate(db_path: str, telegram_id: int, base_rate: float,
                        extra_rate: Optional[float] = None) -> None:
    """
    Устанавливает персональную ставку сотрудника (INSERT или UPDATE при конфликте).
    """
    now_str = datetime.now(MOSCOW_TZ).isoformat()
    logger.info("set_user_rate: telegram_id=%s base_rate=%s extra_rate=%s", telegram_id, base_rate, extra_rate)
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        await db.execute(
            'INSERT INTO user_rates (telegram_id, base_rate, extra_rate, updated_at) VALUES (?, ?, ?, ?) '
            'ON CONFLICT(telegram_id) DO UPDATE SET base_rate=excluded.base_rate, '
            'extra_rate=excluded.extra_rate, updated_at=excluded.updated_at',
            (telegram_id, base_rate, extra_rate, now_str),
        )
        await db.commit()


async def set_user_rate_future(
    db_path: str,
    telegram_id: int,
    base_rate: float,
    extra_rate: Optional[float],
    effective_month: int,
    effective_year: int,
) -> None:
    """
    Устанавливает будущую ставку сотрудника (с 1-го числа указанного месяца).
    При повторном вызове для того же telegram_id — перезаписывает.
    """
    now_str = datetime.now(MOSCOW_TZ).isoformat()
    logger.info(
        "set_user_rate_future: telegram_id=%s base_rate=%s extra_rate=%s effective=%d/%d",
        telegram_id, base_rate, extra_rate, effective_month, effective_year,
    )
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        await db.execute(
            'INSERT INTO user_rates_future '
            '(telegram_id, base_rate, extra_rate, effective_month, effective_year, created_at) '
            'VALUES (?, ?, ?, ?, ?, ?) '
            'ON CONFLICT(telegram_id) DO UPDATE SET '
            'base_rate=excluded.base_rate, extra_rate=excluded.extra_rate, '
            'effective_month=excluded.effective_month, effective_year=excluded.effective_year, '
            'created_at=excluded.created_at',
            (telegram_id, base_rate, extra_rate, effective_month, effective_year, now_str),
        )
        await db.commit()


async def get_user_rate_future(db_path: str, telegram_id: int) -> Optional[Dict]:
    """
    Возвращает запланированную будущую ставку сотрудника, если она есть.
    Формат: {"base_rate", "extra_rate", "effective_month", "effective_year"}
    """
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        async with db.execute(
            'SELECT base_rate, extra_rate, effective_month, effective_year '
            'FROM user_rates_future WHERE telegram_id = ?',
            (telegram_id,),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return {
        "base_rate": row[0],
        "extra_rate": row[1],
        "effective_month": row[2],
        "effective_year": row[3],
    }


async def delete_user_rate_future(db_path: str, telegram_id: int) -> None:
    """Удаляет запланированную будущую ставку сотрудника."""
    logger.info("delete_user_rate_future: telegram_id=%s", telegram_id)
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        await db.execute(
            'DELETE FROM user_rates_future WHERE telegram_id = ?',
            (telegram_id,),
        )
        await db.commit()


async def get_all_future_rates(db_path: str) -> list[dict]:
    """
    Возвращает все запланированные будущие ставки.
    Используется в switch_month() для применения изменений.
    """
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        async with db.execute(
            'SELECT telegram_id, base_rate, extra_rate, effective_month, effective_year '
            'FROM user_rates_future',
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {
            "telegram_id": r[0],
            "base_rate": r[1],
            "extra_rate": r[2],
            "effective_month": r[3],
            "effective_year": r[4],
        }
        for r in rows
    ]


async def get_user_rate_history(db_path: str, telegram_id: int, month: int, year: int) -> Optional[Dict]:
    """
    Читает персональную ставку из user_rates_history для указанного периода.
    Возвращает {"telegram_id", "base_rate", "extra_rate"} или None.
    """
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT telegram_id, base_rate, extra_rate FROM user_rates_history '
            'WHERE telegram_id = ? AND month = ? AND year = ?',
            (telegram_id, month, year),
        ) as cursor:
            row = await cursor.fetchone()
    if row is None:
        return None
    return {"telegram_id": row["telegram_id"], "base_rate": row["base_rate"], "extra_rate": row["extra_rate"]}


async def snapshot_user_rates_history(db_path: str, month: int, year: int) -> None:
    """
    Копирует все записи из user_rates в user_rates_history для указанного месяца/года.
    Существующие записи не перезаписываются (INSERT OR IGNORE).
    """
    logger.info("snapshot_user_rates_history: сохранение снимка персональных ставок для %d/%d", month, year)
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        async with db.execute('SELECT telegram_id, base_rate, extra_rate FROM user_rates') as cursor:
            rows = await cursor.fetchall()
        await db.executemany(
            'INSERT OR IGNORE INTO user_rates_history (telegram_id, base_rate, extra_rate, month, year) '
            'VALUES (?, ?, ?, ?, ?)',
            [(r[0], r[1], r[2], month, year) for r in rows],
        )
        await db.commit()
    logger.info("snapshot_user_rates_history: сохранено %d записей для %d/%d", len(rows), month, year)


async def get_users_rates_by_department(db_path: str, department: str) -> list[dict]:
    """
    Возвращает всех сотрудников отдела с их персональными ставками (JOIN users + user_rates).
    """
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT u.telegram_id, u.full_name, u.position, ur.base_rate, ur.extra_rate '
            'FROM users u JOIN user_rates ur ON u.telegram_id = ur.telegram_id '
            'WHERE u.department = ? AND u.role NOT IN ("superadmin", "developer")',
            (department,),
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {
            "telegram_id": r["telegram_id"],
            "full_name": r["full_name"],
            "position": r["position"],
            "base_rate": r["base_rate"],
            "extra_rate": r["extra_rate"],
        }
        for r in rows
    ]


async def get_all_users_rates(db_path: str) -> list[dict]:
    """
    Возвращает всех сотрудников с персональными ставками (JOIN users + user_rates).
    Исключает superadmin и developer.
    """
    async with aiosqlite.connect(db_path, timeout=10.0, isolation_level=None) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            'SELECT u.telegram_id, u.full_name, u.department, u.position, ur.base_rate, ur.extra_rate '
            'FROM users u JOIN user_rates ur ON u.telegram_id = ur.telegram_id '
            'WHERE u.role NOT IN ("superadmin", "developer")',
        ) as cursor:
            rows = await cursor.fetchall()
    return [
        {
            "telegram_id": r["telegram_id"],
            "full_name": r["full_name"],
            "department": r["department"],
            "position": r["position"],
            "base_rate": r["base_rate"],
            "extra_rate": r["extra_rate"],
        }
        for r in rows
    ]


async def get_admins_by_department(db_path: str, department: str) -> list[int]:
    """
    Возвращает список telegram_id всех админов отдела.

    Args:
        db_path: путь к SQLite БД
        department: "Зал", "Бар", "Кухня" или "МОП"

    Returns:
        Список telegram_id админов (например [123456789, 987654321])
        Пустой список если отдел неизвестен или админов нет
    """
    async with aiosqlite.connect(db_path) as db:
        role_map = {
            "Зал": "admin_hall",
            "Бар": "admin_bar",
            "Кухня": "admin_kitchen",
            "МОП": "admin_hall",  # МОП подчиняется admin_hall
        }
        role = role_map.get(department)
        if not role:
            return []

        cursor = await db.execute(
            "SELECT telegram_id FROM users WHERE role = ?",
            (role,)
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
