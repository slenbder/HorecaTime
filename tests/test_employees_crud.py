"""Tests for the employees CRUD layer (Phase 2a: SQLite = source of truth)."""
import sqlite3

import pytest

from app.db.models import (
    create_migration_tables,
    upsert_employee,
    approve_employee,
    dismiss_employee_db,
    get_employee,
    get_employees_by_department_db,
    set_employee_role,
)

REG_AT = "2026-07-01T10:00:00+03:00"


@pytest.fixture()
def employees_db(tmp_path):
    path = str(tmp_path / "employees_test.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


async def _register(db_path, tg_id=42, **overrides):
    params = {
        "nickname": "@nick",
        "full_name": "Иванов Иван",
        "department": "Кухня",
        "position": "Горячий цех",
        "custom_position": None,
        "status": "pending",
        "registered_at": REG_AT,
    }
    params.update(overrides)
    await upsert_employee(db_path, tg_id, **params)


class TestUpsertEmployee:

    @pytest.mark.asyncio
    async def test_insert_creates_pending_with_default_role(self, employees_db):
        await _register(employees_db)

        emp = await get_employee(employees_db, 42)
        assert emp["status"] == "pending"
        assert emp["role"] == "user"
        assert emp["full_name"] == "Иванов Иван"
        assert emp["approved_at"] is None

    @pytest.mark.asyncio
    async def test_upsert_preserves_role_and_approved_at(self, employees_db):
        await _register(employees_db)
        await approve_employee(employees_db, 42)
        await set_employee_role(employees_db, 42, "admin_kitchen")

        # Повторная регистрация (например, смена отдела)
        await _register(employees_db, department="Бар", position="Бармен")

        emp = await get_employee(employees_db, 42)
        assert emp["role"] == "admin_kitchen"       # сохранена
        assert emp["approved_at"] is not None       # сохранена
        assert emp["status"] == "pending"           # пришедшее поле обновлено
        assert emp["department"] == "Бар"

    @pytest.mark.asyncio
    async def test_get_employee_missing_returns_none(self, employees_db):
        assert await get_employee(employees_db, 999) is None


class TestApproveEmployee:

    @pytest.mark.asyncio
    async def test_approve_sets_status_and_timestamp(self, employees_db):
        await _register(employees_db)

        await approve_employee(employees_db, 42)

        emp = await get_employee(employees_db, 42)
        assert emp["status"] == "approved"
        assert emp["approved_at"] is not None

    @pytest.mark.asyncio
    async def test_approve_missing_employee_raises(self, employees_db):
        with pytest.raises(ValueError):
            await approve_employee(employees_db, 999)


class TestDismissEmployee:

    @pytest.mark.asyncio
    async def test_dismiss_keeps_row_in_db(self, employees_db):
        await _register(employees_db)
        await approve_employee(employees_db, 42)

        result = await dismiss_employee_db(employees_db, 42)

        assert result is True
        emp = await get_employee(employees_db, 42)
        assert emp is not None                      # строка НЕ удалена
        assert emp["status"] == "dismissed"
        assert emp["dismissed_at"] is not None
        assert emp["full_name"] == "Иванов Иван"    # история сохранена

    @pytest.mark.asyncio
    async def test_dismiss_missing_employee_returns_false(self, employees_db):
        assert await dismiss_employee_db(employees_db, 999) is False


class TestGetEmployeesByDepartment:

    @pytest.mark.asyncio
    async def test_filters_by_department_and_status(self, employees_db):
        await _register(employees_db, tg_id=1, full_name="Аня")
        await _register(employees_db, tg_id=2, full_name="Боря")
        await _register(employees_db, tg_id=3, full_name="Вера", department="Бар", position="Бармен")
        await approve_employee(employees_db, 1)
        await approve_employee(employees_db, 3)
        # 2 остаётся pending

        kitchen = await get_employees_by_department_db(employees_db, "Кухня")
        assert [e["telegram_id"] for e in kitchen] == [1]

        pending_kitchen = await get_employees_by_department_db(
            employees_db, "Кухня", status="pending"
        )
        assert [e["telegram_id"] for e in pending_kitchen] == [2]

    @pytest.mark.asyncio
    async def test_dismissed_excluded_from_approved(self, employees_db):
        await _register(employees_db, tg_id=1)
        await approve_employee(employees_db, 1)
        await dismiss_employee_db(employees_db, 1)

        assert await get_employees_by_department_db(employees_db, "Кухня") == []


class TestSetEmployeeRole:

    @pytest.mark.asyncio
    async def test_updates_role(self, employees_db):
        await _register(employees_db)
        await set_employee_role(employees_db, 42, "admin_kitchen")
        emp = await get_employee(employees_db, 42)
        assert emp["role"] == "admin_kitchen"
