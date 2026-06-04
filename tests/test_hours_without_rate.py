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


@pytest.mark.parametrize("cmd_handler,command", [
    (cmd_hours_first, "/hours_first"),
    (cmd_hours_second, "/hours_second"),
    (cmd_hours_last, "/hours_last"),
])
@pytest.mark.asyncio
async def test_hours_no_rate(cmd_handler, command):
    """Юзер без ставки вызывает команду — получает сообщение с инструкцией."""
    message = _make_message()

    with (
        patch("app.bot.handlers.userreports.get_user", return_value=_FAKE_USER),
        patch("app.bot.handlers.userreports.get_user_rate", new=AsyncMock(return_value=None)),
        patch("app.bot.handlers.userreports.get_user_rate_history", new=AsyncMock(return_value=None)),
        patch("app.bot.handlers.userreports.sheets_client") as mock_sheets,
    ):
        mock_sheets.get_summary_hours.return_value = {"h1": 0}
        await cmd_handler(message)

    message.answer.assert_called_once_with(_EXPECTED_MSG)
