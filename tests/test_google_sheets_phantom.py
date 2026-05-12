"""Тесты функций write_check_filling_to_phantom и get_phantom_checks_summary."""
from unittest.mock import MagicMock, patch

import gspread.utils
import pytest

from app.services.google_sheets import GoogleSheetsClient
from config import PHANTOM_CHECK_FILLING_ID


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def _make_client() -> GoogleSheetsClient:
    client = object.__new__(GoogleSheetsClient)
    client._spreadsheet = MagicMock()
    client._client = MagicMock()
    return client


def _make_sheet_with_phantom(phantom_row_idx: int = 5) -> tuple[MagicMock, list]:
    """Возвращает (mock_ws, all_values) с фантомом на указанной строке (1-based)."""
    all_values = []
    for i in range(1, phantom_row_idx + 5):
        if i == phantom_row_idx:
            row = ["Наполняемость чека", str(PHANTOM_CHECK_FILLING_ID), "Официант"] + [""] * 38
        else:
            row = ["Иванов", "12345", "Официант"] + [""] * 38
        all_values.append(row)

    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = all_values
    return mock_ws, all_values


# ---------------------------------------------------------------------------
# Tests: write_check_filling_to_phantom
# ---------------------------------------------------------------------------

class TestWriteCheckFillingToPhantom:

    def test_write_check_filling_basic(self):
        """Пустая ячейка + 3 чека → записывает '3'."""
        client = _make_client()
        mock_ws, _ = _make_sheet_with_phantom(phantom_row_idx=5)
        mock_ws.cell.return_value.value = ""
        client._spreadsheet.worksheet.return_value = mock_ws

        result = client.write_check_filling_to_phantom("01.05.26", 3)

        assert result is True
        mock_ws.update.assert_called_once()
        args = mock_ws.update.call_args
        assert args[0][0] == [[3]]

    def test_write_check_filling_summation(self):
        """Ячейка уже содержит '2', добавляем 3 → записывает '5'."""
        client = _make_client()
        mock_ws, _ = _make_sheet_with_phantom(phantom_row_idx=5)
        mock_ws.cell.return_value.value = "2"
        client._spreadsheet.worksheet.return_value = mock_ws

        result = client.write_check_filling_to_phantom("01.05.26", 3)

        assert result is True
        args = mock_ws.update.call_args
        assert args[0][0] == [[5]]

    def test_write_check_filling_not_found(self):
        """Фантом не найден в листе → возвращает False."""
        client = _make_client()
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            ["Иванов", "11111", "Официант"] + [""] * 5,
            ["Петров", "22222", "Раннер"] + [""] * 5,
        ]
        client._spreadsheet.worksheet.return_value = mock_ws

        result = client.write_check_filling_to_phantom("01.05.26", 2)

        assert result is False
        mock_ws.update.assert_not_called()

    def test_write_check_filling_day_col_first_half(self):
        """День 1 → колонка 4 (D), день 15 → колонка 18 (R)."""
        client = _make_client()
        mock_ws, _ = _make_sheet_with_phantom(phantom_row_idx=5)
        mock_ws.cell.return_value.value = ""
        client._spreadsheet.worksheet.return_value = mock_ws

        client.write_check_filling_to_phantom("01.05.26", 1)
        _, col_day1 = gspread.utils.a1_to_rowcol(mock_ws.update.call_args[0][1])
        assert col_day1 == 4  # 3 + 1

        mock_ws.reset_mock()
        mock_ws.cell.return_value.value = ""
        client.write_check_filling_to_phantom("15.05.26", 1)
        _, col_day15 = gspread.utils.a1_to_rowcol(mock_ws.update.call_args[0][1])
        assert col_day15 == 18  # 3 + 15

    def test_write_check_filling_day_col_second_half(self):
        """День 16 → колонка 20 (T), день 31 → колонка 35 (AI)."""
        client = _make_client()
        mock_ws, _ = _make_sheet_with_phantom(phantom_row_idx=5)
        mock_ws.cell.return_value.value = ""
        client._spreadsheet.worksheet.return_value = mock_ws

        client.write_check_filling_to_phantom("16.05.26", 1)
        _, col_day16 = gspread.utils.a1_to_rowcol(mock_ws.update.call_args[0][1])
        assert col_day16 == 20  # 19 + (16-15) = 20

        mock_ws.reset_mock()
        mock_ws.cell.return_value.value = ""
        client.write_check_filling_to_phantom("31.05.26", 1)
        _, col_day31 = gspread.utils.a1_to_rowcol(mock_ws.update.call_args[0][1])
        assert col_day31 == 35  # 19 + (31-15) = 35


# ---------------------------------------------------------------------------
# Tests: get_phantom_checks_summary
# ---------------------------------------------------------------------------

class TestGetPhantomChecksSummary:

    def _setup_ws(self, cell_value: str, phantom_row_idx: int = 5) -> tuple:
        client = _make_client()
        mock_ws, _ = _make_sheet_with_phantom(phantom_row_idx=phantom_row_idx)
        mock_ws.cell.return_value.value = cell_value
        client._spreadsheet.worksheet.return_value = mock_ws
        return client, mock_ws

    def test_get_phantom_checks_first(self):
        """period='first' → читает колонку 19 (S)."""
        client, mock_ws = self._setup_ws("47")

        result = client.get_phantom_checks_summary("first")

        assert result == 47
        col_called = mock_ws.cell.call_args[0][1]
        assert col_called == 19

    def test_get_phantom_checks_second(self):
        """period='second' → читает колонку 36 (AJ)."""
        client, mock_ws = self._setup_ws("23")

        result = client.get_phantom_checks_summary("second")

        assert result == 23
        col_called = mock_ws.cell.call_args[0][1]
        assert col_called == 36

    def test_get_phantom_checks_last(self):
        """period='last' → читает колонку 37 (AK) прошлого месяца."""
        client, mock_ws = self._setup_ws("15")

        with patch("app.services.google_sheets.datetime") as mock_dt:
            mock_now = MagicMock()
            mock_now.month = 5
            mock_now.year = 2026
            mock_dt.now.return_value = mock_now

            result = client.get_phantom_checks_summary("last")

        assert result == 15
        col_called = mock_ws.cell.call_args[0][1]
        assert col_called == 37

    def test_get_phantom_checks_not_found(self):
        """Фантом не найден → возвращает 0."""
        client = _make_client()
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            ["Иванов", "11111", "Официант"] + [""] * 5,
        ]
        client._spreadsheet.worksheet.return_value = mock_ws

        result = client.get_phantom_checks_summary("first")

        assert result == 0

    def test_get_phantom_checks_float_value(self):
        """Значение '47.0' (формула) → парсится в 47."""
        client, _ = self._setup_ws("47.0")
        result = client.get_phantom_checks_summary("second")
        assert result == 47
