"""Фаза 3: cmd_start, /dismiss и повторный апрув читают employees (SQLite), не Sheets."""
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
from config import DEVELOPER_ID, SUPERADMIN_IDS

REG_AT = "2026-07-01T10:00:00+03:00"
AUTH = "app.bot.handlers.auth"
REGULAR_ID = 42


class _ForbiddenSheets:
    """Любое обращение к методу/атрибуту Sheets-клиента — ошибка."""

    def __init__(self):
        self.touched: list[str] = []

    def __getattr__(self, name):
        self.touched.append(name)
        raise AssertionError(f"sheets_client.{name} не должен вызываться")


def _make_message(tg_id=REGULAR_ID) -> MagicMock:
    msg = MagicMock()
    msg.from_user.id = tg_id
    msg.answer = AsyncMock()
    msg.bot.set_my_commands = AsyncMock()
    return msg


def _make_state() -> MagicMock:
    state = MagicMock()
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    state.get_data = AsyncMock(return_value={})
    state.update_data = AsyncMock()
    return state


def _make_callback(data: str) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.from_user.id = 999
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    return cb


def _employee(status: str, **overrides) -> dict:
    emp = {
        "telegram_id": REGULAR_ID, "full_name": "Иванов Иван", "department": "Зал",
        "position": "Официант", "custom_position": None, "role": "user",
        "status": status,
    }
    emp.update(overrides)
    return emp


async def _run_start(*, employee, cached_user, tg_id=REGULAR_ID, sheets=None):
    from app.bot.handlers.auth import AuthStates, cmd_start

    msg, state = _make_message(tg_id), _make_state()
    sheets = _ForbiddenSheets() if sheets is None else sheets
    with (
        patch(f"{AUTH}.sheets_client", sheets),
        patch(f"{AUTH}.get_employee", new=AsyncMock(return_value=employee)),
        patch(f"{AUTH}.get_user", return_value=cached_user),
        patch(f"{AUTH}.delete_user") as mock_delete,
        patch(f"{AUTH}.set_commands_for_role", new=AsyncMock()),
        patch(f"{AUTH}.RolesCacheService.get_user_role", return_value=None),
    ):
        await cmd_start(msg, state)
    return msg, state, mock_delete, AuthStates, sheets


def _answered(msg) -> str:
    return msg.answer.call_args_list[-1].args[0]


