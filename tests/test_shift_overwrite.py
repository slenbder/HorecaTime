"""Тесты уведомления при перезаписи смены."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_message(tg_id: int = 12345, username: str = "testuser") -> MagicMock:
    msg = MagicMock()
    msg.from_user.id = tg_id
    msg.from_user.username = username
    msg.answer = AsyncMock()
    msg.bot.send_message = AsyncMock()
    return msg


def _make_state(day: int, month: int, year: int, h: float, ah: float = 0.0) -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={
        "day": day, "month": month, "year": year,
        "h": h, "ah": ah, "start": 16.0, "end": 0.0,
    })
    state.clear = AsyncMock()
    return state


# ---------------------------------------------------------------------------
# Тест 1: перезапись с другим значением → уведомление отправлено
# ---------------------------------------------------------------------------


def _old_shift(h: float, ah: float = 0.0) -> dict:
    """Старая запись shifts из SQLite (возврат upsert_shift)."""
    return {"telegram_id": 12345, "shift_date": "2026-05-15", "hours": h,
            "extra_hours": ah, "source": "user",
            "created_at": "x", "updated_at": "x"}

class TestBarShiftOverwrite:

    @pytest.mark.asyncio
    async def test_overwrite_with_different_value_notifies_admins(self):
        """Бармен перезаписывает смену — старое значение отличается → уведомление."""
        from app.bot.handlers.userhours import _write_and_finish_bar

        message = _make_message()
        state = _make_state(day=15, month=5, year=2026, h=8.0, ah=3.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест Тестов"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[111])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", [999]),
            patch("app.bot.handlers.userhours.upsert_shift",
                  new=AsyncMock(return_value=_old_shift(7.0))),
        ):
            await _write_and_finish_bar(message, state, "Бармен")

        all_texts = " ".join(
            str(call) for call in message.bot.send_message.call_args_list
        )
        assert "⚠️ Смена перезаписана" in all_texts
        assert "Было:" in all_texts
        assert "Стало:" in all_texts

    @pytest.mark.asyncio
    async def test_overwrite_with_same_value_no_notification(self):
        """Бармен вводит смену — значение совпадает со старым → уведомление НЕ отправляется."""
        from app.bot.handlers.userhours import _write_and_finish_bar

        message = _make_message()
        # h=8, ah=3 → new_value = "8/3"
        state = _make_state(day=15, month=5, year=2026, h=8.0, ah=3.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест Тестов"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[111])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", [999]),
            patch("app.bot.handlers.userhours.upsert_shift",
                  new=AsyncMock(return_value=_old_shift(8.0, 3.0))),
        ):
            await _write_and_finish_bar(message, state, "Бармен")

        all_texts = " ".join(
            str(call) for call in message.bot.send_message.call_args_list
        )
        assert "⚠️ Смена перезаписана" not in all_texts

    @pytest.mark.asyncio
    async def test_no_overwrite_when_cell_was_empty(self):
        """Ячейка была пустой → уведомление НЕ отправляется."""
        from app.bot.handlers.userhours import _write_and_finish_bar

        message = _make_message()
        state = _make_state(day=1, month=5, year=2026, h=8.0, ah=0.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест Тестов"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[111])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", [999]),
            patch("app.bot.handlers.userhours.upsert_shift",
                  new=AsyncMock(return_value=None)),
        ):
            await _write_and_finish_bar(message, state, "Бармен")

        all_texts = " ".join(
            str(call) for call in message.bot.send_message.call_args_list
        )
        assert "⚠️ Смена перезаписана" not in all_texts


# ---------------------------------------------------------------------------
# Тест: _format_shift_value форматирует корректно
# ---------------------------------------------------------------------------

class TestFormatShiftValue:

    def test_plain_hours(self):
        from app.services.google_sheets import _format_shift_value
        assert _format_shift_value("8") == "8 ч"

    def test_decimal_hours(self):
        from app.services.google_sheets import _format_shift_value
        assert _format_shift_value("8.5") == "8.5 ч"

    def test_hours_with_ah(self):
        from app.services.google_sheets import _format_shift_value
        assert _format_shift_value("8/3") == "8 ч (тусовочные: 3 ч)"

    def test_hours_with_decimal_ah(self):
        from app.services.google_sheets import _format_shift_value
        assert _format_shift_value("8/1.5") == "8 ч (тусовочные: 1.5 ч)"

    def test_empty_raw(self):
        from app.services.google_sheets import _format_shift_value
        assert _format_shift_value("") == "0 ч"
