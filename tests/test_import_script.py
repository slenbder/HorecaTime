"""Tests for import_from_sheets.py: cell parsing, status mapping, idempotency, source protection."""
import sqlite3

import pytest

from app.db.models import create_migration_tables
from config import PHANTOM_CHECK_FILLING_ID
from import_from_sheets import (
    parse_shift_cell,
    parse_registered_at,
    day_to_col,
    extract_employees,
    extract_shifts,
    extract_check_filling,
    extract_dismissed_ids,
    write_employees,
    write_shifts,
    write_check_filling,
    mark_dismissed,
)

NOW_ISO = "2026-07-07T12:00:00+03:00"


@pytest.fixture()
def migration_db(tmp_path):
    path = str(tmp_path / "import_test.db")
    with sqlite3.connect(path) as conn:
        create_migration_tables(conn.cursor())
        conn.commit()
    return path


# ---------------------------------------------------------------------------
# Парсинг ячеек
# ---------------------------------------------------------------------------

class TestParseShiftCell:

    @pytest.mark.parametrize("raw, expected", [
        ("8", (8.0, 0.0)),
        ("8/2", (8.0, 2.0)),
        ("1,5", (1.5, 0.0)),
        ("10/1,5", (10.0, 1.5)),
        ("12.5", (12.5, 0.0)),
        (" 8 / 2 ", (8.0, 2.0)),
    ])
    def test_valid_values(self, raw, expected):
        assert parse_shift_cell(raw) == expected

    @pytest.mark.parametrize("raw", ["", "   "])
    def test_empty_returns_none(self, raw):
        assert parse_shift_cell(raw) is None

    @pytest.mark.parametrize("raw", ["abc", "8/x", "x/2", "8//2", "•"])
    def test_garbage_raises(self, raw):
        with pytest.raises(ValueError):
            parse_shift_cell(raw)


class TestParseRegisteredAt:

    def test_valid_techlist_format(self):
        result = parse_registered_at("05.03.26 14:30")
        assert result is not None
        assert result.startswith("2026-03-05T14:30")

    @pytest.mark.parametrize("raw", ["", "не дата", "2026-03-05", "05.03.2026 14:30"])
    def test_unparsable_returns_none(self, raw):
        assert parse_registered_at(raw) is None


class TestDayToCol:

    @pytest.mark.parametrize("day, col", [(1, 4), (15, 18), (16, 20), (31, 35)])
    def test_mapping_matches_sheet_layout(self, day, col):
        # D–R (4–18) = дни 1–15, T–AI (20–35) = дни 16–31; S (19) — итог, пропускается
        assert day_to_col(day) == col


# ---------------------------------------------------------------------------
# Извлечение из Техлиста
# ---------------------------------------------------------------------------

def _tech_row(tg_id, nickname="@nick", fio="Иванов Иван", dept="Кухня",
              pos="Горячий цех", reg="05.03.26 14:30", approved="", custom=""):
    return [str(tg_id), nickname, fio, dept, pos, reg, approved, custom]


class TestExtractEmployees:

    def test_status_mapping(self):
        values = [
            ["header"] * 8,
            _tech_row(1, approved="ДА"),
            _tech_row(2, approved="да"),   # регистр не важен
            _tech_row(3, approved=""),
            _tech_row(4, approved="нет"),
        ]
        rows, warnings = extract_employees(values, {}, NOW_ISO)
        statuses = {r["telegram_id"]: r["status"] for r in rows}
        assert statuses == {1: "approved", 2: "approved", 3: "pending", 4: "pending"}
        assert warnings == []

    def test_non_numeric_tg_id_skipped_with_warning(self):
        values = [["header"] * 8, _tech_row("не-число")]
        rows, warnings = extract_employees(values, {}, NOW_ISO)
        assert rows == []
        assert len(warnings) == 1
        assert "нечисловой TG_ID" in warnings[0]

    def test_role_from_users_table_else_user(self):
        values = [["header"] * 8, _tech_row(1), _tech_row(2)]
        rows, _ = extract_employees(values, {1: "admin_kitchen"}, NOW_ISO)
        roles = {r["telegram_id"]: r["role"] for r in rows}
        assert roles == {1: "admin_kitchen", 2: "user"}

    def test_bad_registered_at_falls_back_to_now_with_warning(self):
        values = [["header"] * 8, _tech_row(1, reg="мусор")]
        rows, warnings = extract_employees(values, {}, NOW_ISO)
        assert rows[0]["registered_at"] == NOW_ISO
        assert len(warnings) == 1
        assert "не распарсилась" in warnings[0]

    def test_empty_optional_fields_become_none(self):
        values = [["header"] * 8, _tech_row(1, nickname="", custom="")]
        rows, _ = extract_employees(values, {}, NOW_ISO)
        assert rows[0]["nickname"] is None
        assert rows[0]["custom_position"] is None


