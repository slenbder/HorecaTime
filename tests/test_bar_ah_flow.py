"""Тесты нового bar AH флоу: кнопки Да/Нет + ввод числа часов."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.fsm.shift_states import ShiftStates


# ---------------------------------------------------------------------------
# Вспомогательные фабрики
# ---------------------------------------------------------------------------

def _make_message(text: str = "", tg_id: int = 12345, username: str = "barman") -> MagicMock:
    msg = MagicMock()
    msg.text = text
    msg.from_user.id = tg_id
    msg.from_user.username = username
    msg.answer = AsyncMock()
    msg.bot.send_message = AsyncMock()
    return msg


def _make_callback(tg_id: int = 12345, username: str = "barman") -> MagicMock:
    cb = MagicMock()
    cb.from_user.id = tg_id
    cb.from_user.username = username
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.message.bot = MagicMock()
    cb.message.bot.send_message = AsyncMock()
    cb.answer = AsyncMock()
    return cb


def _make_state(day=15, month=5, year=2026, h=8.0, position="Бармен") -> AsyncMock:
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={
        "day": day, "month": month, "year": year,
        "h": h, "start": 16.0, "end": 0.0, "position": position,
    })
    state.update_data = AsyncMock()
    state.set_state = AsyncMock()
    state.clear = AsyncMock()
    return state


# ---------------------------------------------------------------------------
# Тесты _process_bar_shift_input — новая механика (кнопки)
# ---------------------------------------------------------------------------

class TestBarShiftInput:

    @pytest.mark.asyncio
    async def test_valid_input_shows_buttons_and_sets_ah_choice_state(self):
        """Корректная смена → отправлены кнопки Да/Нет, FSM = waiting_ah_choice."""
        from app.bot.handlers.userhours import _process_bar_shift_input

        message = _make_message("13.05 16:00-00:00")
        state = AsyncMock()
        state.update_data = AsyncMock()
        state.set_state = AsyncMock()

        with patch("app.bot.handlers.userhours.parse_shift") as mock_parse:
            mock_parse.return_value = {
                "day": 13, "month": 5, "year": 2026,
                "h": 8.0, "start": 16.0, "end": 0.0, "is_weekend": False,
            }
            await _process_bar_shift_input(message, state, "Бармен")

        message.answer.assert_called_once()
        call_kwargs = message.answer.call_args
        assert "Были тусовочные часы?" in call_kwargs[0][0]
        assert call_kwargs[1].get("reply_markup") is not None

        state.set_state.assert_called_once_with(ShiftStates.waiting_ah_choice)

    @pytest.mark.asyncio
    async def test_invalid_input_returns_error_stays_in_shift_input(self):
        """Некорректный ввод → сообщение об ошибке, set_state не вызывается."""
        from app.bot.handlers.userhours import _process_bar_shift_input

        message = _make_message("blah")
        state = AsyncMock()
        state.set_state = AsyncMock()

        with patch("app.bot.handlers.userhours.parse_shift", return_value=None):
            await _process_bar_shift_input(message, state, "Бармен")

        message.answer.assert_called_once()
        assert "❌" in message.answer.call_args[0][0]
        state.set_state.assert_not_called()


# ---------------------------------------------------------------------------
# Тесты _process_bar_ah_input — парсинг числа
# ---------------------------------------------------------------------------

class TestBarAhInput:

    @pytest.mark.asyncio
    async def test_valid_integer_input(self):
        """Ввод '3' → ah=3.0, write_and_finish_bar вызван."""
        from app.bot.handlers.userhours import _process_bar_ah_input

        message = _make_message("3")
        state = _make_state(h=8.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Бармен Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", []),
            patch("app.bot.handlers.userhours.upsert_shift", new=AsyncMock(return_value=None)),
        ):
            mock_sc.write_shift.return_value = ""
            await _process_bar_ah_input(message, state, "Бармен")

        state.update_data.assert_called_with(ah=3.0)
        mock_sc.write_shift.assert_called_once()

    @pytest.mark.asyncio
    async def test_valid_decimal_with_dot(self):
        """Ввод '2.5' → ah=2.5."""
        from app.bot.handlers.userhours import _process_bar_ah_input

        message = _make_message("2.5")
        state = _make_state(h=8.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", []),
            patch("app.bot.handlers.userhours.upsert_shift", new=AsyncMock(return_value=None)),
        ):
            mock_sc.write_shift.return_value = ""
            await _process_bar_ah_input(message, state, "Бармен")

        state.update_data.assert_called_with(ah=2.5)

    @pytest.mark.asyncio
    async def test_valid_decimal_with_comma(self):
        """Ввод '2,5' → ah=2.5 (запятая нормализуется в точку)."""
        from app.bot.handlers.userhours import _process_bar_ah_input

        message = _make_message("2,5")
        state = _make_state(h=8.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", []),
            patch("app.bot.handlers.userhours.upsert_shift", new=AsyncMock(return_value=None)),
        ):
            mock_sc.write_shift.return_value = ""
            await _process_bar_ah_input(message, state, "Бармен")

        state.update_data.assert_called_with(ah=2.5)

    @pytest.mark.asyncio
    async def test_non_number_input_gives_error(self):
        """Нечисловой ввод → ошибка, write_shift не вызывается."""
        from app.bot.handlers.userhours import _process_bar_ah_input

        message = _make_message("abc")
        state = _make_state()

        with patch("app.bot.handlers.userhours.sheets_client") as mock_sc:
            await _process_bar_ah_input(message, state, "Бармен")

        message.answer.assert_called_once()
        assert "❌" in message.answer.call_args[0][0]
        mock_sc.write_shift.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_input_gives_error(self):
        """Ввод '0' → ошибка (>0 обязательно)."""
        from app.bot.handlers.userhours import _process_bar_ah_input

        message = _make_message("0")
        state = _make_state()

        with patch("app.bot.handlers.userhours.sheets_client") as mock_sc:
            await _process_bar_ah_input(message, state, "Бармен")

        message.answer.assert_called_once()
        assert "❌" in message.answer.call_args[0][0]
        mock_sc.write_shift.assert_not_called()

    @pytest.mark.asyncio
    async def test_negative_input_gives_error(self):
        """Ввод отрицательного числа → ошибка."""
        from app.bot.handlers.userhours import _process_bar_ah_input

        message = _make_message("-2")
        state = _make_state()

        with patch("app.bot.handlers.userhours.sheets_client") as mock_sc:
            await _process_bar_ah_input(message, state, "Бармен")

        message.answer.assert_called_once()
        assert "❌" in message.answer.call_args[0][0]
        mock_sc.write_shift.assert_not_called()

    @pytest.mark.asyncio
    async def test_rounding_to_half(self):
        """Ввод '2.7' → state.update_data вызван с ah, округлённым до 0.5."""
        from app.bot.handlers.userhours import _process_bar_ah_input

        message = _make_message("2.7")
        state = _make_state(h=8.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", []),
            patch("app.bot.handlers.userhours.upsert_shift", new=AsyncMock(return_value=None)),
        ):
            mock_sc.write_shift.return_value = ""
            await _process_bar_ah_input(message, state, "Бармен")

        # round_to_half(2.7) = 2.5 или 3.0
        ah_saved = state.update_data.call_args[1]["ah"]
        assert ah_saved in (2.5, 3.0)


# ---------------------------------------------------------------------------
# Тесты callback "bar_ah:no"
# ---------------------------------------------------------------------------

class TestCbBarAhNo:

    @pytest.mark.asyncio
    async def test_no_button_writes_shift_with_zero_ah(self):
        """Кнопка 'Нет' → запись с ah=0, FSM очищен."""
        from app.bot.handlers.userhours import cb_bar_ah_no

        callback = _make_callback()
        state = _make_state(h=8.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Бармен Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", []),
            patch("app.bot.handlers.userhours.upsert_shift", new=AsyncMock(return_value=None)),
        ):
            mock_sc.write_shift.return_value = ""
            await cb_bar_ah_no(callback, state)

        mock_sc.write_shift.assert_called_once()
        ah_arg = mock_sc.write_shift.call_args[0][5]
        assert ah_arg == 0.0

        callback.message.edit_text.assert_called_once()
        assert "❌" in callback.message.edit_text.call_args[0][0]
        callback.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_button_uses_callback_from_user_id(self):
        """Кнопка 'Нет' → tg_id берётся из callback.from_user, не из callback.message."""
        from app.bot.handlers.userhours import cb_bar_ah_no

        callback = _make_callback(tg_id=99999)
        state = _make_state(h=8.0)

        with (
            patch("app.bot.handlers.userhours.sheets_client") as mock_sc,
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест"}),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[])),
            patch("app.bot.handlers.userhours.SUPERADMIN_IDS", []),
            patch("app.bot.handlers.userhours.upsert_shift", new=AsyncMock(return_value=None)),
        ):
            mock_sc.write_shift.return_value = ""
            await cb_bar_ah_no(callback, state)

        tg_id_passed = mock_sc.write_shift.call_args[0][0]
        assert tg_id_passed == 99999


# ---------------------------------------------------------------------------
# Тесты callback "bar_ah:yes"
# ---------------------------------------------------------------------------

class TestCbBarAhYes:

    @pytest.mark.asyncio
    async def test_yes_button_edits_message_and_asks_for_hours(self):
        """Кнопка 'Да' → редактирует сообщение, спрашивает количество часов."""
        from app.bot.handlers.userhours import cb_bar_ah_yes

        callback = _make_callback()
        state = _make_state(h=8.0)

        await cb_bar_ah_yes(callback, state)

        callback.message.edit_text.assert_called_once()
        edited = callback.message.edit_text.call_args[0][0]
        assert "✅" in edited

        callback.message.answer.assert_called_once()
        asked = callback.message.answer.call_args[0][0]
        assert "тусовочных часов" in asked.lower()

    @pytest.mark.asyncio
    async def test_yes_button_sets_waiting_ah_input_state(self):
        """Кнопка 'Да' → FSM переходит в waiting_ah_input."""
        from app.bot.handlers.userhours import cb_bar_ah_yes

        callback = _make_callback()
        state = _make_state(h=8.0)

        await cb_bar_ah_yes(callback, state)

        state.set_state.assert_called_once_with(ShiftStates.waiting_ah_input)
        callback.answer.assert_called_once()
