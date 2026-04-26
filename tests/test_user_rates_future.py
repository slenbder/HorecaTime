import sqlite3
import tempfile
import os
import pytest

from app.db.models import (
    set_user_rate_future,
    get_user_rate_future,
    delete_user_rate_future,
    get_all_future_rates,
)


# ---------------------------------------------------------------------------
# Schema helpers
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
        'INSERT OR IGNORE INTO users (telegram_id, full_name, role, created_at) '
        'VALUES (?, ?, ?, ?)',
        (telegram_id, f"User {telegram_id}", "user", "2026-01-01T00:00:00"),
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    _create_schema(path)
    yield path
    os.unlink(path)


# ---------------------------------------------------------------------------
# Tests: set_user_rate_future
# ---------------------------------------------------------------------------

class TestSetUserRateFuture:

    @pytest.mark.asyncio
    async def test_set_user_rate_future_create(self, db_path):
        """Новая запись создаётся с правильными данными."""
        with sqlite3.connect(db_path) as conn:
            _insert_user(conn, 12345)
            conn.commit()

        await set_user_rate_future(db_path, 12345, 400.0, None, 5, 2026)

        result = await get_user_rate_future(db_path, 12345)

        assert result is not None
        assert result["base_rate"] == 400.0
        assert result["extra_rate"] is None
        assert result["effective_month"] == 5
        assert result["effective_year"] == 2026

    @pytest.mark.asyncio
    async def test_set_user_rate_future_update(self, db_path):
        """Повторный вызов обновляет запись, не дублирует её."""
        with sqlite3.connect(db_path) as conn:
            _insert_user(conn, 12345)
            conn.commit()

        await set_user_rate_future(db_path, 12345, 400.0, None, 5, 2026)
        await set_user_rate_future(db_path, 12345, 450.0, 600.0, 6, 2026)

        result = await get_user_rate_future(db_path, 12345)

        assert result is not None
        assert result["base_rate"] == 450.0
        assert result["extra_rate"] == 600.0
        assert result["effective_month"] == 6
        assert result["effective_year"] == 2026

        with sqlite3.connect(db_path) as conn:
            count = conn.execute(
                'SELECT COUNT(*) FROM user_rates_future WHERE telegram_id = ?',
                (12345,),
            ).fetchone()[0]
        assert count == 1

    @pytest.mark.asyncio
    async def test_set_user_rate_future_with_extra(self, db_path):
        """Запись с extra_rate сохраняется корректно."""
        with sqlite3.connect(db_path) as conn:
            _insert_user(conn, 67890)
            conn.commit()

        await set_user_rate_future(db_path, 67890, 300.0, 450.0, 5, 2026)

        result = await get_user_rate_future(db_path, 67890)

        assert result is not None
        assert result["base_rate"] == 300.0
        assert result["extra_rate"] == 450.0


# ---------------------------------------------------------------------------
# Tests: get_user_rate_future
# ---------------------------------------------------------------------------

class TestGetUserRateFuture:

    @pytest.mark.asyncio
    async def test_get_user_rate_future_not_found(self, db_path):
        """Запись отсутствует → возвращает None."""
        result = await get_user_rate_future(db_path, 99999)

        assert result is None


# ---------------------------------------------------------------------------
# Tests: delete_user_rate_future
# ---------------------------------------------------------------------------

class TestDeleteUserRateFuture:

    @pytest.mark.asyncio
    async def test_delete_user_rate_future(self, db_path):
        """Удаление существующей записи — запись пропадает из БД."""
        with sqlite3.connect(db_path) as conn:
            _insert_user(conn, 12345)
            conn.commit()

        await set_user_rate_future(db_path, 12345, 400.0, None, 5, 2026)
        await delete_user_rate_future(db_path, 12345)

        assert await get_user_rate_future(db_path, 12345) is None
        assert await get_all_future_rates(db_path) == []

    @pytest.mark.asyncio
    async def test_delete_user_rate_future_nonexistent(self, db_path):
        """Удаление несуществующей записи не вызывает исключения (идемпотентно)."""
        await delete_user_rate_future(db_path, 99999)


# ---------------------------------------------------------------------------
# Tests: get_all_future_rates
# ---------------------------------------------------------------------------

class TestGetAllFutureRates:

    @pytest.mark.asyncio
    async def test_get_all_future_rates_empty(self, db_path):
        """Пустая таблица → возвращает пустой список."""
        result = await get_all_future_rates(db_path)

        assert result == []

    @pytest.mark.asyncio
    async def test_get_all_future_rates_multiple(self, db_path):
        """Три записи возвращаются полностью и с корректными данными."""
        with sqlite3.connect(db_path) as conn:
            for tid in (111, 222, 333):
                _insert_user(conn, tid)
            conn.commit()

        await set_user_rate_future(db_path, 111, 300.0, None, 5, 2026)
        await set_user_rate_future(db_path, 222, 400.0, 500.0, 5, 2026)
        await set_user_rate_future(db_path, 333, 250.0, None, 6, 2026)

        result = await get_all_future_rates(db_path)

        assert len(result) == 3

        by_id = {r["telegram_id"]: r for r in result}
        assert set(by_id.keys()) == {111, 222, 333}

        assert by_id[111]["base_rate"] == 300.0
        assert by_id[111]["extra_rate"] is None
        assert by_id[111]["effective_month"] == 5
        assert by_id[111]["effective_year"] == 2026

        assert by_id[222]["base_rate"] == 400.0
        assert by_id[222]["extra_rate"] == 500.0
        assert by_id[222]["effective_month"] == 5

        assert by_id[333]["base_rate"] == 250.0
        assert by_id[333]["effective_month"] == 6
        assert by_id[333]["effective_year"] == 2026
