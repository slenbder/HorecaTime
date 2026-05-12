"""Тесты отображения пула чеков в /hours_* командах для Официанта."""
from unittest.mock import MagicMock, patch

import pytest

from app.bot.handlers.userreports import (
    _build_hours_first_lines,
    _build_hours_second_lines,
)

_FIRST_DATA = {"h_first": 80.0, "ah_first": 1.5}
_SECOND_DATA = {
    "h_second": 80.0,
    "ah_second": 1.5,
    "h_total": 160.0,
    "ah_total": 3.0,
}
_WAITER_RATE = {"base_rate": 250.0, "extra_rate": None}
_RUNNER_RATE = {"base_rate": 200.0, "extra_rate": 250.0}
_RUNNER_FIRST_DATA = {"h_first": 80.0, "ah_first": 2.0}


class TestHoursWithChecksPool:

    @pytest.mark.asyncio
    async def test_hours_first_shows_checks_pool(self):
        """_build_hours_first_lines для Официанта содержит строку с пулом чеков."""
        with patch("app.bot.handlers.userreports.sheets_client") as mock_sc:
            mock_sc.get_phantom_checks_summary.return_value = 47

            lines = await _build_hours_first_lines(_FIRST_DATA, "Официант", _WAITER_RATE)

        pool_lines = [l for l in lines if "пул чеков" in l.lower() or "47 шт" in l]
        assert pool_lines, f"Строка с пулом чеков не найдена в: {lines}"
        assert "47 шт" in pool_lines[0]
        assert "70500" in pool_lines[0]  # 47 * 1500

    @pytest.mark.asyncio
    async def test_hours_first_zero_checks(self):
        """Пул = 0 → строка всё равно присутствует '0 шт (0 р)'."""
        with patch("app.bot.handlers.userreports.sheets_client") as mock_sc:
            mock_sc.get_phantom_checks_summary.return_value = 0

            lines = await _build_hours_first_lines(_FIRST_DATA, "Официант", _WAITER_RATE)

        pool_lines = [l for l in lines if "пул чеков" in l.lower()]
        assert pool_lines, "Строка с пулом чеков должна присутствовать даже при 0"
        assert "0 шт" in pool_lines[0]
        assert "(0 р)" in pool_lines[0]

    @pytest.mark.asyncio
    async def test_hours_second_shows_checks_pool(self):
        """_build_hours_second_lines для Официанта содержит строку с пулом чеков."""
        with patch("app.bot.handlers.userreports.sheets_client") as mock_sc:
            mock_sc.get_phantom_checks_summary.return_value = 23

            lines = await _build_hours_second_lines(_SECOND_DATA, "Официант", _WAITER_RATE)

        pool_lines = [l for l in lines if "пул чеков" in l.lower() or "23 шт" in l]
        assert pool_lines, f"Строка с пулом чеков не найдена в: {lines}"
        assert "23 шт" in pool_lines[0]

    @pytest.mark.asyncio
    async def test_hours_last_shows_checks_pool(self):
        """phantom_period='last' → get_phantom_checks_summary вызван с 'last'."""
        with patch("app.bot.handlers.userreports.sheets_client") as mock_sc:
            mock_sc.get_phantom_checks_summary.return_value = 15

            lines = await _build_hours_second_lines(
                _SECOND_DATA, "Официант", _WAITER_RATE,
                phantom_period="last",
            )

        mock_sc.get_phantom_checks_summary.assert_called_once_with("last")
        pool_lines = [l for l in lines if "пул чеков" in l.lower()]
        assert pool_lines

    @pytest.mark.asyncio
    async def test_hours_checks_not_for_runner(self):
        """Раннер НЕ получает строку с пулом чеков."""
        with patch("app.bot.handlers.userreports.sheets_client") as mock_sc:
            mock_sc.get_phantom_checks_summary.return_value = 100

            lines = await _build_hours_first_lines(_RUNNER_FIRST_DATA, "Раннер", _RUNNER_RATE)

        mock_sc.get_phantom_checks_summary.assert_not_called()
        pool_lines = [l for l in lines if "пул чеков" in l.lower()]
        assert not pool_lines
