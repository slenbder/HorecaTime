import sqlite3
import pytest

from app.db.models import (
    set_user_rate_future,
    get_user_rate_future,
    delete_user_rate_future,
    get_all_future_rates,
)


# ---------------------------------------------------------------------------
# Tests: set_user_rate_future
# ---------------------------------------------------------------------------

class TestSetUserRateFuture:

    @pytest.mark.asyncio
    async def test_set_user_rate_future_create(self, db_path, insert_user):
        """Новая запись создаётся с правильными данными."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 12345)
            conn.commit()

        await set_user_rate_future(db_path, 12345, 400.0, None, 5, 2026)

        result = await get_user_rate_future(db_path, 12345)

        assert result is not None
        assert result["base_rate"] == 400.0
        assert result["extra_rate"] is None
        assert result["effective_month"] == 5
        assert result["effective_year"] == 2026

    @pytest.mark.asyncio
    async def test_set_user_rate_future_update(self, db_path, insert_user):
        """Повторный вызов обновляет запись, не дублирует её."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 12345)
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
    async def test_set_user_rate_future_with_extra(self, db_path, insert_user):
        """Запись с extra_rate сохраняется корректно."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 67890)
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
    async def test_delete_user_rate_future(self, db_path, insert_user):
        """Удаление существующей записи — запись пропадает из БД."""
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 12345)
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
    async def test_get_all_future_rates_multiple(self, db_path, insert_user):
        """Три записи возвращаются полностью и с корректными данными."""
        with sqlite3.connect(db_path) as conn:
            for tid in (111, 222, 333):
                insert_user(conn, tid)
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
