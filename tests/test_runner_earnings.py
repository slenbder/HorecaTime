"""Tests for _build_runner_earnings_lines (Раннер earnings breakdown)."""
import pytest

from app.bot.handlers.userreports import _build_runner_earnings_lines


class TestRunnerEarningsLines:

    def test_runner_earnings_no_weekends(self):
        """h_weekend=0 → single combined-total line (else-branch)."""
        lines = _build_runner_earnings_lines(h=40.0, ah=0.0, h_weekend=0.0, base=200.0, extra=300.0)

        assert len(lines) == 1
        assert "8000" in lines[0]

    def test_runner_earnings_with_weekends(self):
        """h_weekend=10 → regular-day line + weekend line + total."""
        lines = _build_runner_earnings_lines(h=40.0, ah=0.0, h_weekend=10.0, base=200.0, extra=300.0)

        assert len(lines) == 3
        assert any("6000" in line and "обычные" in line for line in lines)
        assert any("3000" in line and "выходные" in line for line in lines)
        assert any("9000" in line for line in lines)

    def test_runner_earnings_with_ah(self):
        """ah>0 with weekends → regular + weekend + extra-hours + total (4 lines)."""
        lines = _build_runner_earnings_lines(h=40.0, ah=5.0, h_weekend=10.0, base=200.0, extra=300.0)

        assert len(lines) == 4
        assert any("доп. часы" in line for line in lines)
        assert any("10000" in line for line in lines)

    def test_runner_earnings_all_weekends(self):
        """h == h_weekend → weekend line contains full total 6000."""
        lines = _build_runner_earnings_lines(h=20.0, ah=0.0, h_weekend=20.0, base=200.0, extra=300.0)

        assert any("6000" in line and "выходные" in line for line in lines)
        total_line = lines[-1]
        assert "6000" in total_line
