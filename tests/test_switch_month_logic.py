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
    client.user_exists_in_techlist.return_value = in_techlist

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
        """Three active employees (in techlist, not red) are all cleared and counted."""
        all_values = [
            ["Иванов", "101", "Официант"],
            ["Петров", "102", "Бармен"],
            ["Сидоров", "103", "Раннер"],
        ]
        client, new_ws = _make_sheets_client(all_values, dismissed=set(), in_techlist=True)

        result, _ = await _run_switch_month(client)

        assert result["transferred"] == 3
        assert new_ws.batch_clear.call_count == 3

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