# ---------------------------------------------------------------------------
# Извлечение смен и чеков из месячного листа
# ---------------------------------------------------------------------------

def _month_row(tg_id, fio="Иванов", pos="Официант", cells=None):
    """Строка месячного листа: A=ФИО, B=TG_ID, C=позиция, D..AI — дни."""
    row = [fio, str(tg_id), pos] + [""] * 32
    for day, value in (cells or {}).items():
        row[day_to_col(day) - 1] = value
    return row


class TestExtractShifts:

    def test_parses_days_both_halves(self):
        values = [_month_row(42, cells={1: "8", 16: "10/1,5"})]
        rows, warnings = extract_shifts(values, "Июль 2026", 7, 2026, NOW_ISO)
        assert warnings == []
        assert len(rows) == 2
        by_date = {r["shift_date"]: r for r in rows}
        assert by_date["2026-07-01"]["hours"] == 8.0
        assert by_date["2026-07-16"] == {
            "telegram_id": 42, "shift_date": "2026-07-16",
            "hours": 10.0, "extra_hours": 1.5, "source": "import",
            "created_at": NOW_ISO, "updated_at": NOW_ISO,
        }

    def test_phantom_row_excluded(self):
        values = [_month_row(PHANTOM_CHECK_FILLING_ID, cells={1: "5"})]
        rows, _ = extract_shifts(values, "Июль 2026", 7, 2026, NOW_ISO)
        assert rows == []

    def test_non_numeric_tg_rows_skipped(self):
        values = [
            ["", "", "КУХНЯ"] + [""] * 32,          # заголовок секции
            _month_row("текст", cells={1: "8"}),     # мусор в B
            _month_row(42, cells={2: "6"}),
        ]
        rows, warnings = extract_shifts(values, "Июль 2026", 7, 2026, NOW_ISO)
        assert [r["telegram_id"] for r in rows] == [42]
        assert warnings == []

    def test_garbage_cell_warns_and_continues(self):
        values = [_month_row(42, cells={1: "мусор", 2: "8"})]
        rows, warnings = extract_shifts(values, "Июль 2026", 7, 2026, NOW_ISO)
        assert len(rows) == 1
        assert rows[0]["shift_date"] == "2026-07-02"
        assert len(warnings) == 1
        assert "день 1" in warnings[0] and "мусор" in warnings[0]


class TestExtractCheckFilling:

    def test_counts_from_phantom_row(self):
        values = [
            _month_row(42, cells={1: "8"}),
            _month_row(PHANTOM_CHECK_FILLING_ID, fio="Наполняемость чека",
                       cells={1: "5", 16: "3"}),
        ]
        rows, warnings = extract_check_filling(values, "Июль 2026", 7, 2026)
        assert warnings == []
        assert rows == [
            {"fill_date": "2026-07-01", "count": 5},
            {"fill_date": "2026-07-16", "count": 3},
        ]

    def test_missing_phantom_warns(self):
        values = [_month_row(42)]
        rows, warnings = extract_check_filling(values, "Июль 2026", 7, 2026)
        assert rows == []
        assert len(warnings) == 1
        assert "не найдена" in warnings[0]


