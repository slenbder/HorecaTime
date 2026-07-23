"""Unit-тесты _fetch_user_info (Фаза 3): читает данные сотрудника из employees, не из Техлиста."""
from unittest.mock import AsyncMock, patch

import pytest

from app.bot.handlers.auth import _fetch_user_info
from config import DB_PATH


def _employee(**overrides) -> dict:
    base = {
        "telegram_id": 42,
        "nickname": "nick",
        "full_name": "Иванов Иван",
        "department": "Зал",
        "position": "Официант",
        "custom_position": None,
        "role": "user",
        "status": "approved",
        "registered_at": "2026-07-01T00:00:00",
        "approved_at": "2026-07-02T00:00:00",
        "dismissed_at": None,
    }
    base.update(overrides)
    return base


class TestFetchUserInfo:

    @pytest.mark.asyncio
    async def test_found_returns_all_five_keys(self):
        employee = _employee()
        with patch(
            "app.bot.handlers.auth.get_employee", new=AsyncMock(return_value=employee)
        ) as mock_get:
            result = await _fetch_user_info(42)

        mock_get.assert_awaited_once_with(DB_PATH, 42)
        assert set(result.keys()) == {"fio", "department", "position", "custom_position", "mention"}
        assert result["fio"] == "Иванов Иван"
        assert result["department"] == "Зал"
        assert result["position"] == "Официант"

    @pytest.mark.asyncio
    async def test_not_found_returns_none(self):
        with patch("app.bot.handlers.auth.get_employee", new=AsyncMock(return_value=None)):
            result = await _fetch_user_info(999)

        assert result is None

    @pytest.mark.asyncio
    async def test_custom_position_none_becomes_empty_string(self):
        """employees.custom_position nullable → в результате '' , а не None (сохранена
        семантика прежнего дефолта из user_info.get("custom_position", ""))."""
        employee = _employee(custom_position=None)
        with patch("app.bot.handlers.auth.get_employee", new=AsyncMock(return_value=employee)):
            result = await _fetch_user_info(42)

        assert result["custom_position"] == ""
        assert result["custom_position"] is not None

    @pytest.mark.asyncio
    async def test_nickname_without_at_builds_mention_correctly(self):
        """nickname в employees хранится без '@' — lstrip('@') не должен ничего лишнего
        срезать (идемпотентен независимо от наличия префикса)."""
        employee = _employee(nickname="nick", full_name="Иванов Иван")
        with patch("app.bot.handlers.auth.get_employee", new=AsyncMock(return_value=employee)):
            result = await _fetch_user_info(42)

        assert result["mention"] == '<a href="https://t.me/nick">Иванов Иван</a>'

    @pytest.mark.asyncio
    async def test_fio_comes_from_full_name_not_fio_from_user(self):
        """employees не имеет колонки fio_from_user — fio строится из full_name."""
        employee = _employee(full_name="Петров Пётр")
        assert "fio_from_user" not in employee

        with patch("app.bot.handlers.auth.get_employee", new=AsyncMock(return_value=employee)):
            result = await _fetch_user_info(42)

        assert result["fio"] == "Петров Пётр"
