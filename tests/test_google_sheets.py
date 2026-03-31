"""
Тесты для app/services/google_sheets.py:
  - GoogleSheetsClient.get_sheet_id_by_name()
  - GoogleSheetsClient.get_section_range()

Все тесты работают без реального доступа к Google Sheets: __init__,
_create_client и _reconnect замокированы через patch.object.
"""
from unittest.mock import MagicMock, patch, call

import pytest

from app.services.google_sheets import GoogleSheetsClient


# ---------------------------------------------------------------------------
# Фикстуры
# ---------------------------------------------------------------------------

def _make_worksheet(title: str, gid: int) -> MagicMock:
    ws = MagicMock()
    ws.title = title
    ws.id = gid
    return ws


@pytest.fixture
def client():
    """
    Создаёт GoogleSheetsClient с замокированным _create_client.
    После создания экземпляра _spreadsheet заменяется чистым MagicMock,
    чтобы каждый тест мог настраивать его поведение независимо.
    """
    mock_gspread_client = MagicMock()
    with patch.object(GoogleSheetsClient, "_create_client", return_value=mock_gspread_client):
        c = GoogleSheetsClient()
    # Заменяем _spreadsheet на свежий mock после инициализации
    c._spreadsheet = MagicMock()
    return c


# ---------------------------------------------------------------------------
# Вспомогательные данные для get_section_range
# ---------------------------------------------------------------------------

# Структура листа (0-based indices):
#   i=0  ["", "", "", "Март", "2026"]        — строка метаданных
#   i=1  ["", "", "", ""]                     — пустая строка
#   i=2  ["", "", "КУХНЯ", "", ""]            — заголовок КУХНЯ  → start_row=3 (1-based)
#   i=3  ["Вася", "", "Горячий цех", ...]     — повар
#   i=4  ["Петя", "", "Холодный цех", ...]    — повар
#   i=5  ["", "", "БАР", "", ""]              — заголовок БАР → end_row=5 для КУХНИ; start_row=6
#   i=6  ["Борис", "", "Бармен", ...]         — бармен
#   i=7  ["", "", "ЗАЛ", "", ""]              — заголовок ЗАЛ → end_row=7 для БАРа; start_row=8
#   i=8  ["Катя", "", "Официант", ...]        — официант
# Итого 9 строк: len=9
#
# Ожидаемые диапазоны:
#   КУХНЯ → "A3:AN5"   (start_row=3, end_row=5)
#   БАР   → "A6:AN7"   (start_row=6, end_row=7)
#   ЗАЛ   → "A8:AN9"   (start_row=8, end_row=9=len)

FAKE_ALL_VALUES = [
    ["", "", "", "Март", "2026"],
    ["", "", "", ""],
    ["", "", "КУХНЯ", "", ""],
    ["Вася", "", "Горячий цех", "", ""],
    ["Петя", "", "Холодный цех", "", ""],
    ["", "", "БАР", "", ""],
    ["Борис", "", "Бармен", "", ""],
    ["", "", "ЗАЛ", "", ""],
    ["Катя", "", "Официант", "", ""],
]


# ---------------------------------------------------------------------------
# get_sheet_id_by_name
# ---------------------------------------------------------------------------

class TestGetSheetIdByName:
    def test_returns_id_for_existing_sheet(self, client):
        """Возвращает числовой gid для существующего листа."""
        client._spreadsheet.worksheets.return_value = [
            _make_worksheet("Февраль 2026", 111111),
            _make_worksheet("Март 2026", 222222),
        ]

        result = client.get_sheet_id_by_name("Март 2026")

        assert result == 222222

    def test_returns_none_for_missing_sheet(self, client):
        """Возвращает None, если листа с таким именем нет."""
        client._spreadsheet.worksheets.return_value = [
            _make_worksheet("Февраль 2026", 111111),
        ]

        result = client.get_sheet_id_by_name("Январь 2026")

        assert result is None

    def test_exact_name_match_is_case_sensitive(self, client):
        """Сопоставление по названию регистрозависимо."""
        client._spreadsheet.worksheets.return_value = [
            _make_worksheet("март 2026", 333333),
        ]

        result = client.get_sheet_id_by_name("Март 2026")

        assert result is None

    def test_returns_first_matching_id_when_unique(self, client):
        """При наличии нескольких листов возвращает gid нужного."""
        sheets = [
            _make_worksheet("Январь 2026", 10),
            _make_worksheet("Февраль 2026", 20),
            _make_worksheet("Март 2026", 30),
            _make_worksheet("Апрель 2026", 40),
        ]
        client._spreadsheet.worksheets.return_value = sheets

        assert client.get_sheet_id_by_name("Январь 2026") == 10
        assert client.get_sheet_id_by_name("Апрель 2026") == 40

    def test_reconnects_and_retries_on_api_error(self, client):
        """При ошибке API вызывает _reconnect и повторяет запрос."""
        good_ws = _make_worksheet("Март 2026", 55555)
        client._spreadsheet.worksheets.side_effect = [
            Exception("API error"),
            [good_ws],
        ]

        with patch.object(client, "_reconnect") as mock_reconnect:
            result = client.get_sheet_id_by_name("Март 2026")

        mock_reconnect.assert_called_once()
        assert result == 55555

    def test_empty_spreadsheet_returns_none(self, client):
        """Если листов нет совсем — возвращает None."""
        client._spreadsheet.worksheets.return_value = []

        result = client.get_sheet_id_by_name("Март 2026")

        assert result is None

    def test_cyrillic_sheet_name(self, client):
        """Кириллическое название листа ('Март 2026') распознаётся корректно."""
        client._spreadsheet.worksheets.return_value = [
            _make_worksheet("Март 2026", 98765),
        ]

        result = client.get_sheet_id_by_name("Март 2026")

        assert result == 98765


