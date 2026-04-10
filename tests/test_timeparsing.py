import datetime
import pytest
from app.services.timeparsing import parse_shift, round_to_half, is_weekend, check_overlap


# ---------------------------------------------------------------------------
# round_to_half
# ---------------------------------------------------------------------------

class TestRoundToHalf:
    def test_exact_half(self):
        assert round_to_half(7.5) == 7.5

    def test_rounds_up_to_half(self):
        # 7ч 20мин = 7.333… → ближайшие 0.5 = 7.5
        assert round_to_half(7 + 20 / 60) == 7.5

    def test_rounds_down_to_whole(self):
        # 7ч 10мин = 7.166… → ближайшие 0.5 = 7.0
        assert round_to_half(7 + 10 / 60) == 7.0

    def test_whole_number(self):
        assert round_to_half(8.0) == 8.0

    def test_zero(self):
        assert round_to_half(0.0) == 0.0


# ---------------------------------------------------------------------------
# is_weekend
# ---------------------------------------------------------------------------

class TestIsWeekend:
    # 2025-03-14 — пятница
    def test_friday(self):
        assert is_weekend(14, 3, 2025) is True

    # 2025-03-15 — суббота
    def test_saturday(self):
        assert is_weekend(15, 3, 2025) is True

    # 2025-03-16 — воскресенье
    def test_sunday(self):
        assert is_weekend(16, 3, 2025) is True

    # 2025-03-17 — понедельник
    def test_monday(self):
        assert is_weekend(17, 3, 2025) is False

    # 2025-03-18 — вторник
    def test_tuesday(self):
        assert is_weekend(18, 3, 2025) is False


# ---------------------------------------------------------------------------
# parse_shift — форматы даты
# ---------------------------------------------------------------------------

class TestDateFormats:
    TIME = "10-18"

    def _parse(self, date_str):
        return parse_shift(f"{date_str} {self.TIME}", "Раннер")

    def test_short_day_month(self):
        r = self._parse("1.1")
        assert r is not None
        assert r["day"] == 1 and r["month"] == 1
        assert r["year"] == datetime.date.today().year

    def test_zero_padded(self):
        r = self._parse("01.01")
        assert r is not None
        assert r["day"] == 1 and r["month"] == 1

    def test_with_short_year(self):
        r = self._parse("1.01.25")
        assert r is not None
        assert r["year"] == 2025

    def test_fully_padded_with_year(self):
        r = self._parse("01.01.25")
        assert r is not None
        assert r["day"] == 1 and r["month"] == 1 and r["year"] == 2025


# ---------------------------------------------------------------------------
# parse_shift — форматы времени
# ---------------------------------------------------------------------------

class TestDashNormalization:
    def test_spaces_around_hyphen(self):
        # "10:00 - 20:00" — пробелы вокруг тире
        r = parse_shift("1.03 10:00 - 20:00", "Раннер")
        assert r is not None
        assert r["start"] == 10.0 and r["end"] == 20.0 and r["h"] == 10.0

    def test_en_dash(self):
        # "10:00–20:00" — en dash (U+2013)
        r = parse_shift("1.03 10:00\u201320:00", "Раннер")
        assert r is not None
        assert r["start"] == 10.0 and r["end"] == 20.0 and r["h"] == 10.0


class TestTimeFormats:
    DATE = "15.03.25"

    def _parse(self, time_str):
        return parse_shift(f"{self.DATE} {time_str}", "Раннер")

    def test_hhmm_range(self):
        r = self._parse("1000-1800")
        assert r is not None
        assert r["start"] == 10.0 and r["end"] == 18.0 and r["h"] == 8.0

    def test_h_range(self):
        r = self._parse("10-18")
        assert r is not None
        assert r["start"] == 10.0 and r["end"] == 18.0 and r["h"] == 8.0

    def test_dot_separator(self):
        r = self._parse("10.00-18.00")
        assert r is not None
        assert r["start"] == 10.0 and r["end"] == 18.0 and r["h"] == 8.0

    def test_colon_separator(self):
        r = self._parse("10:00-18:00")
        assert r is not None
        assert r["start"] == 10.0 and r["end"] == 18.0 and r["h"] == 8.0


# ---------------------------------------------------------------------------
# parse_shift — пересечение полуночи
# ---------------------------------------------------------------------------

class TestMidnightCrossing:
    def test_midnight_crossing(self):
        # 22:00 → 02:00 = 4 часа
        r = parse_shift("15.03.25 22-02", "Бармен")
        assert r is not None
        assert r["h"] == 4.0

    def test_midnight_with_minutes(self):
        # 22:30 → 02:00 = 3.5 часа
        r = parse_shift("15.03.25 22:30-02:00", "Бармен")
        assert r is not None
        assert r["h"] == 3.5

    def test_same_start_end_is_zero(self):
        r = parse_shift("15.03.25 10-10", "Кухня")
        assert r is not None
        assert r["h"] == 0.0


# ---------------------------------------------------------------------------
# parse_shift — признак выходного дня
# ---------------------------------------------------------------------------

class TestWeekendFlag:
    def test_friday_is_weekend(self):
        r = parse_shift("14.03.25 10-18", "Раннер")
        assert r is not None
        assert r["is_weekend"] is True

    def test_monday_is_not_weekend(self):
        r = parse_shift("17.03.25 10-18", "Раннер")
        assert r is not None
        assert r["is_weekend"] is False


# ---------------------------------------------------------------------------
# parse_shift — невалидный ввод
# ---------------------------------------------------------------------------

class TestInvalidInput:
    def test_empty_string(self):
        assert parse_shift("", "Раннер") is None

    def test_only_date(self):
        assert parse_shift("15.03.25", "Раннер") is None

    def test_only_time(self):
        assert parse_shift("10-18", "Раннер") is None

    def test_invalid_date(self):
        assert parse_shift("32.13.25 10-18", "Раннер") is None

    def test_invalid_time_format(self):
        assert parse_shift("15.03.25 abc-xyz", "Раннер") is None

    def test_invalid_time_range(self):
        assert parse_shift("15.03.25 25-30", "Раннер") is None

    def test_garbage(self):
        assert parse_shift("не смена", "Раннер") is None

    def test_three_tokens(self):
        assert parse_shift("15.03.25 10-18 extra", "Раннер") is None


# ---------------------------------------------------------------------------
# check_overlap
# ---------------------------------------------------------------------------

class TestCheckOverlap:
    def test_no_overlap_sequential(self):
        # 10-20 и 22-02 — не пересекаются
        assert check_overlap(10.0, 20.0, 22.0, 2.0) is False

    def test_overlap_crossing(self):
        # 10-22 и 20-02 — пересекаются (20:00–22:00)
        assert check_overlap(10.0, 22.0, 20.0, 2.0) is True

    def test_both_midnight_overlap(self):
        # 22-02 и 01-04 — оба через полночь, пересекаются (01:00–02:00)
        assert check_overlap(22.0, 2.0, 1.0, 4.0) is True

    def test_boundary_no_overlap(self):
        # 10-20 и 20-23 — конец одного = начало другого, не пересекаются
        assert check_overlap(10.0, 20.0, 20.0, 23.0) is False

    def test_overlap_mixed_midnight(self):
        # 20-23 (не через полночь) и 22-02 (через полночь) — пересекаются (22:00–23:00)
        assert check_overlap(20.0, 23.0, 22.0, 2.0) is True
