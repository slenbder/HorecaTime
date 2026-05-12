from unittest.mock import MagicMock, patch
import pytest

from app.services.google_sheets import GoogleSheetsClient


# ---------------------------------------------------------------------------
# Factory — создаёт GoogleSheetsClient без реального подключения
# ---------------------------------------------------------------------------

def _make_client() -> GoogleSheetsClient:
    """Создаёт экземпляр GoogleSheetsClient без вызова __init__."""
    client = object.__new__(GoogleSheetsClient)
    client._spreadsheet = MagicMock()
    client._client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Helpers — строим фиктивный лист с заголовками отделов
# ---------------------------------------------------------------------------

def _make_all_values(*dept_rows: tuple[int, str]) -> list[list[str]]:
    """
    Возвращает список строк длиной max_row.
    dept_rows: (row_index_0based, dept_name) — строка-заголовок отдела.
    Заголовок: A="", B="", C=dept_name.
    Остальные строки содержат данные сотрудников (A непустой).
    """
    if not dept_rows:
        return [["Иванов", "Официант", "8"]] * 10

    max_idx = max(idx for idx, _ in dept_rows)
    rows: list[list[str]] = []
    dept_positions = {idx for idx, _ in dept_rows}

    for i in range(max_idx + 10):
        if i in dept_positions:
            dept_name = next(name for idx, name in dept_rows if idx == i)
            rows.append(["", "", dept_name, "", ""])
        else:
            rows.append(["Иванов", "Официант", "8", "", ""])
    return rows


# ---------------------------------------------------------------------------
# Tests: get_section_range
# ---------------------------------------------------------------------------

class TestGetSectionRange:

    def test_get_section_range_found(self):
        """Заголовок "ЗАЛ" на строке 5 → возвращает диапазон, начинающийся с A5."""
        client = _make_client()

        # Заголовок "зал" на индексе 4 (1-based = строка 5)
        all_values = _make_all_values((4, "зал"))
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = all_values
        client._spreadsheet.worksheet.return_value = mock_ws

        result = client.get_section_range("Март 2026", "Зал")

        assert result is not None
        # Диапазон должен начинаться с A5
        assert result.startswith("A5:")

    def test_get_section_range_not_found(self):
        """Отдел отсутствует → возвращает None."""
        client = _make_client()

        # Строки содержат данные, но НЕТ заголовка "зал"
        all_values = [["Иванов", "Официант", "8"]] * 15
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = all_values
        client._spreadsheet.worksheet.return_value = mock_ws

        result = client.get_section_range("Март 2026", "Зал")

        assert result is None

    def test_get_section_range_multiple_sections(self):
        """Два отдела: "зал" на строке 5, "бар" на строке 20 → возвращает блок ЗАЛа."""
        client = _make_client()

        # зал — индекс 4 (строка 5), бар — индекс 19 (строка 20)
        all_values = _make_all_values((4, "зал"), (19, "бар"))
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = all_values
        client._spreadsheet.worksheet.return_value = mock_ws

        result = client.get_section_range("Март 2026", "Зал")

        assert result is not None
        # Блок ЗАЛа: A5 → до строки 19 (перед БАРом)
        assert result.startswith("A5:")
        # Не захватывает строку БАРа (end_row = 19 в 1-based → "AN19")
        assert result.endswith(":AN19")


# ---------------------------------------------------------------------------
# Tests: get_sheet_id_by_name
# ---------------------------------------------------------------------------

class TestGetSheetIdByName:

    def _make_worksheet(self, title: str, sheet_id: int) -> MagicMock:
        ws = MagicMock()
        ws.title = title
        ws.id = sheet_id
        return ws

    def test_get_sheet_id_found(self):
        """Лист "Март 2026" существует → возвращает его id=123456."""
        client = _make_client()
        client._spreadsheet.worksheets.return_value = [
            self._make_worksheet("Февраль 2026", 111),
            self._make_worksheet("Март 2026", 123456),
            self._make_worksheet("Апрель 2026", 999),
        ]

        result = client.get_sheet_id_by_name("Март 2026")

        assert result == 123456

    def test_get_sheet_id_not_found(self):
        """Нужного листа нет → возвращает None."""
        client = _make_client()
        client._spreadsheet.worksheets.return_value = [
            self._make_worksheet("Февраль 2026", 111),
            self._make_worksheet("Апрель 2026", 999),
        ]

        result = client.get_sheet_id_by_name("Несуществующий месяц")

        assert result is None

    def test_get_sheet_id_empty_list(self):
        """Пустой список листов → возвращает None без исключения."""
        client = _make_client()
        client._spreadsheet.worksheets.return_value = []

        result = client.get_sheet_id_by_name("Март 2026")

        assert result is None


# ---------------------------------------------------------------------------
# Tests: get_summary_hours — _parse_cell locale handling
# ---------------------------------------------------------------------------

def _make_summary_row(s_val: str, aj_val: str = "0", ak_val: str = "0") -> list[str]:
    """Строка листа: B=telegram_id, S(19)=s_val, AJ(36)=aj_val, AK(37)=ak_val."""
    row = [""] * 43
    row[1] = "99999"    # telegram_id
    row[18] = s_val     # S (col 19, index 18)
    row[35] = aj_val    # AJ (col 36, index 35)
    row[36] = ak_val    # AK (col 37, index 36)
    return row


class TestGetSummaryHoursParseCell:

    def _run(self, s_val: str, aj_val: str = "0", ak_val: str = "0"):
        client = _make_client()
        mock_ws = MagicMock()
        mock_ws.get_all_values.return_value = [
            _make_summary_row(s_val, aj_val, ak_val)
        ]
        client._spreadsheet.worksheet.return_value = mock_ws
        return client.get_summary_hours(99999, "Май 2026")

    def test_parse_cell_dot_decimal(self):
        """'8/1.5' (точка) → h_first=8.0, ah_first=1.5."""
        result = self._run("8/1.5")
        assert result["h_first"] == 8.0
        assert result["ah_first"] == 1.5

    def test_parse_cell_comma_decimal_russian_locale(self):
        """'8/1,5' (запятая, русская локаль) → h_first=8.0, ah_first=1.5."""
        result = self._run("8/1,5")
        assert result["h_first"] == 8.0
        assert result["ah_first"] == 1.5

    def test_parse_cell_zero_ah(self):
        """'8/0' → h_first=8.0, ah_first=0.0."""
        result = self._run("8/0")
        assert result["h_first"] == 8.0
        assert result["ah_first"] == 0.0

    def test_parse_cell_plain_number(self):
        """'8' (без слэша) → h_first=8.0, ah_first=0.0."""
        result = self._run("8")
        assert result["h_first"] == 8.0
        assert result["ah_first"] == 0.0

    def test_parse_cell_empty(self):
        """Пустая ячейка → h_first=0.0, ah_first=0.0."""
        result = self._run("")
        assert result["h_first"] == 0.0
        assert result["ah_first"] == 0.0

    def test_parse_cell_comma_both_parts(self):
        """'8,5/1,5' → h_first=8.5, ah_first=1.5."""
        result = self._run("8,5/1,5")
        assert result["h_first"] == 8.5
        assert result["ah_first"] == 1.5