class TestExtractDismissedIds:

    def test_maps_row_indices_to_tg_ids(self):
        values = [
            _month_row(42),
            ["", "", "БАР"] + [""] * 32,
            _month_row(77),
        ]
        assert extract_dismissed_ids(values, {1, 2, 3}) == [42, 77]

    def test_out_of_range_and_phantom_ignored(self):
        values = [_month_row(PHANTOM_CHECK_FILLING_ID)]
        assert extract_dismissed_ids(values, {1, 99}) == []


# ---------------------------------------------------------------------------
# Запись в БД: идемпотентность и защита source
# ---------------------------------------------------------------------------

def _shift(tg_id=42, date="2026-07-01", hours=8.0, ah=0.0, source="import",
           ts=NOW_ISO):
    return {"telegram_id": tg_id, "shift_date": date, "hours": hours,
            "extra_hours": ah, "source": source, "created_at": ts, "updated_at": ts}


def _employee(tg_id=42, status="approved"):
    return {"telegram_id": tg_id, "nickname": "@nick", "full_name": "Иванов",
            "department": "Кухня", "position": "Горячий цех", "custom_position": None,
            "role": "user", "status": status, "registered_at": NOW_ISO}


class TestIdempotency:

    def test_double_import_does_not_duplicate(self, migration_db):
        employees = [_employee(1), _employee(2, status="pending")]
        shifts = [_shift(1, "2026-07-01"), _shift(1, "2026-07-02"), _shift(2, "2026-07-01")]
        checks = [{"fill_date": "2026-07-01", "count": 5}]

        with sqlite3.connect(migration_db) as conn:
            for _ in range(2):  # двойной прогон
                write_employees(conn, employees)
                write_shifts(conn, shifts)
                write_check_filling(conn, checks)
                conn.commit()

            counts = {
                t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("employees", "shifts", "check_filling")
            }
        assert counts == {"employees": 2, "shifts": 3, "check_filling": 1}

    def test_reimport_updates_import_rows(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            write_shifts(conn, [_shift(hours=8.0)])
            write_shifts(conn, [_shift(hours=10.0, ts="2026-07-08T00:00:00")])
            row = conn.execute(
                "SELECT hours, updated_at FROM shifts WHERE telegram_id = 42"
            ).fetchone()
        assert row == (10.0, "2026-07-08T00:00:00")


class TestSourceProtection:

    def test_non_import_shift_not_overwritten(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            # Данные Фазы 2: смена внесена пользователем через бота
            conn.execute(
                "INSERT INTO shifts (telegram_id, shift_date, hours, extra_hours, source, created_at, updated_at) "
                "VALUES (42, '2026-07-01', 12.0, 2.0, 'user', 'orig', 'orig')"
            )
            conn.commit()

            written = write_shifts(conn, [_shift(hours=8.0)])
            conn.commit()

            row = conn.execute(
                "SELECT hours, extra_hours, source, updated_at FROM shifts WHERE telegram_id = 42"
            ).fetchone()
        assert written == 0
        assert row == (12.0, 2.0, "user", "orig")

    @pytest.mark.parametrize("source", ["admin_approve", "admin_edit"])
    def test_all_phase2_sources_protected(self, migration_db, source):
        with sqlite3.connect(migration_db) as conn:
            conn.execute(
                "INSERT INTO shifts (telegram_id, shift_date, hours, source, created_at, updated_at) "
                "VALUES (42, '2026-07-01', 12.0, ?, 'orig', 'orig')", (source,)
            )
            write_shifts(conn, [_shift(hours=8.0)])
            row = conn.execute("SELECT hours, source FROM shifts WHERE telegram_id = 42").fetchone()
        assert row == (12.0, source)


class TestMarkDismissed:

    def test_marks_existing_only(self, migration_db):
        with sqlite3.connect(migration_db) as conn:
            write_employees(conn, [_employee(42)])
            marked = mark_dismissed(conn, [42, 999], NOW_ISO)
            status, dismissed_at = conn.execute(
                "SELECT status, dismissed_at FROM employees WHERE telegram_id = 42"
            ).fetchone()
        assert marked == 1
        assert status == "dismissed"
        assert dismissed_at == NOW_ISO
