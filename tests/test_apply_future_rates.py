import sqlite3
import pytest

from app.scheduler.monthly_switch import apply_future_rates
from app.db.models import (
    set_user_rate,
    get_user_rate,
    set_user_rate_future,
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
            CREATE TABLE IF NOT EXISTS user_rates (
                telegram_id INTEGER PRIMARY KEY REFERENCES users(telegram_id),
                base_rate   REAL NOT NULL,
                extra_rate  REAL,
                updated_at  TEXT NOT NULL
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
        "INSERT INTO users (telegram_id, full_name, role, department, created_at) "
        "VALUES (?, 'Test User', 'user', 'Кухня', datetime('now'))",
        (telegram_id,),
    )


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def db_path(tmp_path):
    path = str(tmp_path / "test.db")
    _create_schema(path)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestApplyFutureRates:

    @pytest.mark.asyncio
    async def test_apply_future_rates_success(self, db_path):
        """Две майские future-ставки применяются в user_rates и удаляются из future."""
        with sqlite3.connect(db_path) as conn:
            _insert_user(conn, 111)
            _insert_user(conn, 222)
            conn.commit()

        await set_user_rate(db_path, 111, 300.0, None)
        await set_user_rate(db_path, 222, 400.0, 500.0)

        await set_user_rate_future(db_path, 111, 350.0, None, 5, 2026)
        await set_user_rate_future(db_path, 222, 450.0, 600.0, 5, 2026)

        await apply_future_rates(db_path, 5, 2026)

        rate_111 = await get_user_rate(db_path, 111)
        assert rate_111 is not None
        assert rate_111["base_rate"] == 350.0
        assert rate_111["extra_rate"] is None

        rate_222 = await get_user_rate(db_path, 222)
        assert rate_222 is not None
        assert rate_222["base_rate"] == 450.0
        assert rate_222["extra_rate"] == 600.0

        assert await get_all_future_rates(db_path) == []

    @pytest.mark.asyncio
    async def test_apply_future_rates_only_target_month(self, db_path):
        """Майская future-ставка применяется; июньская остаётся нетронутой."""
        with sqlite3.connect(db_path) as conn:
            _insert_user(conn, 111)
            _insert_user(conn, 222)
            conn.commit()

        await set_user_rate(db_path, 111, 300.0, None)
        await set_user_rate(db_path, 222, 400.0, None)

        await set_user_rate_future(db_path, 111, 350.0, None, 5, 2026)
        await set_user_rate_future(db_path, 222, 500.0, None, 6, 2026)

        await apply_future_rates(db_path, 5, 2026)

        rate_111 = await get_user_rate(db_path, 111)
        assert rate_111 is not None
        assert rate_111["base_rate"] == 350.0

        rate_222 = await get_user_rate(db_path, 222)
        assert rate_222 is not None
        assert rate_222["base_rate"] == 400.0  # не изменилась

        remaining = await get_all_future_rates(db_path)
        assert len(remaining) == 1
        assert remaining[0]["telegram_id"] == 222
        assert remaining[0]["effective_month"] == 6
        assert remaining[0]["effective_year"] == 2026

    @pytest.mark.asyncio
    async def test_apply_future_rates_no_applicable(self, db_path):
        """Нет future-ставок на целевой месяц — user_rates не меняются, ошибки нет."""
        with sqlite3.connect(db_path) as conn:
            _insert_user(conn, 111)
            conn.commit()

        await set_user_rate(db_path, 111, 300.0, None)

        await apply_future_rates(db_path, 5, 2026)

        rate_111 = await get_user_rate(db_path, 111)
        assert rate_111 is not None
        assert rate_111["base_rate"] == 300.0
