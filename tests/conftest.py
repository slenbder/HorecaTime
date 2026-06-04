import sqlite3

import pytest
from unittest.mock import MagicMock

from app.services.google_sheets import GoogleSheetsClient


# ---------------------------------------------------------------------------
# Step 1: GoogleSheetsClient factory fixture (replaces local _make_client())
# ---------------------------------------------------------------------------

@pytest.fixture
def sheets_client() -> GoogleSheetsClient:
    client = object.__new__(GoogleSheetsClient)
    client._spreadsheet = MagicMock()
    client._client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Step 2: Shared DB helpers (replaces duplicated _create_schema / _insert_user)
# ---------------------------------------------------------------------------

def _create_schema(db_path: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                full_name   TEXT NOT NULL,
                role        TEXT NOT NULL,
                department  TEXT,
                position    TEXT,
                hourly_rate REAL,
                created_at  TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_rates (
                telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id),
                base_rate   REAL NOT NULL,
                extra_rate  REAL,
                updated_at  TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS user_rates_history (
                telegram_id INTEGER NOT NULL,
                base_rate   REAL    NOT NULL,
                extra_rate  REAL,
                month       INTEGER NOT NULL,
                year        INTEGER NOT NULL,
                PRIMARY KEY (telegram_id, month, year)
            )
        ''')
        conn.execute('''
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


def _insert_user(conn: sqlite3.Connection, telegram_id: int) -> None:
    conn.execute(
        'INSERT OR IGNORE INTO users (telegram_id, full_name, role, department, created_at) '
        'VALUES (?, ?, ?, ?, ?)',
        (telegram_id, f"User {telegram_id}", "user", "Кухня", "2026-01-01T00:00:00"),
    )


@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    _create_schema(path)
    return path


@pytest.fixture()
def insert_user():
    return _insert_user
