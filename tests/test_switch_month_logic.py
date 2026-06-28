"""Tests for switch_month row-classification logic and get_dismissed_rows."""
import logging

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.scheduler.monthly_switch import switch_month


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_sheets_client(all_values: list, dismissed: set = frozenset(), in_techlist: bool = True):
    """Build a minimal sheets_client mock suitable for switch_month tests."""
    source_ws = MagicMock()
    source_ws.id = 88

    new_ws = MagicMock()
    new_ws.get_all_values.return_value = all_values
    new_ws.id = 99
    new_ws.title = "Май 2026"
    new_ws.col_count = 40

    existing_sheet = MagicMock()
    existing_sheet.title = "Апрель 2026"

    client = MagicMock()
    client._spreadsheet.worksheets.return_value = [existing_sheet]
    client._spreadsheet.worksheet.return_value = source_ws
    client._spreadsheet.duplicate_sheet.return_value = new_ws
    client.get_dismissed_rows.return_value = set(dismissed)

    # Build techlist_ids set from all_values (column B, index 1)
    tg_ids = {str(row[1]).strip() for row in all_values if len(row) > 1 and str(row[1]).strip()}
    client.get_techlist_ids.return_value = tg_ids if in_techlist else set()

    return client, new_ws


async def _run_switch_month(client):
    """Execute switch_month with all external dependencies patched out."""
    bot = AsyncMock()
    with (
        patch(
            "app.scheduler.monthly_switch._find_last_month_sheet",
            return_value=("Апрель 2026", 4, 2026),
        ),
        patch(
            "app.scheduler.monthly_switch.snapshot_user_rates_history",
            new_callable=AsyncMock,
        ),
        patch(
            "app.scheduler.monthly_switch.apply_future_rates",
            new_callable=AsyncMock,
        ),
        patch(
            "app.scheduler.monthly_switch._transfer_phantom_to_new_month",
            new_callable=AsyncMock,
        ) as mock_transfer,
    ):
        result = await switch_month(bot, client, "test.db")

    return result, mock_transfer


# ---------------------------------------------------------------------------
# Tests: get_dismissed_rows — red-row detection
# ---------------------------------------------------------------------------

