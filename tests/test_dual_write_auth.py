"""Dual-write тесты Фазы 2a: SQLite первым, Sheets — зеркало.

Ошибка SQLite → операция отклонена, Sheets не вызывается.
Ошибка Sheets → операция успешна, разработчик уведомлён.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import DEVELOPER_ID


def _dev_notified(send_message_mock) -> bool:
    """Было ли уведомление разработчику (позиционный первый аргумент DEVELOPER_ID)."""
    return any(
        call.args and call.args[0] == DEVELOPER_ID
        for call in send_message_mock.call_args_list
    )


def _make_message(text="Иванов Иван", tg_id=42, username="nick") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = tg_id
    msg.from_user.username = username
    msg.answer = AsyncMock()
    msg.bot.send_message = AsyncMock()
    return msg


def _make_state(data: dict) -> MagicMock:
    state = MagicMock()
    state.get_data = AsyncMock(return_value=data)
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    return state


def _make_callback(data: str, message_text: str = "") -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.message.text = message_text
    cb.from_user.id = 999
    cb.from_user.full_name = "Админ"
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.bot.send_message = AsyncMock()
    cb.bot.set_my_commands = AsyncMock()
    return cb


_FIO_STATE = {"department": "Зал", "position": "Официант", "custom_position": None}


# ---------------------------------------------------------------------------
# Регистрация (process_fio)
# ---------------------------------------------------------------------------

class TestRegistrationDualWrite:

    @pytest.mark.asyncio
    async def test_sheets_failure_registration_succeeds(self):
        """Sheets упал → заявка в SQLite сохранена, пользователь получил успех, дев уведомлён."""
        from app.bot.handlers.auth import process_fio

        msg = _make_message()
        state = _make_state(_FIO_STATE)

        with (
            patch("app.bot.handlers.auth.upsert_employee", new=AsyncMock()) as mock_upsert,
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            mock_sc.add_or_update_pending_user.side_effect = Exception("Sheets down")
            await process_fio(msg, state)

        mock_upsert.assert_awaited_once()
        assert mock_upsert.await_args.kwargs["status"] == "pending"
        # Пользователю — успех, а не ошибка
        final_answer = msg.answer.call_args_list[-1].args[0]
        assert "Заявка на доступ отправлена" in final_answer
        assert _dev_notified(msg.bot.send_message)

    @pytest.mark.asyncio
    async def test_sqlite_failure_sheets_not_called(self):
        """SQLite упал → отказ операции, Sheets НЕ вызывался, state не сброшен."""
        from app.bot.handlers.auth import process_fio

        msg = _make_message()
        state = _make_state(_FIO_STATE)

        with (
            patch("app.bot.handlers.auth.upsert_employee",
                  new=AsyncMock(side_effect=Exception("db locked"))),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            await process_fio(msg, state)

        mock_sc.add_or_update_pending_user.assert_not_called()
        state.clear.assert_not_called()   # пользователь может отправить ФИО повторно
        error_answer = msg.answer.call_args_list[-1].args[0]
        assert "Не удалось сохранить заявку" in error_answer


# ---------------------------------------------------------------------------
# Апрув (process_approve)
# ---------------------------------------------------------------------------

_USER_DATA = {
    "fio": "Иванов Иван",
    "department": "Зал",
    "position": "Официант",
    "custom_position": "",
    "mention": "@nick",
}


class TestApproveDualWrite:

    @pytest.mark.asyncio
    async def test_sheets_failure_approve_succeeds(self):
        """Зеркало упало → апрув в SQLite прошёл, админ получил успех, дев уведомлён."""
        from app.bot.handlers.auth import process_approve

        cb = _make_callback("approve_42_5", message_text="Новая заявка")

        with (
            patch("app.bot.handlers.auth.sheets_client", new=MagicMock()),
            patch("app.bot.handlers.auth._fetch_user_info", return_value=_USER_DATA),
            patch("app.bot.handlers.auth.approve_employee", new=AsyncMock()) as mock_approve,
            patch("app.bot.handlers.auth.set_employee_role", new=AsyncMock()) as mock_role,
            patch("app.bot.handlers.auth._register_user_in_sheets",
                  new=AsyncMock(side_effect=Exception("Sheets down"))),
            patch("app.bot.handlers.auth._setup_user_access", new=AsyncMock()) as mock_access,
            patch("app.bot.handlers.auth._notify_approval", new=AsyncMock()),
        ):
            await process_approve(cb, MagicMock())

        mock_approve.assert_awaited_once()
        assert mock_approve.await_args.args[1] == 42
        mock_role.assert_awaited_once()
        mock_access.assert_awaited_once()          # доступ настроен несмотря на Sheets
        cb.answer.assert_called_with("Пользователь одобрен!")
        assert _dev_notified(cb.bot.send_message)

    @pytest.mark.asyncio
    async def test_sqlite_failure_sheets_not_called(self):
        """SQLite упал → апрув отклонён, зеркало НЕ вызывалось."""
        from app.bot.handlers.auth import process_approve

        cb = _make_callback("approve_42_5", message_text="Новая заявка")

        with (
            patch("app.bot.handlers.auth.sheets_client", new=MagicMock()),
            patch("app.bot.handlers.auth._fetch_user_info", return_value=_USER_DATA),
            patch("app.bot.handlers.auth.approve_employee",
                  new=AsyncMock(side_effect=Exception("db locked"))),
            patch("app.bot.handlers.auth._register_user_in_sheets", new=AsyncMock()) as mock_reg,
            patch("app.bot.handlers.auth._setup_user_access", new=AsyncMock()) as mock_access,
        ):
            await process_approve(cb, MagicMock())

        mock_reg.assert_not_awaited()
        mock_access.assert_not_awaited()
        cb.answer.assert_called_with(
            "❌ Ошибка сохранения одобрения. Попробуйте ещё раз.", show_alert=True
        )


# ---------------------------------------------------------------------------
# Увольнение (dismiss_confirm_handler)
# ---------------------------------------------------------------------------

class TestDismissDualWrite:

    @pytest.mark.asyncio
    async def test_sheets_failure_dismiss_succeeds(self):
        """Зеркало упало → увольнение прошло: employees помечен, users удалён, дев уведомлён."""
        from app.bot.handlers.auth import dismiss_confirm_handler

        cb = _make_callback("dismiss_confirm:42")
        state = _make_state({"dismiss_target_name": "Иванов Иван"})

        with (
            patch("app.bot.handlers.auth.dismiss_employee_db",
                  new=AsyncMock(return_value=True)) as mock_dismiss,
            patch("app.bot.handlers.auth.get_user", return_value=None),
            patch("app.bot.handlers.auth.delete_user") as mock_delete,
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
            patch("app.bot.handlers.auth.aiosqlite.connect",
                  side_effect=Exception("fsm cleanup skipped")),
        ):
            mock_sc.dismiss_employee.side_effect = Exception("Sheets down")
            await dismiss_confirm_handler(cb, state)

        mock_dismiss.assert_awaited_once()
        assert mock_dismiss.await_args.args[1] == 42
        mock_delete.assert_called_once_with(42)     # кеш users чистится как раньше
        assert _dev_notified(cb.bot.send_message)
        edit_text = cb.message.edit_text.call_args.args[0]
        assert "уволен" in edit_text

    @pytest.mark.asyncio
    async def test_sqlite_failure_nothing_else_touched(self):
        """SQLite упал → отказ: ни Sheets, ни delete_user не вызваны."""
        from app.bot.handlers.auth import dismiss_confirm_handler

        cb = _make_callback("dismiss_confirm:42")
        state = _make_state({"dismiss_target_name": "Иванов Иван"})

        with (
            patch("app.bot.handlers.auth.dismiss_employee_db",
                  new=AsyncMock(side_effect=Exception("db locked"))),
            patch("app.bot.handlers.auth.get_user", return_value=None),
            patch("app.bot.handlers.auth.delete_user") as mock_delete,
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            await dismiss_confirm_handler(cb, state)

        mock_sc.dismiss_employee.assert_not_called()
        mock_delete.assert_not_called()
        cb.message.edit_text.assert_not_called()
        cb.answer.assert_called_with(
            "❌ Ошибка БД, увольнение не выполнено. Попробуйте ещё раз.", show_alert=True
        )
