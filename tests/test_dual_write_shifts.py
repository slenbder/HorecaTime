"""Dual-write тесты Фазы 2b: смены и чеки — SQLite первым, Sheets зеркалом.

Ошибка Sheets → операция успешна, данные в SQLite, разработчик уведомлён.
Ошибка SQLite → отказ операции, Sheets не вызывается, state сохраняется.
ValueError Sheets (не в листе месяца) → отказ как раньше + откат записи в БД.
"""
import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.models import create_migration_tables, get_shift
from config import DEVELOPER_ID


@pytest.fixture()
def shifts_db(tmp_path):
    path = str(tmp_path / "dual_write_test.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


def _make_message(text: str = "", tg_id: int = 12345, username: str = "user") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = tg_id
    msg.from_user.username = username
    msg.answer = AsyncMock()
    msg.bot.send_message = AsyncMock()
    return msg


def _make_state(**data) -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value=data)
    state.clear = AsyncMock()
    return state


def _dev_notified(send_message_mock) -> bool:
    return any(
        c.args and c.args[0] == DEVELOPER_ID
        for c in send_message_mock.call_args_list
    )


def _answers(msg) -> str:
    return " ".join(str(c) for c in msg.answer.call_args_list)


_BAR_STATE = dict(day=15, month=5, year=2026, h=8.0, ah=3.0, start=16.0, end=0.0)


# ---------------------------------------------------------------------------
# Бармен (_write_and_finish_bar) — одиночная смена
# ---------------------------------------------------------------------------

