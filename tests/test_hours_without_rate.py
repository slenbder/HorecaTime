import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot.handlers.userreports import cmd_hours_first, cmd_hours_second, cmd_hours_last

_EXPECTED_MSG = (
    "⚠️ Ваша ставка ещё не установлена.\n"
    "Обратитесь к администратору вашего отдела для установки ставки."
)

_FAKE_USER = {
    "telegram_id": 12345,
    "full_name": "Test User",
    "role": "user",
    "department": "Зал",
    "position": "Официант",
}


def _make_message() -> MagicMock:
    message = MagicMock()
    message.from_user.id = 12345
    message.answer = AsyncMock()
    return message


class TestHoursWithoutRate:

    @pytest.mark.asyncio
    async def test_hours_first_without_rate(self):
        """Юзер без ставки вызывает /hours_first — получает сообщение с инструкцией."""
        message = _make_message()

        with (
            patch("app.bot.handlers.userreports.get_user", return_value=_FAKE_USER),
            patch("app.bot.handlers.userreports.get_user_rate", new=AsyncMock(return_value=None)),
            patch("app.bot.handlers.userreports.sheets_client") as mock_sheets,
        ):
            mock_sheets.get_summary_hours.return_value = {"h1": 0}
            await cmd_hours_first(message)

        message.answer.assert_called_once_with(_EXPECTED_MSG)

    @pytest.mark.asyncio
    async def test_hours_second_without_rate(self):
        """Юзер без ставки вызывает /hours_second — получает сообщение с инструкцией."""
        message = _make_message()

        with (
            patch("app.bot.handlers.userreports.get_user", return_value=_FAKE_USER),
            patch("app.bot.handlers.userreports.get_user_rate", new=AsyncMock(return_value=None)),
            patch("app.bot.handlers.userreports.sheets_client") as mock_sheets,
        ):
            mock_sheets.get_summary_hours.return_value = {"h1": 0}
            await cmd_hours_second(message)

        message.answer.assert_called_once_with(_EXPECTED_MSG)

    @pytest.mark.asyncio
    async def test_hours_last_without_rate(self):
        """Юзер без ставки вызывает /hours_last — получает сообщение с инструкцией."""
        message = _make_message()

        with (
            patch("app.bot.handlers.userreports.get_user", return_value=_FAKE_USER),
            patch("app.bot.handlers.userreports.get_user_rate", new=AsyncMock(return_value=None)),
            patch("app.bot.handlers.userreports.get_user_rate_history", new=AsyncMock(return_value=None)),
            patch("app.bot.handlers.userreports.sheets_client") as mock_sheets,
        ):
            mock_sheets.get_summary_hours.return_value = {"h1": 0}
            await cmd_hours_last(message)

        message.answer.assert_called_once_with(_EXPECTED_MSG)
