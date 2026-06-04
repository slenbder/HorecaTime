"""Tests for delete_user (cascade) and get_admins_by_department."""
import sqlite3

import pytest

import app.db.models as models_module
from app.db.models import delete_user, get_user, get_admins_by_department


# ---------------------------------------------------------------------------
# Tests: delete_user — cascade across 4 tables
# ---------------------------------------------------------------------------

class TestDeleteUser:

    def test_delete_user_removes_from_users(self, db_path, insert_user, monkeypatch):
        monkeypatch.setattr(models_module, "DB_PATH", db_path)
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 42)
            conn.commit()

        delete_user(42)

        assert get_user(42) is None

    def test_delete_user_removes_rates(self, db_path, insert_user, monkeypatch):
        monkeypatch.setattr(models_module, "DB_PATH", db_path)
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 42)
            conn.execute(
                "INSERT INTO user_rates (telegram_id, base_rate, extra_rate, updated_at) "
                "VALUES (42, 200.0, NULL, '2026-01-01T00:00:00')"
            )
            conn.commit()

        delete_user(42)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM user_rates WHERE telegram_id = 42"
            ).fetchall()
        assert rows == []

    def test_delete_user_removes_future_rates(self, db_path, insert_user, monkeypatch):
        monkeypatch.setattr(models_module, "DB_PATH", db_path)
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 42)
            conn.execute(
                "INSERT INTO user_rates_future "
                "(telegram_id, base_rate, extra_rate, effective_month, effective_year, created_at) "
                "VALUES (42, 200.0, NULL, 7, 2026, '2026-01-01T00:00:00')"
            )
            conn.commit()

        delete_user(42)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM user_rates_future WHERE telegram_id = 42"
            ).fetchall()
        assert rows == []

    def test_delete_user_removes_rates_history(self, db_path, insert_user, monkeypatch):
        monkeypatch.setattr(models_module, "DB_PATH", db_path)
        with sqlite3.connect(db_path) as conn:
            insert_user(conn, 42)
            conn.execute(
                "INSERT INTO user_rates_history "
                "(telegram_id, base_rate, extra_rate, month, year) "
                "VALUES (42, 200.0, NULL, 5, 2026)"
            )
            conn.commit()

        delete_user(42)

        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT * FROM user_rates_history WHERE telegram_id = 42"
            ).fetchall()
        assert rows == []

    def test_delete_user_nonexistent_no_error(self, db_path, monkeypatch):
        monkeypatch.setattr(models_module, "DB_PATH", db_path)
        delete_user(9999999)  # must not raise


# ---------------------------------------------------------------------------
# Tests: get_admins_by_department
# ---------------------------------------------------------------------------

def _insert_admin(conn: sqlite3.Connection, telegram_id: int, role: str, department: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO users (telegram_id, full_name, role, department, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (telegram_id, f"Admin {telegram_id}", role, department, "2026-01-01T00:00:00"),
    )


class TestGetAdminsByDepartment:

    @pytest.mark.asyncio
    async def test_get_admins_returns_only_dept_admins(self, db_path, monkeypatch):
        monkeypatch.setattr(models_module, "SUPERADMIN_IDS", [])
        with sqlite3.connect(db_path) as conn:
            _insert_admin(conn, 100, "admin_hall", "Зал")
            _insert_admin(conn, 200, "admin_bar", "Бар")
            conn.commit()

        result = await get_admins_by_department(db_path, "Зал")

        assert 100 in result
        assert 200 not in result

    @pytest.mark.asyncio
    async def test_get_admins_empty_dept(self, db_path, monkeypatch):
        monkeypatch.setattr(models_module, "SUPERADMIN_IDS", [])

        result = await get_admins_by_department(db_path, "Зал")

        assert result == []