class TestGetDismissedRows:

    def test_dismissed_rows_excluded(self, sheets_client):
        """Row with #FFCCCC background (r≥0.95, g≤0.85) is included; white rows are not."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "sheets": [{
                "data": [{
                    "rowData": [
                        {
                            "values": [{
                                "effectiveFormat": {
                                    "backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}
                                }
                            }]
                        },
                        {
                            "values": [{
                                "effectiveFormat": {
                                    "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
                                }
                            }]
                        },
                    ]
                }]
            }]
        }
        sheets_client._client.http_client.request.return_value = mock_resp

        result = sheets_client.get_dismissed_rows("Апрель 2026")

        assert 1 in result       # red row is dismissed
        assert 2 not in result   # white row is not dismissed


# ---------------------------------------------------------------------------
# Tests: switch_month — employee row classification
# ---------------------------------------------------------------------------

class TestSwitchMonthLogic:

    @pytest.mark.asyncio
    async def test_anomaly_row_skipped_with_warning(self, caplog):
        """Row with empty telegram_id column (B) is skipped and a warning is logged."""
        all_values = [
            ["NoId", "", "Официант"],          # B empty → warning + skip
            ["ValidUser", "101", "Официант"],   # valid active employee
        ]
        client, _ = _make_sheets_client(all_values)

        with caplog.at_level(logging.WARNING):
            result, _ = await _run_switch_month(client)

        assert "нет TG_ID" in caplog.text
        assert result["transferred"] == 1

    @pytest.mark.asyncio
    async def test_active_rows_transferred(self):
        """Three active employees: counted as transferred, cleared via one batch_clear."""
        all_values = [
            ["Иванов", "101", "Официант"],
            ["Петров", "102", "Бармен"],
            ["Сидоров", "103", "Раннер"],
        ]
        client, new_ws = _make_sheets_client(all_values, dismissed=set(), in_techlist=True)

        result, _ = await _run_switch_month(client)

        assert result["transferred"] == 3
        # After batching: exactly 1 batch_clear with 2 ranges per row = 6 total
        assert new_ws.batch_clear.call_count == 1
        ranges = new_ws.batch_clear.call_args[0][0]
        assert len(ranges) == 6

    @pytest.mark.asyncio
    async def test_phantom_transferred(self):
        """_transfer_phantom_to_new_month is called with correct sheet names after processing."""
        all_values = [["ActiveUser", "101", "Официант"]]
        client, _ = _make_sheets_client(all_values)

        result, mock_transfer = await _run_switch_month(client)

        mock_transfer.assert_called_once()
        positional_args = mock_transfer.call_args[0]
        assert positional_args[1] == "Апрель 2026"  # current (old) sheet
        assert positional_args[2] == "Май 2026"     # next (new) sheet


# ---------------------------------------------------------------------------
# Tests: Шаг 2 — батч-очистка смен
# ---------------------------------------------------------------------------

class TestBatchClearAndFormulas:

    @pytest.mark.asyncio
    async def test_batch_clear_single_call_with_all_ranges(self):
        """N активных сотрудников → ровно 1 вызов batch_clear, 2N диапазонов в аргументе."""
        all_values = [
            ["Иванов", "101", "Официант"],
            ["Петров", "102", "Бармен"],
            ["Сидоров", "103", "Раннер"],
        ]
        client, new_ws = _make_sheets_client(all_values, dismissed=set(), in_techlist=True)

        await _run_switch_month(client)

        assert new_ws.batch_clear.call_count == 1
        ranges = new_ws.batch_clear.call_args[0][0]
        # 3 сотрудника × 2 диапазона каждый = 6
        assert len(ranges) == 6
        # Каждая строка сотрудника (1, 2, 3) должна быть в диапазонах
        for row_idx in (1, 2, 3):
            assert f"D{row_idx}:R{row_idx}" in ranges
            assert f"T{row_idx}:AI{row_idx}" in ranges

    @pytest.mark.asyncio
    async def test_batch_update_single_call_user_entered(self):
        """Формулы пишутся одним batch_update с value_input_option=USER_ENTERED."""
        all_values = [
            ["Иванов", "101", "Официант"],
            ["Петров", "102", "Бармен"],
        ]
        client, new_ws = _make_sheets_client(all_values, dismissed=set(), in_techlist=True)

        await _run_switch_month(client)

        assert new_ws.batch_update.call_count == 1
        _, kwargs = new_ws.batch_update.call_args
        assert kwargs.get("value_input_option") == "USER_ENTERED"

    @pytest.mark.asyncio
    async def test_formulas_use_ru_sumproduct(self):
        """Формулы S и AJ содержат СУММПРОИЗВ (не SUM / не английские формулы)."""
        all_values = [["Иванов", "101", "Официант"]]
        client, new_ws = _make_sheets_client(all_values, dismissed=set(), in_techlist=True)

        await _run_switch_month(client)

        updates = new_ws.batch_update.call_args[0][0]
        s_formula = next(item["values"][0][0] for item in updates if item["range"].startswith("S"))
        aj_formula = next(item["values"][0][0] for item in updates if item["range"].startswith("AJ"))
        # AK combines S+AJ — не содержит СУММПРОИЗВ, это нормально
        assert "СУММПРОИЗВ" in s_formula
        assert "СУММПРОИЗВ" in aj_formula

    @pytest.mark.asyncio
    async def test_simple_formula_for_kitchen_position(self):
        """Позиции из _SIMPLE_H_POSITIONS (Горячий цех) получают простую формулу S (без '/')."""
        all_values = [["Кузнецов", "201", "Горячий цех"]]
        client, new_ws = _make_sheets_client(all_values, dismissed=set(), in_techlist=True)

        await _run_switch_month(client)

        updates = new_ws.batch_update.call_args[0][0]
        s_formula = next(item["values"][0][0] for item in updates if item["range"].startswith("S"))
        # Простая формула: нет конкатенации "/" (только суммирование)
        assert "&" not in s_formula
        assert "СУММПРОИЗВ" in s_formula

    @pytest.mark.asyncio
    async def test_complex_formula_for_hall_position(self):
        """Официант (Зал) получает сложную формулу S с конкатенацией '/'."""
        all_values = [["Иванов", "101", "Официант"]]
        client, new_ws = _make_sheets_client(all_values, dismissed=set(), in_techlist=True)

        await _run_switch_month(client)

        updates = new_ws.batch_update.call_args[0][0]
        s_formula = next(item["values"][0][0] for item in updates if item["range"].startswith("S"))
        # Сложная формула: содержит & "/" (конкатенация H/AH)
        assert '&"/"&' in s_formula
        assert "СУММПРОИЗВ" in s_formula

    @pytest.mark.asyncio
    async def test_no_clear_when_no_active_employees(self):
        """Нет активных сотрудников → batch_clear и batch_update не вызываются."""
        all_values = [["Уволенный", "999", "Официант"]]
        client, new_ws = _make_sheets_client(all_values, dismissed={1}, in_techlist=False)

        await _run_switch_month(client)

        new_ws.batch_clear.assert_not_called()
        new_ws.batch_update.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: Шаг 3 — батч-удаление строк
# ---------------------------------------------------------------------------

def _find_delete_call(client):
    """Находит вызов _spreadsheet.batch_update с deleteDimension запросами."""
    for c in client._spreadsheet.batch_update.call_args_list:
        body = c[0][0] if c[0] else {}
        if any("deleteDimension" in r for r in body.get("requests", [])):
            return body["requests"]
    return None


class TestBatchRowDeletion:

    @pytest.mark.asyncio
    async def test_rows_deleted_in_single_batch_update(self):
        """N строк к удалению → ровно один batch_update с deleteDimension."""
        all_values = [
            ["Уволен1", "101", "Официант"],
            ["Уволен2", "102", "Бармен"],
            ["Уволен3", "103", "Раннер"],
        ]
        client, _ = _make_sheets_client(all_values, dismissed={1, 2, 3}, in_techlist=False)

        await _run_switch_month(client)

        requests = _find_delete_call(client)
        assert requests is not None, "deleteDimension batch_update не вызван"
        assert len(requests) == 3

    @pytest.mark.asyncio
    async def test_delete_indices_descending_order(self):
        """deleteDimension запросы идут от бо́льших индексов к меньшим — нет сдвига."""
        # Rows 1 и 3 уволены (красные) + в техлисте → аномалия → удалить.
        # Row 2 не уволен + в техлисте → перенести.
        all_values = [
            ["Уволен1", "101", "Официант"],   # row 1 — dismissed anomaly
            ["Активный", "102", "Бармен"],    # row 2 — active
            ["Уволен3", "103", "Раннер"],     # row 3 — dismissed anomaly
        ]
        client, _ = _make_sheets_client(all_values, dismissed={1, 3}, in_techlist=True)

        await _run_switch_month(client)

        requests = _find_delete_call(client)
        assert requests is not None
        # Индексы должны убывать: row 3 → startIndex=2, row 1 → startIndex=0
        start_indices = [r["deleteDimension"]["range"]["startIndex"] for r in requests]
        assert start_indices == sorted(start_indices, reverse=True)

    @pytest.mark.asyncio
    async def test_delete_uses_new_ws_sheet_id(self):
        """sheetId в deleteDimension совпадает с id нового листа."""
        all_values = [["Уволен", "101", "Официант"]]
        client, new_ws = _make_sheets_client(all_values, dismissed={1}, in_techlist=False)
        new_ws.id = 42  # явно зададим

        await _run_switch_month(client)

        requests = _find_delete_call(client)
        assert requests is not None
        for req in requests:
            assert req["deleteDimension"]["range"]["sheetId"] == 42

    @pytest.mark.asyncio
    async def test_no_delete_when_no_rows_to_delete(self):
        """Нет строк к удалению → deleteDimension batch_update не вызывается."""
        all_values = [["Активный", "101", "Официант"]]
        client, _ = _make_sheets_client(all_values, dismissed=set(), in_techlist=True)

        await _run_switch_month(client)

        requests = _find_delete_call(client)
        assert requests is None

    @pytest.mark.asyncio
    async def test_startindex_is_zero_based(self):
        """startIndex для строки N (1-based) должен быть N-1 (0-based)."""
        # Row 1 — active (не уволен, в техлисте). Row 2 — уволен + в техлисте → аномалия → удалить.
        all_values = [
            ["Активный", "101", "Официант"],  # row 1 — active
            ["Уволен",   "102", "Бармен"],    # row 2 — dismissed anomaly
        ]
        client, _ = _make_sheets_client(all_values, dismissed={2}, in_techlist=True)

        await _run_switch_month(client)

        requests = _find_delete_call(client)
        assert requests is not None and len(requests) == 1
        dim_range = requests[0]["deleteDimension"]["range"]
        assert dim_range["startIndex"] == 1   # row 2 → 0-based index 1
        assert dim_range["endIndex"] == 2