class TestCmdStart:

    @pytest.mark.asyncio
    async def test_approved_is_authorized(self):
        msg, state, mock_delete, _, sheets = await _run_start(
            employee=_employee("approved"), cached_user={"full_name": "x"}
        )
        assert "уже авторизован" in _answered(msg)
        state.clear.assert_awaited()
        mock_delete.assert_not_called()
        assert sheets.touched == []

    @pytest.mark.asyncio
    async def test_pending_shows_department_choice(self):
        msg, state, mock_delete, states, sheets = await _run_start(
            employee=_employee("pending"), cached_user=None
        )
        assert "Выбери свой отдел" in _answered(msg)
        state.set_state.assert_awaited_with(states.choosing_department)
        mock_delete.assert_not_called()
        assert sheets.touched == []

    @pytest.mark.asyncio
    async def test_unknown_employee_shows_department_choice(self):
        msg, state, mock_delete, states, sheets = await _run_start(employee=None, cached_user=None)
        assert "Выбери свой отдел" in _answered(msg)
        state.set_state.assert_awaited_with(states.choosing_department)
        assert sheets.touched == []

    @pytest.mark.asyncio
    async def test_dismissed_with_cache_resets(self):
        msg, state, mock_delete, states, sheets = await _run_start(
            employee=_employee("dismissed"), cached_user={"full_name": "x"}
        )
        mock_delete.assert_called_once_with(REGULAR_ID)
        state.clear.assert_awaited()
        assert "Выбери свой отдел" in _answered(msg)
        state.set_state.assert_awaited_with(states.choosing_department)
        assert sheets.touched == []

    @pytest.mark.asyncio
    async def test_dismissed_without_cache_goes_to_registration(self):
        msg, _, mock_delete, _, sheets = await _run_start(
            employee=_employee("dismissed"), cached_user=None
        )
        mock_delete.assert_not_called()
        assert "Выбери свой отдел" in _answered(msg)
        assert sheets.touched == []

    @pytest.mark.asyncio
    async def test_no_employee_with_cache_is_not_reset(self):
        msg, _, mock_delete, _, sheets = await _run_start(
            employee=None, cached_user={"full_name": "x"}
        )
        mock_delete.assert_not_called()
        assert "Выбери свой отдел" in _answered(msg)
        assert sheets.touched == []

    @pytest.mark.asyncio
    async def test_works_with_sheets_client_none(self):
        from app.bot.handlers.auth import cmd_start

        msg, state = _make_message(), _make_state()
        with (
            patch(f"{AUTH}.sheets_client", None),
            patch(f"{AUTH}.get_employee", new=AsyncMock(return_value=_employee("approved"))),
            patch(f"{AUTH}.get_user", return_value=None),
            patch(f"{AUTH}.set_commands_for_role", new=AsyncMock()),
            patch(f"{AUTH}.RolesCacheService.get_user_role", return_value=None),
        ):
            await cmd_start(msg, state)
        assert "уже авторизован" in _answered(msg)

    @pytest.mark.asyncio
    async def test_db_error_reports_failure_and_does_not_reset(self):
        from app.bot.handlers.auth import cmd_start

        msg, state = _make_message(), _make_state()
        sheets = _ForbiddenSheets()
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.get_employee", new=AsyncMock(side_effect=Exception("db locked"))),
            patch(f"{AUTH}.get_user", return_value={"full_name": "x"}),
            patch(f"{AUTH}.delete_user") as mock_delete,
        ):
            await cmd_start(msg, state)
        mock_delete.assert_not_called()
        assert "ошибка при проверке авторизации" in _answered(msg)
        state.set_state.assert_not_awaited()
        assert sheets.touched == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("kind", ["developer", "superadmin"])
    async def test_privileged_roles_unchanged(self, kind):
        from app.bot.handlers.auth import cmd_start

        if kind == "developer":
            tg_id = DEVELOPER_ID
        else:
            others = [i for i in SUPERADMIN_IDS if i != DEVELOPER_ID]
            if not others:
                pytest.skip("нет superadmin-id, отличного от DEVELOPER_ID")
            tg_id = others[0]

        msg, state = _make_message(tg_id), _make_state()
        get_employee_mock = AsyncMock()
        sheets = _ForbiddenSheets()
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.get_employee", new=get_employee_mock),
            patch(f"{AUTH}.set_commands_for_role", new=AsyncMock()),
        ):
            await cmd_start(msg, state)
        assert "Добро пожаловать" in _answered(msg)
        get_employee_mock.assert_not_awaited()
        assert sheets.touched == []

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        strict=True,
        reason="роль берётся только из users-кеша; при его отсутствии employees.role "
        "игнорируется и админ получает команды user",
    )
    async def test_approved_admin_without_users_record_gets_employee_role(self):
        from app.bot.handlers.auth import cmd_start

        msg, state = _make_message(), _make_state()
        set_commands = AsyncMock()
        with (
            patch(f"{AUTH}.sheets_client", _ForbiddenSheets()),
            patch(f"{AUTH}.get_employee",
                  new=AsyncMock(return_value=_employee("approved", role="admin_hall"))),
            patch(f"{AUTH}.get_user", return_value=None),
            patch(f"{AUTH}.set_commands_for_role", new=set_commands),
            patch(f"{AUTH}.RolesCacheService.get_user_role", return_value=None),
        ):
            await cmd_start(msg, state)
        assert set_commands.await_args.args[2] == "admin_hall"


