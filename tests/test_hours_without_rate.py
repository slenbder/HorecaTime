from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.bot.handlers.userreports import cmd_hours_first, cmd_hours_second, cmd_hours_last
from config import DB_PATH

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


@pytest.mark.asyncio
async def test_hours_last_january_rolls_to_december_previous_year():
    """Граница года: /hours_last, вызванный в январе, должен считать
    'прошлый месяц' как декабрь ПРЕДЫДУЩЕГО года (prev_month=12,
    prev_year=now.year-1), а не декабрь текущего/тот же год. Этот
    prev_year/prev_month — ранее существовавший код (использовался только
    для get_user_rate_history), сейчас на него же завязан и период
    наполняемости чеков (get_check_filling_summary) — проверяем оба места."""
    message = _make_message()
    fake_now = datetime(2026, 1, 15, tzinfo=ZoneInfo("Europe/Moscow"))

    with (
        patch("app.bot.handlers.userreports.get_user", return_value=_FAKE_USER),
        patch("app.bot.handlers.userreports.get_user_rate_history",
              new=AsyncMock(return_value={"base_rate": 250.0, "extra_rate": None})) as mock_rate_history,
        patch("app.bot.handlers.userreports.get_check_filling_summary",
              new=AsyncMock(return_value=0)) as mock_summary,
        patch("app.bot.handlers.userreports.sheets_client") as mock_sheets,
        patch("app.bot.handlers.userreports.datetime") as mock_datetime,
    ):
        mock_datetime.now.return_value = fake_now
        mock_sheets.get_summary_hours.return_value = {
            "h_second": 0.0, "ah_second": 0.0, "h_total": 0.0, "ah_total": 0.0,
        }
        await cmd_hours_last(message)

    # now = 15.01.2026 → prev = декабрь 2025, а не декабрь 2026 и не январь
    mock_rate_history.assert_called_once_with(DB_PATH, 12345, 12, 2025)
    mock_summary.assert_called_once_with(DB_PATH, 2025, 12, "full")