class TestBarDualWrite:

    @pytest.mark.asyncio
    async def test_sheets_failure_shift_persisted_in_sqlite(self, shifts_db):
        """Sheets упал → смена в SQLite, пользователю ✅, дев уведомлён."""
        from app.bot.handlers.userhours import _write_and_finish_bar

        message = _make_message()
        state = _make_state(**_BAR_STATE)

        with (
            patch("app.bot.handlers.userhours.DB_PATH", shifts_db),
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            mock_sc.write_shift.side_effect = Exception("Sheets down")
            await _write_and_finish_bar(message, state, "Бармен")

        rec = await get_shift(shifts_db, 12345, "2026-05-15")
        assert rec is not None
        assert (rec["hours"], rec["extra_hours"], rec["source"]) == (8.0, 3.0, "user")
        assert "✅ Смена" in _answers(message)
        assert _dev_notified(message.bot.send_message)

    @pytest.mark.asyncio
    async def test_sqlite_failure_sheets_not_called(self):
        """SQLite упал → отказ, Sheets не вызывался, state сохранён для повтора."""
        from app.bot.handlers.userhours import _write_and_finish_bar

        message = _make_message()
        state = _make_state(**_BAR_STATE)

        with (
            patch("app.bot.handlers.userhours.upsert_shift",
                  new=AsyncMock(side_effect=Exception("db locked"))),
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
        ):
            await _write_and_finish_bar(message, state, "Бармен")

        mock_sc.write_shift.assert_not_called()
        state.clear.assert_not_called()
        assert "❌ Ошибка записи" in _answers(message)

    @pytest.mark.asyncio
    async def test_roster_validation_rolls_back_sqlite(self, shifts_db):
        """Sheets: 'не найден в листе' → отказ как раньше, запись в БД откачена."""
        from app.bot.handlers.userhours import _write_and_finish_bar

        message = _make_message()
        state = _make_state(**_BAR_STATE)

        with (
            patch("app.bot.handlers.userhours.DB_PATH", shifts_db),
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            mock_sc.write_shift.side_effect = ValueError(
                "Пользователь 12345 не найден в листе 'Май 2026'"
            )
            await _write_and_finish_bar(message, state, "Бармен")

        assert await get_shift(shifts_db, 12345, "2026-05-15") is None
        assert "не числитесь в графике" in _answers(message)
        state.clear.assert_called_once()


# ---------------------------------------------------------------------------
# Раннер (_write_and_finish) — полные часы в БД, is_weekend только в зеркало
# ---------------------------------------------------------------------------

class TestRunnerDualWrite:

    @pytest.mark.asyncio
    async def test_full_hours_to_sqlite_weekend_only_to_mirror(self):
        from app.bot.handlers.userhours import _write_and_finish

        message = _make_message()
        state = _make_state(day=16, month=5, year=2026, h=9.0, ah=1.0,
                            is_weekend=True, comment="", start=10.0, end=19.0)

        with (
            patch("app.bot.handlers.userhours.upsert_shift",
                  new=AsyncMock(return_value=None)) as mock_upsert,
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Раннер"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            mock_sc.write_shift.return_value = ""
            await _write_and_finish(message, state)

        # SQLite: полные часы дня, без флага выходного (выводим из shift_date)
        args = mock_upsert.await_args.args
        assert args[1:5] == (12345, "2026-05-16", 9.0, 1.0)
        # Зеркало: is_weekend уходит в Sheets для накопителей AM/AN
        assert mock_sc.write_shift.call_args.kwargs["is_weekend"] is True


# ---------------------------------------------------------------------------
# Мультистрочный ввод (_process_simple_h_shifts) — bulk-транзакция
# ---------------------------------------------------------------------------

class TestSimpleHBulkDualWrite:

    @pytest.mark.asyncio
    async def test_partial_mirror_failure_all_persisted_dev_gets_dates(self, shifts_db):
        """Sheets упал на 2-й строке → обе смены в SQLite, юзеру ✅, дев получил дату."""
        from app.bot.handlers.userhours import _process_simple_h_shifts

        message = _make_message(text="01.05 10:00-20:00\n02.05 10:00-20:00")
        state = _make_state(position="Клининг")

        with (
            patch("app.bot.handlers.userhours.DB_PATH", shifts_db),
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            mock_sc.write_shift.side_effect = ["", Exception("Sheets down")]
            await _process_simple_h_shifts(message, state, "Клининг")

        assert await get_shift(shifts_db, 12345, "2026-05-01") is not None
        assert await get_shift(shifts_db, 12345, "2026-05-02") is not None
        assert "✅ Записано смен: 2" in _answers(message)

        dev_calls = [
            c for c in message.bot.send_message.call_args_list
            if c.args and c.args[0] == DEVELOPER_ID
        ]
        assert dev_calls and "02.05" in str(dev_calls[0])

    @pytest.mark.asyncio
    async def test_sqlite_bulk_failure_sheets_not_called(self):
        """Bulk-транзакция упала → Sheets не вызывался, отказ без сброса state."""
        from app.bot.handlers.userhours import _process_simple_h_shifts

        message = _make_message(text="01.05 10:00-20:00")
        state = _make_state(position="Клининг")

        with (
            patch("app.bot.handlers.userhours.upsert_shifts_bulk",
                  new=AsyncMock(side_effect=Exception("db locked"))),
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            await _process_simple_h_shifts(message, state, "Клининг")

        mock_sc.write_shift.assert_not_called()
        state.clear.assert_not_called()
        assert "❌ Ошибка записи" in _answers(message)

    @pytest.mark.asyncio
    async def test_roster_validation_rolls_back_whole_bulk(self, shifts_db):
        """'не найден в листе' на 1-й строке → обе строки транзакции откачены."""
        from app.bot.handlers.userhours import _process_simple_h_shifts

        message = _make_message(text="01.05 10:00-20:00\n02.05 10:00-20:00")
        state = _make_state(position="Клининг")

        with (
            patch("app.bot.handlers.userhours.DB_PATH", shifts_db),
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            mock_sc.write_shift.side_effect = ValueError(
                "Пользователь 12345 не найден в листе 'Май 2026'"
            )
            await _process_simple_h_shifts(message, state, "Клининг")

        assert await get_shift(shifts_db, 12345, "2026-05-01") is None
        assert await get_shift(shifts_db, 12345, "2026-05-02") is None
        assert "не числитесь в графике" in _answers(message)


# ---------------------------------------------------------------------------
# Официант без фото (_write_waiter_no_photo)
# ---------------------------------------------------------------------------

class TestWaiterNoPhotoDualWrite:

    @pytest.mark.asyncio
    async def test_sheets_failure_succeeds(self, shifts_db):
        from app.bot.handlers.userhours import _write_waiter_no_photo

        message = _make_message()
        state = _make_state()
        result = {"day": 10, "month": 5, "year": 2026, "h": 8.0, "start": 10.0, "end": 18.0}

        with (
            patch("app.bot.handlers.userhours.DB_PATH", shifts_db),
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Официант"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
        ):
            mock_sc.write_shift.side_effect = Exception("Sheets down")
            await _write_waiter_no_photo(message, state, 12345, result)

        rec = await get_shift(shifts_db, 12345, "2026-05-10")
        assert rec["hours"] == 8.0
        assert "✅ Смена" in _answers(message)
        assert _dev_notified(message.bot.send_message)


# ---------------------------------------------------------------------------
# Апрув доп. часов (approve_ah_callback) — source='admin_approve'
# ---------------------------------------------------------------------------

class TestApproveAhDualWrite:

    @pytest.mark.asyncio
    async def test_sqlite_failure_buttons_stay(self):
        """SQLite упал → '❌ апрув не выполнен', зеркало не вызывалось, кнопки не гашены."""
        from app.bot.handlers.auth import approve_ah_callback

        cb = MagicMock()
        cb.data = "approve_ah:12345:03.05.26:10.0:3:2"
        cb.message.text = "Фотоотчёт"
        cb.from_user.id = 999
        cb.answer = AsyncMock()
        cb.message.edit_text = AsyncMock()
        cb.bot.send_message = AsyncMock()

        with (
            patch("app.bot.handlers.auth.upsert_shift",
                  new=AsyncMock(side_effect=Exception("db locked"))),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            await approve_ah_callback(cb)

        mock_sc.write_shift.assert_not_called()
        cb.message.edit_text.assert_not_called()   # кнопки остались — повтор возможен
        cb.answer.assert_called_with("❌ Ошибка записи, апрув не выполнен.", show_alert=True)

    @pytest.mark.asyncio
    async def test_sheets_failure_approve_succeeds(self, shifts_db):
        """Sheets упал → апрув успешен, H+AH в SQLite (source='admin_approve'), дев уведомлён."""
        from app.bot.handlers.auth import approve_ah_callback

        cb = MagicMock()
        cb.data = "approve_ah:12345:03.05.26:10.0:3:2"
        cb.message.text = "Фотоотчёт"
        cb.from_user.id = 999
        cb.answer = AsyncMock()
        cb.message.edit_text = AsyncMock()
        cb.bot.send_message = AsyncMock()

        with (
            patch("app.bot.handlers.auth.DB_PATH", shifts_db),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_shift.side_effect = Exception("Sheets down")
            await approve_ah_callback(cb)

        rec = await get_shift(shifts_db, 12345, "2026-05-03")
        assert rec["hours"] == 10.0
        assert rec["extra_hours"] == 1.0   # 2 фото × 0.5
        assert rec["source"] == "admin_approve"
        cb.message.edit_text.assert_called_once()  # апрув завершён
        assert _dev_notified(cb.bot.send_message)