@pytest.fixture()
def employees_db(tmp_path):
    path = str(tmp_path / "phase3_auth.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


async def _register(db_path, tg_id, department="Зал", position="Официант",
                    full_name="Иванов Иван", approve=True):
    await upsert_employee(
        db_path, tg_id, nickname=None, full_name=full_name, department=department,
        position=position, custom_position=None, status="pending", registered_at=REG_AT,
    )
    if approve:
        await approve_employee(db_path, tg_id)


class TestDismissDeptSelected:

    async def _run(self, db_path, dept):
        from app.bot.handlers.auth import dismiss_dept_selected

        cb = _make_callback(f"dismiss_dept:{dept}")
        state = _make_state()
        state.get_data = AsyncMock(return_value={"dismiss_type": "user"})
        sheets = _ForbiddenSheets()
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.DB_PATH", db_path),
            patch(f"{AUTH}.get_user", side_effect=AssertionError("get_user не нужен")),
        ):
            await dismiss_dept_selected(cb, state)
        assert sheets.touched == []
        return cb

    @staticmethod
    def _button_ids(cb) -> list[str]:
        markup = cb.message.edit_text.call_args.kwargs["reply_markup"]
        return [
            row[0].callback_data for row in markup.inline_keyboard
            if row[0].callback_data.startswith("dismiss_select:")
        ]

    @pytest.mark.asyncio
    async def test_lists_only_approved_from_department(self, employees_db):
        await _register(employees_db, 1, "Зал", "Официант", "Один")
        await _register(employees_db, 2, "Зал", "Раннер", "Два", approve=False)   # pending
        await _register(employees_db, 3, "Зал", "Раннер", "Три")
        await dismiss_employee_db(employees_db, 3)                                 # dismissed
        await _register(employees_db, 4, "Бар", "Бармен", "Четыре")

        cb = await self._run(employees_db, "Зал")
        assert self._button_ids(cb) == ["dismiss_select:1"]

    @pytest.mark.asyncio
    async def test_mop_finds_its_employees_without_users_record(self, employees_db):
        await _register(employees_db, 10, "МОП", "Клининг", "Уборщик")
        await _register(employees_db, 11, "МОП", "Котломой", "Котломойщик")

        cb = await self._run(employees_db, "МОП")
        assert sorted(self._button_ids(cb)) == ["dismiss_select:10", "dismiss_select:11"]

    @pytest.mark.asyncio
    async def test_db_error_alerts_and_clears_state(self):
        from app.bot.handlers.auth import dismiss_dept_selected

        cb = _make_callback("dismiss_dept:Зал")
        state = _make_state()
        state.get_data = AsyncMock(return_value={"dismiss_type": "user"})
        sheets = _ForbiddenSheets()
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.get_employees_by_department_db",
                  new=AsyncMock(side_effect=Exception("db locked"))),
        ):
            await dismiss_dept_selected(cb, state)
        assert sheets.touched == []
        cb.answer.assert_awaited_once()
        assert cb.answer.call_args.kwargs.get("show_alert") is True
        state.clear.assert_awaited_once()


class TestDismissSelect:

    @pytest.mark.asyncio
    async def test_reads_employees_not_sheets(self, employees_db):
        from app.bot.handlers.auth import dismiss_select

        await _register(employees_db, 7, "МОП", "Клининг", "Петров Пётр")
        cb = _make_callback("dismiss_select:7")
        state = _make_state()
        sheets = _ForbiddenSheets()
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.DB_PATH", employees_db),
            patch(f"{AUTH}.get_user", return_value=None),
        ):
            await dismiss_select(cb, state)
        assert sheets.touched == []

        state.update_data.assert_awaited_once_with(
            dismiss_target_id=7,
            dismiss_target_name="Петров Пётр",
            dismiss_target_position="Клининг",
            dismiss_target_dept="МОП",
        )
        assert "Петров Пётр" in cb.message.edit_text.call_args.args[0]

    @pytest.mark.asyncio
    async def test_db_error_clears_state(self):
        from app.bot.handlers.auth import dismiss_select

        cb = _make_callback("dismiss_select:7")
        state = _make_state()
        sheets = _ForbiddenSheets()
        with (
            patch(f"{AUTH}.sheets_client", sheets),
            patch(f"{AUTH}.get_user", return_value=None),
            patch(f"{AUTH}.get_employee", new=AsyncMock(side_effect=Exception("db locked"))),
        ):
            await dismiss_select(cb, state)
        assert sheets.touched == []
        state.clear.assert_awaited_once()
        state.update_data.assert_not_awaited()


class TestReapprove:

    @pytest.mark.asyncio
    async def test_reapprove_clears_dismissed_at(self, employees_db):
        await _register(employees_db, 5)
        await dismiss_employee_db(employees_db, 5)
        assert (await get_employee(employees_db, 5))["dismissed_at"] is not None

        await upsert_employee(
            employees_db, 5, nickname=None, full_name="Иванов Иван", department="Зал",
            position="Официант", custom_position=None, status="pending", registered_at=REG_AT,
        )
        await approve_employee(employees_db, 5)

        emp = await get_employee(employees_db, 5)
        assert emp["status"] == "approved"
        assert emp["dismissed_at"] is None
        assert emp["approved_at"] is not None
