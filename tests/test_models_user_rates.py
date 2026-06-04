import sqlite3
import pytest

from app.db.models import get_user_rate, set_user_rate, get_user_rate_history


# ---------------------------------------------------------------------------
# Tests: get_user_rate
# ---------------------------------------------------------------------------

class TestGetUserRate:

    @pytest.mark.asyncio
    async def test_get_user_rate_found(self, db_path, insert_user):
        """Ставка существует → возвращает словарь с base_rate."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 123)
            conn.execute(
                'INSERT INTO user_rates (telegram_id, base_rate, extra_rate, updated_at) '
                'VALUES (?, ?, ?, ?)',
                (123, 300.0, None, "2026-01-01T00:00:00"),
            )
            conn.commit()

        result = await get_user_rate(db_path, 123)

        assert result is not None
        assert result["telegram_id"] == 123
        assert result["base_rate"] == 300.0

    @pytest.mark.asyncio
    async def test_get_user_rate_not_found(self, db_path):
        """Запись отсутствует → возвращает None."""
        result = await get_user_rate(db_path, 999)

        assert result is None

    @pytest.mark.asyncio
    async def test_get_user_rate_with_extra(self, db_path, insert_user):
        """Позиция с extra_rate → оба поля возвращаются корректно."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 123)
            conn.execute(
                'INSERT INTO user_rates (telegram_id, base_rate, extra_rate, updated_at) '
                'VALUES (?, ?, ?, ?)',
                (123, 300.0, 350.0, "2026-01-01T00:00:00"),
            )
            conn.commit()

        result = await get_user_rate(db_path, 123)

        assert result is not None
        assert result["base_rate"] == 300.0
        assert result["extra_rate"] == 350.0


# ---------------------------------------------------------------------------
# Tests: set_user_rate
# ---------------------------------------------------------------------------

class TestSetUserRate:

    @pytest.mark.asyncio
    async def test_set_user_rate_create(self, db_path, insert_user):
        """Новая запись создаётся с правильными данными."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 123)
            conn.commit()

        await set_user_rate(db_path, 123, 300.0, None)

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                'SELECT base_rate, extra_rate FROM user_rates WHERE telegram_id = ?',
                (123,),
            ).fetchone()

        assert row is not None
        assert row[0] == 300.0
        assert row[1] is None

    @pytest.mark.asyncio
    async def test_set_user_rate_update(self, db_path, insert_user):
        """Обновление существующей ставки — запись не дублируется."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 123)
            conn.execute(
                'INSERT INTO user_rates (telegram_id, base_rate, extra_rate, updated_at) '
                'VALUES (?, ?, ?, ?)',
                (123, 300.0, None, "2026-01-01T00:00:00"),
            )
            conn.commit()

        await set_user_rate(db_path, 123, 350.0, None)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                'SELECT base_rate FROM user_rates WHERE telegram_id = ?',
                (123,),
            ).fetchall()

        assert len(rows) == 1          # не задублировалась
        assert rows[0][0] == 350.0     # обновилась

    @pytest.mark.asyncio
    async def test_set_user_rate_no_extra(self, db_path, insert_user):
        """extra_rate=None сохраняется как NULL в БД."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 456)
            conn.commit()

        await set_user_rate(db_path, 456, 250.0, extra_rate=None)

        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                'SELECT extra_rate FROM user_rates WHERE telegram_id = ?',
                (456,),
            ).fetchone()

        assert row is not None
        assert row[0] is None


# ---------------------------------------------------------------------------
# Tests: get_user_rate_history
# ---------------------------------------------------------------------------

class TestGetUserRateHistory:

    @pytest.mark.asyncio
    async def test_get_user_rate_history_found(self, db_path):
        """Снимок за март 2026 найден → возвращает словарь с корректными данными."""
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                'INSERT INTO user_rates_history '
                '(telegram_id, base_rate, extra_rate, month, year) '
                'VALUES (?, ?, ?, ?, ?)',
                (123, 300.0, None, 3, 2026),
            )
            conn.commit()

        result = await get_user_rate_history(db_path, 123, 3, 2026)

        assert result is not None
        assert result["telegram_id"] == 123
        assert result["base_rate"] == 300.0
        assert result["extra_rate"] is None

    @pytest.mark.asyncio
    async def test_get_user_rate_history_not_found(self, db_path):
        """Снимок за указанный период отсутствует → возвращает None."""
        result = await get_user_rate_history(db_path, 123, 3, 2026)

        assert result is None
