"""Tests for summarize_shifts (расчёт часов из shifts, контракт ключей сводки)."""
import pytest

from app.services.shift_summary import summarize_shifts

CONTRACT_KEYS = {
    "h_first", "ah_first", "h_second", "ah_second", "h_total", "ah_total",
    "h_weekend_first", "h_weekend_second", "h_weekend_total",
}

# Июль 2026: 1 — ср, 2 — чт, 3 — пт, 4 — сб, 5 — вс, 6 — пн, 15 — ср, 16 — чт,
# 17 — пт, 18 — сб, 19 — вс, 20 — пн.
Y, M = 2026, 7


def _row(day, h, ah=0.0, month=M, year=Y):
    return {"shift_date": f"{year:04d}-{month:02d}-{day:02d}", "hours": h, "extra_hours": ah}


class TestSummarizeShifts:

    def test_empty_gives_zeros_for_all_keys(self):
        result = summarize_shifts([], Y, M)
        assert set(result) == CONTRACT_KEYS
        assert all(v == 0.0 for v in result.values())

    def test_keys_equal_contract_and_values_float(self):
        result = summarize_shifts([_row(2, 8), _row(3, 6, 1)], Y, M)
        assert set(result) == CONTRACT_KEYS
        assert all(isinstance(v, float) for v in result.values())

    def test_half_split_includes_15_and_16(self):
        result = summarize_shifts([_row(15, 8.0), _row(16, 9.0)], Y, M)
        assert result["h_first"] == 8.0
        assert result["h_second"] == 9.0
        assert result["h_total"] == 17.0

    def test_hours_and_extra_hours_separated(self):
        result = summarize_shifts([_row(2, 8.0, 1.5), _row(16, 10.0, 2.0)], Y, M)
        assert result["h_first"] == 8.0 and result["ah_first"] == 1.5
        assert result["h_second"] == 10.0 and result["ah_second"] == 2.0
        assert result["h_total"] == 18.0 and result["ah_total"] == 3.5

    @pytest.mark.parametrize("day, expected", [
        (3, 8.0),   # пт
        (4, 8.0),   # сб
        (5, 8.0),   # вс
        (6, 0.0),   # пн
        (1, 0.0),   # ср
        (2, 0.0),   # чт
    ])
    def test_weekend_days(self, day, expected):
        result = summarize_shifts([_row(day, 8.0)], Y, M)
        assert result["h_weekend_first"] == expected
        assert result["h_weekend_total"] == expected

    def test_weekend_in_both_halves_total_is_sum(self):
        result = summarize_shifts([_row(3, 8.0), _row(4, 6.0), _row(17, 5.0), _row(19, 4.0)], Y, M)
        assert result["h_weekend_first"] == 14.0
        assert result["h_weekend_second"] == 9.0
        assert result["h_weekend_total"] == 23.0
        assert result["h_weekend_total"] == result["h_weekend_first"] + result["h_weekend_second"]

    def test_weekend_uses_hours_only_not_extra_hours(self):
        result = summarize_shifts([_row(3, 8.0, 2.0)], Y, M)
        assert result["h_weekend_first"] == 8.0
        assert result["ah_first"] == 2.0

    def test_total_equals_first_plus_second(self):
        result = summarize_shifts([_row(2, 7.5, 1.0), _row(20, 9.0, 0.5)], Y, M)
        assert result["h_total"] == result["h_first"] + result["h_second"]
        assert result["ah_total"] == result["ah_first"] + result["ah_second"]

    def test_midnight_shift_attributed_to_start_date(self):
        # Четверг 02.07 22:00-04:00 = 6 ч — не выходной (все часы за четвергом).
        thursday = summarize_shifts([_row(2, 6.0)], Y, M)
        assert thursday["h_first"] == 6.0
        assert thursday["h_weekend_total"] == 0.0
        # Воскресенье 05.07 22:00-04:00 = 6 ч — выходной целиком.
        sunday = summarize_shifts([_row(5, 6.0)], Y, M)
        assert sunday["h_weekend_first"] == 6.0
        assert sunday["h_weekend_total"] == 6.0

    def test_no_float_tails_on_sums(self):
        result = summarize_shifts([_row(3, 0.1, 0.1), _row(4, 0.2, 0.2)], Y, M)
        assert result["h_first"] == 0.3
        assert result["ah_first"] == 0.3
        assert result["h_weekend_first"] == 0.3
        assert result["h_total"] == 0.3

    def test_rows_of_other_month_ignored(self):
        result = summarize_shifts([_row(2, 8.0), _row(2, 5.0, month=6)], Y, M)
        assert result["h_total"] == 8.0

    def test_none_extra_hours_treated_as_zero(self):
        row = {"shift_date": "2026-07-02", "hours": 8.0, "extra_hours": None}
        assert summarize_shifts([row], Y, M)["ah_total"] == 0.0
