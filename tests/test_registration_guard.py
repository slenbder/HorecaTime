"""Повторная регистрация не должна понижать approved-сотрудника до pending."""
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import (
    approve_employee,
    create_migration_tables,
    dismiss_employee_db,
    get_employee,
    upsert_employee,
)

AUTH = "app.bot.handlers.auth"
OLD_REG = "2026-07-01T10:00:00+03:00"
NEW_REG = "2026-10-05T12:00:00+03:00"


class _ForbiddenSheets:
    def __init__(self):
        self.touched: list[str] = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(f"sheets_client.{name} не должен вызываться")


@pytest.fixture()
def employees_db(tmp_path):
    path = str(tmp_path / "registration_guard.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


async def _upsert(db_path, *, status="pending", full_name="Иванов Иван", department="Зал",
                  position="Официант", registered_at=OLD_REG, tg_id=42):
    await upsert_employee(
        db_path, tg_id, nickname=None, full_name=full_name, department=department,
        position=position, custom_position=None, status=status, registered_at=registered_at,
    )


class TestUpsertEmployeeGuard:

    @pytest.mark.asyncio
    async def test_approved_plus_pending_is_skipped_entirely(self, employees_db):
        await _upsert(employees_db)
        await approve_employee(employees_db, 42)
        before = await get_employee(employees_db, 42)

        await _upsert(employees_db, full_name="Другой Человек", department="Бар",
                      position="Бармен", registered_at=NEW_REG)

        assert await get_employee(employees_db, 42) == before
        assert before["status"] == "approved"

    @pytest.mark.asyncio
    async def test_approved_plus_pending_logs_warning_without_name(self, employees_db, caplog):
        await _upsert(employees_db)
        await approve_employee(employees_db, 42)

        with caplog.at_level("WARNING", logger="app.db.models"):
            await _upsert(employees_db, full_name="Секретное Имя")

        messages = [r.getMessage() for r in caplog.records]
        assert any("пропущен" in m and "42" in m for m in messages)
        assert not any("Секретное Имя" in m for m in messages)

    @pytest.mark.asyncio
    async def test_dismissed_plus_pending_becomes_pending_with_new_fields(self, employees_db):
        await _upsert(employees_db)
        await approve_employee(employees_db, 42)
        await dismiss_employee_db(employees_db, 42)

        await _upsert(employees_db, full_name="Новое Имя", department="Бар",
                      position="Бармен", registered_at=NEW_REG)

        emp = await get_employee(employees_db, 42)
        assert emp["status"] == "pending"
        assert (emp["full_name"], emp["department"], emp["position"]) == ("Новое Имя", "Бар", "Бармен")
        assert emp["registered_at"] == NEW_REG

    @pytest.mark.asyncio
    async def test_pending_plus_pending_updates_fields(self, employees_db):
        await _upsert(employees_db)
        await _upsert(employees_db, full_name="Новое Имя", department="Кухня",
                      position="Горячий цех", registered_at=NEW_REG)

        emp = await get_employee(employees_db, 42)
        assert emp["status"] == "pending"
        assert (emp["full_name"], emp["department"], emp["position"]) == ("Новое Имя", "Кухня", "Горячий цех")
        assert emp["registered_at"] == NEW_REG

    @pytest.mark.asyncio
    async def test_missing_record_is_created(self, employees_db):
        assert await get_employee(employees_db, 42) is None
        await _upsert(employees_db)
        emp = await get_employee(employees_db, 42)
        assert emp["status"] == "pending"
        assert emp["full_name"] == "Иванов Иван"

    @pytest.mark.asyncio
    async def test_approved_plus_approved_updates(self, employees_db):
        await _upsert(employees_db)
        await approve_employee(employees_db, 42)

        await _upsert(employees_db, status="approved", full_name="Новое Имя",
                      department="Бар", position="Бармен", registered_at=NEW_REG)

        emp = await get_employee(employees_db, 42)
        assert emp["status"] == "approved"
        assert (emp["full_name"], emp["department"], emp["position"]) == ("Новое Имя", "Бар", "Бармен")
        assert emp["registered_at"] == NEW_REG


def _make_message(tg_id=42, text="Иванов Иван") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = tg_id
    msg.from_user.username = "nick"
    msg.answer = AsyncMock()
    msg.bot.send_message = AsyncMock()
    return msg


def _make_state() -> MagicMock:
    state = MagicMock()
    state.get_data = AsyncMock(
        return_value={"department": "Зал", "position": "Официант", "custom_position": None}
    )
    state.clear = AsyncMock()
    return state


class TestProcessFioGuard:

    @pytest.mark.asyncio
    async def test_approved_employee_gets_already_authorized(self):
        from app.bot.handlers.auth import process_fio

        msg, state, sheets = _make_message(), _make_state(), _ForbiddenSheets()
        mock_upsert, mock_admins = AsyncMock(), AsyncMock(return_value=[1])
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.get_employee", new=AsyncMock(return_value={"status": "approved"})),
            patch(f"{AUTH}.upsert_employee", new=mock_upsert),
            patch(f"{AUTH}.get_admins_by_department", new=mock_admins),
        ):
            await process_fio(msg, state)

        mock_upsert.assert_not_called()
        mock_admins.assert_not_called()
        msg.bot.send_message.assert_not_called()
        state.clear.assert_awaited_once()
        assert "уже авторизован" in msg.answer.call_args.args[0]
        assert sheets.touched == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("employee", [None, {"status": "pending"}, {"status": "dismissed"}])
    async def test_other_statuses_go_through_registration(self, employee):
        from app.bot.handlers.auth import process_fio

        msg, state = _make_message(), _make_state()
        sheets = MagicMock()
        sheets.add_or_update_pending_user.return_value = 7
        mock_upsert = AsyncMock()
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.get_employee", new=AsyncMock(return_value=employee)),
            patch(f"{AUTH}.upsert_employee", new=mock_upsert),
            patch(f"{AUTH}.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            await process_fio(msg, state)

        mock_upsert.assert_awaited_once()
        assert mock_upsert.await_args.kwargs["status"] == "pending"
        sheets.add_or_update_pending_user.assert_called_once()
        state.clear.assert_awaited_once()
        assert "Заявка на доступ отправлена" in msg.answer.call_args.args[0]

    @pytest.mark.asyncio
    async def test_get_employee_error_reports_and_keeps_state(self):
        from app.bot.handlers.auth import process_fio

        msg, state, sheets = _make_message(), _make_state(), _ForbiddenSheets()
        mock_upsert = AsyncMock()
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.get_employee", new=AsyncMock(side_effect=Exception("db locked"))),
            patch(f"{AUTH}.upsert_employee", new=mock_upsert),
        ):
            await process_fio(msg, state)

        mock_upsert.assert_not_called()
        state.clear.assert_not_called()
        assert "Произошла ошибка" in msg.answer.call_args.args[0]
        assert sheets.touched == []
