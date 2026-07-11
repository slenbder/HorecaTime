"""Tests for shifts/check_filling CRUD (Phase 2b) and to_iso_date."""
import asyncio
import sqlite3

import pytest

from app.db.models import (
    create_migration_tables,
    upsert_shift,
    upsert_shifts_bulk,
    get_shift,
    delete_shift,
    add_check_filling,
)
from app.services.timeparsing import to_iso_date


@pytest.fixture()
def shifts_db(tmp_path):
    path = str(tmp_path / "shifts_test.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


def _bulk_row(tg_id=42, date="2026-07-01", hours=8.0, ah=0.0, source="user"):
    return {"telegram_id": tg_id, "shift_date": date, "hours": hours,
            "extra_hours": ah, "source": source}


class TestUpsertShift:

    @pytest.mark.asyncio
    async def test_create_returns_none_and_persists(self, shifts_db):
        old = await upsert_shift(shifts_db, 42, "2026-07-01", 8.0, 1.5, "user")

        assert old is None
        rec = await get_shift(shifts_db, 42, "2026-07-01")
        assert rec["hours"] == 8.0
        assert rec["extra_hours"] == 1.5
        assert rec["source"] == "user"

    @pytest.mark.asyncio
    async def test_overwrite_returns_old_record(self, shifts_db):
        await upsert_shift(shifts_db, 42, "2026-07-01", 8.0, 0.0, "user")

        old = await upsert_shift(shifts_db, 42, "2026-07-01", 10.0, 2.0, "admin_approve")

        assert old["hours"] == 8.0
        assert old["source"] == "user"
        rec = await get_shift(shifts_db, 42, "2026-07-01")
        assert (rec["hours"], rec["extra_hours"], rec["source"]) == (10.0, 2.0, "admin_approve")

    @pytest.mark.asyncio
    async def test_delete_shift_removes_row(self, shifts_db):
        await upsert_shift(shifts_db, 42, "2026-07-01", 8.0, 0.0, "user")
        await delete_shift(shifts_db, 42, "2026-07-01")
        assert await get_shift(shifts_db, 42, "2026-07-01") is None


class TestUpsertShiftsBulk:

    @pytest.mark.asyncio
    async def test_returns_old_records_in_order(self, shifts_db):
        await upsert_shift(shifts_db, 42, "2026-07-02", 6.0, 0.0, "user")

        olds = await upsert_shifts_bulk(shifts_db, [
            _bulk_row(date="2026-07-01"),
            _bulk_row(date="2026-07-02", hours=9.0),
        ])

        assert olds[0] is None
        assert olds[1]["hours"] == 6.0

    @pytest.mark.asyncio
    async def test_atomic_error_on_third_row_writes_nothing(self, shifts_db):
        rows = [
            _bulk_row(date="2026-07-01"),
            _bulk_row(date="2026-07-02"),
            _bulk_row(date="2026-07-03", hours=None),  # NOT NULL → IntegrityError
            _bulk_row(date="2026-07-04"),
            _bulk_row(date="2026-07-05"),
        ]

        with pytest.raises(sqlite3.IntegrityError):
            await upsert_shifts_bulk(shifts_db, rows)

        with sqlite3.connect(shifts_db) as conn:
            count = conn.execute("SELECT COUNT(*) FROM shifts").fetchone()[0]
        assert count == 0

    @pytest.mark.asyncio
    async def test_rollback_does_not_touch_existing_rows(self, shifts_db):
        await upsert_shift(shifts_db, 42, "2026-07-01", 6.0, 0.0, "user")

        with pytest.raises(sqlite3.IntegrityError):
            await upsert_shifts_bulk(shifts_db, [
                _bulk_row(date="2026-07-01", hours=9.0),
                _bulk_row(date="2026-07-02", hours=None),
            ])

        rec = await get_shift(shifts_db, 42, "2026-07-01")
        assert rec["hours"] == 6.0  # обновление первой строки откатилось


class TestAddCheckFilling:

    @pytest.mark.asyncio
    async def test_increments_same_date(self, shifts_db):
        assert await add_check_filling(shifts_db, "2026-07-01", 3) == 3
        assert await add_check_filling(shifts_db, "2026-07-01", 2) == 5

    @pytest.mark.asyncio
    async def test_different_dates_independent(self, shifts_db):
        await add_check_filling(shifts_db, "2026-07-01", 3)
        assert await add_check_filling(shifts_db, "2026-07-02", 4) == 4

    @pytest.mark.asyncio
    async def test_concurrent_increments_not_lost(self, shifts_db):
        """Фикс гонки read-modify-write: параллельные инкременты не теряются."""
        await asyncio.gather(*[
            add_check_filling(shifts_db, "2026-07-01", 1) for _ in range(10)
        ])

        with sqlite3.connect(shifts_db) as conn:
            total = conn.execute(
                "SELECT count FROM check_filling WHERE fill_date = '2026-07-01'"
            ).fetchone()[0]
        assert total == 10


class TestToIsoDate:

    @pytest.mark.parametrize("day, month, year, expected", [
        (1, 7, 2026, "2026-07-01"),
        (31, 12, 2025, "2025-12-31"),
        (15, 1, 2026, "2026-01-15"),
        (29, 2, 2024, "2024-02-29"),   # високосный год
    ])
    def test_valid_dates(self, day, month, year, expected):
        assert to_iso_date(day, month, year) == expected

    @pytest.mark.parametrize("day, month, year", [
        (31, 4, 2026),   # в апреле 30 дней
        (29, 2, 2026),   # не високосный
        (0, 7, 2026),
        (32, 7, 2026),
        (1, 13, 2026),
    ])
    def test_invalid_dates_raise(self, day, month, year):
        with pytest.raises(ValueError):
            to_iso_date(day, month, year)
