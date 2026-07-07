"""Tests for Phase 1 migration schema (employees, shifts, check_filling, consents, pending_approvals)."""
import sqlite3

import pytest

import app.db.models as models_module
from app.db.models import create_migration_tables, init_database

NEW_TABLES = {"employees", "shifts", "check_filling", "consents", "pending_approvals"}


@pytest.fixture()
def migration_db(tmp_path):
    path = str(tmp_path / "schema_test.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


def _table_names(db_path: str) -> set:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


class TestSchemaCreation:

    def test_create_migration_tables_creates_all_five(self, migration_db):
        assert NEW_TABLES <= _table_names(migration_db)

    def test_create_migration_tables_idempotent(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            create_migration_tables(conn.cursor())  # IF NOT EXISTS — не падает
            conn.commit()
        assert NEW_TABLES <= _table_names(migration_db)

    def test_init_database_creates_new_tables(self, tmp_path, monkeypatch):
        path = str(tmp_path / "init_test.db")
        monkeypatch.setattr(models_module, "DB_PATH", path)

        init_database()

        tables = _table_names(path)
        assert NEW_TABLES <= tables
        # существующие таблицы тоже на месте
        assert {"users", "fsm_storage", "user_rates"} <= tables


class TestShiftsConstraints:

    def test_duplicate_shift_same_date_rejected(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            conn.execute(
                "INSERT INTO shifts (telegram_id, shift_date, hours, source, created_at, updated_at) "
                "VALUES (42, '2026-07-01', 8.0, 'import', '2026-07-07T00:00:00', '2026-07-07T00:00:00')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO shifts (telegram_id, shift_date, hours, source, created_at, updated_at) "
                    "VALUES (42, '2026-07-01', 10.0, 'user', '2026-07-07T00:00:00', '2026-07-07T00:00:00')"
                )

    def test_same_user_different_dates_allowed(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            conn.execute(
                "INSERT INTO shifts (telegram_id, shift_date, hours, source, created_at, updated_at) "
                "VALUES (42, '2026-07-01', 8.0, 'import', 'x', 'x')"
            )
            conn.execute(
                "INSERT INTO shifts (telegram_id, shift_date, hours, source, created_at, updated_at) "
                "VALUES (42, '2026-07-02', 8.0, 'import', 'x', 'x')"
            )
            count = conn.execute("SELECT COUNT(*) FROM shifts").fetchone()[0]
        assert count == 2

    def test_hours_not_null(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO shifts (telegram_id, shift_date, hours, source, created_at, updated_at) "
                    "VALUES (42, '2026-07-01', NULL, 'import', 'x', 'x')"
                )


class TestConsentsConstraints:

    def test_same_type_different_doc_versions_allowed(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            conn.execute(
                "INSERT INTO consents (telegram_id, consent_type, doc_version, given_at) "
                "VALUES (42, 'processing', 'v1', '2026-07-07T00:00:00')"
            )
            conn.execute(
                "INSERT INTO consents (telegram_id, consent_type, doc_version, given_at) "
                "VALUES (42, 'processing', 'v2', '2026-07-07T00:00:00')"
            )
            count = conn.execute("SELECT COUNT(*) FROM consents WHERE telegram_id = 42").fetchone()[0]
        assert count == 2

    def test_duplicate_consent_triple_rejected(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            conn.execute(
                "INSERT INTO consents (telegram_id, consent_type, doc_version, given_at) "
                "VALUES (42, 'crossborder', 'v1', '2026-07-07T00:00:00')"
            )
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute(
                    "INSERT INTO consents (telegram_id, consent_type, doc_version, given_at) "
                    "VALUES (42, 'crossborder', 'v1', '2026-07-08T00:00:00')"
                )


class TestEmployeesConstraints:

    def test_employee_pk_upsert(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            conn.execute(
                "INSERT INTO employees (telegram_id, full_name, department, position, status, registered_at) "
                "VALUES (42, 'Иванов Иван', 'Кухня', 'Горячий цех', 'pending', 'x')"
            )
            conn.execute(
                "INSERT OR REPLACE INTO employees "
                "(telegram_id, full_name, department, position, status, registered_at) "
                "VALUES (42, 'Иванов Иван', 'Кухня', 'Горячий цех', 'approved', 'x')"
            )
            rows = conn.execute("SELECT status FROM employees WHERE telegram_id = 42").fetchall()
        assert rows == [("approved",)]

    def test_role_defaults_to_user(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            conn.execute(
                "INSERT INTO employees (telegram_id, full_name, department, position, status, registered_at) "
                "VALUES (43, 'Петров', 'Бар', 'Бармен', 'pending', 'x')"
            )
            role = conn.execute("SELECT role FROM employees WHERE telegram_id = 43").fetchone()[0]
        assert role == "user"


class TestPendingApprovals:

    def test_autoincrement_id(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            for _ in range(2):
                conn.execute(
                    "INSERT INTO pending_approvals "
                    "(telegram_id, approval_type, shift_date, created_at) "
                    "VALUES (42, 'ah_photos', '2026-07-01', 'x')"
                )
            ids = [r[0] for r in conn.execute("SELECT id FROM pending_approvals ORDER BY id").fetchall()]
        assert ids == [1, 2]