# ---------------------------------------------------------------------------
# get_section_range
# ---------------------------------------------------------------------------

class TestGetSectionRange:
    def _setup_ws(self, client, rows):
        """Вспомогательный метод: настраивает мок ws.get_all_values()."""
        ws = MagicMock()
        ws.get_all_values.return_value = rows
        client._spreadsheet.worksheet.return_value = ws

    def test_returns_range_for_kitchen(self, client):
        """КУХНЯ: диапазон от заголовка до строки перед следующим отделом."""
        self._setup_ws(client, FAKE_ALL_VALUES)

        result = client.get_section_range("Март 2026", "КУХНЯ")

        assert result == "A3:AN5"

    def test_returns_range_for_bar(self, client):
        """БАР: диапазон между заголовком БАР и заголовком ЗАЛ."""
        self._setup_ws(client, FAKE_ALL_VALUES)

        result = client.get_section_range("Март 2026", "БАР")

        assert result == "A6:AN7"

    def test_returns_range_for_hall_to_end_of_sheet(self, client):
        """ЗАЛ: последний отдел — end_row равен общей длине листа."""
        self._setup_ws(client, FAKE_ALL_VALUES)

        result = client.get_section_range("Март 2026", "ЗАЛ")

        assert result == "A8:AN9"

    def test_returns_none_for_missing_department(self, client):
        """Несуществующий отдел — возвращает None."""
        self._setup_ws(client, FAKE_ALL_VALUES)

        result = client.get_section_range("Март 2026", "МОП")

        assert result is None

    def test_case_insensitive_search(self, client):
        """Поиск нечувствителен к регистру заголовка отдела."""
        rows = [
            ["", "", "", ""],
            ["", "", "кухня", "", ""],   # строчные буквы
            ["Вася", "", "Горячий цех"],
        ]
        self._setup_ws(client, rows)

        result = client.get_section_range("Март 2026", "КУХНЯ")

        assert result is not None
        assert result.startswith("A2:")

    def test_result_is_a1_notation(self, client):
        """Возвращаемый диапазон соответствует формату A1-нотации."""
        self._setup_ws(client, FAKE_ALL_VALUES)

        result = client.get_section_range("Март 2026", "КУХНЯ")

        assert result is not None
        # Формат: A{start}:AN{end}
        import re
        assert re.fullmatch(r"A\d+:AN\d+", result), f"Неверный формат: {result}"

    def test_last_col_is_an(self, client):
        """Правая граница диапазона всегда AN (колонка 40)."""
        self._setup_ws(client, FAKE_ALL_VALUES)

        for dept in ("КУХНЯ", "БАР", "ЗАЛ"):
            result = client.get_section_range("Март 2026", dept)
            assert result is not None
            assert ":AN" in result, f"Нет AN для {dept}: {result}"

    def test_reconnects_and_retries_on_api_error(self, client):
        """При ошибке API вызывает _reconnect и повторяет запрос."""
        ws_ok = MagicMock()
        ws_ok.get_all_values.return_value = FAKE_ALL_VALUES
        client._spreadsheet.worksheet.side_effect = [
            Exception("Connection reset"),
            ws_ok,
        ]

        with patch.object(client, "_reconnect") as mock_reconnect:
            result = client.get_section_range("Март 2026", "БАР")

        mock_reconnect.assert_called_once()
        assert result == "A6:AN7"

    def test_empty_sheet_returns_none(self, client):
        """Пустой лист (нет строк) — возвращает None для любого отдела."""
        self._setup_ws(client, [])

        result = client.get_section_range("Март 2026", "КУХНЯ")

        assert result is None

    def test_only_one_department_spans_full_sheet(self, client):
        """Единственный отдел на листе — end_row равен числу строк."""
        rows = [
            ["", "", "", ""],
            ["", "", "ЗАЛ", "", ""],
            ["Катя", "", "Официант"],
            ["Лена", "", "Хостесс"],
        ]
        self._setup_ws(client, rows)

        result = client.get_section_range("Март 2026", "ЗАЛ")

        assert result == "A2:AN4"

    def test_department_header_must_have_empty_first_two_cells(self, client):
        """
        Строка считается заголовком отдела только если ячейки A и B пусты.
        Строка вида ['ЗАЛ', '', '', ''] не должна распознаваться как заголовок.
        """
        rows = [
            ["ЗАЛ", "", "что-то", ""],    # cell_a не пуста → не заголовок
            ["", "ЗАЛ", "", ""],           # cell_b не пуста → не заголовок
            ["", "", "ЗАЛ", ""],           # настоящий заголовок
            ["Катя", "", "Официант"],
        ]
        self._setup_ws(client, rows)

        result = client.get_section_range("Март 2026", "ЗАЛ")

        # Только строка i=2 является корректным заголовком → start_row=3
        assert result == "A3:AN4"
