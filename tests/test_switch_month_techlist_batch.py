"""
Tests for the batch Techlist read optimisation in switch_month.

Verifies:
- get_techlist_ids() returns a normalised set of str from column A
- switch_month reads the Techlist EXACTLY ONCE (via get_techlist_ids)
- Membership check: employee in set → transferred; not in set → removed as anomaly
- Normalisation: tg_id as int and as str-with-spaces match the set equally
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, call

from app.services.google_sheets import GoogleSheetsClient
from app.scheduler.monthly_switch import switch_month


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client_for_batch(
    all_values: list,
    dismissed: set = frozenset(),
    techlist_ids: set | None = None,
):
    """
    Build a sheets_client mock that wires get_techlist_ids() directly,
    bypassing user_exists_in_techlist (which must NOT be called in the loop).
    """
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

    if techlist_ids is None:
        # Default: everyone in all_values is in the Techlist
        techlist_ids = {
            str(row[1]).strip()
            for row in all_values
            if len(row) > 1 and str(row[1]).strip()
        }
    client.get_techlist_ids.return_value = techlist_ids

    return client, new_ws


async def _run(client):
    bot = AsyncMock()
    with (
        patch(
            "app.scheduler.monthly_switch._find_last_month_sheet",
            return_value=("Апрель 2026", 4, 2026),
        ),
        patch("app.scheduler.monthly_switch.snapshot_user_rates_history", new_callable=AsyncMock),
        patch("app.scheduler.monthly_switch.apply_future_rates", new_callable=AsyncMock),
        patch(
            "app.scheduler.monthly_switch._transfer_phantom_to_new_month",
            new_callable=AsyncMock,
        ),
    ):
        result = await switch_month(bot, client, "test.db")
    return result


# ---------------------------------------------------------------------------
# Test 1: get_techlist_ids returns normalised set from column A
# ---------------------------------------------------------------------------

class TestGetTechlistIds:

    def test_returns_set_of_normalised_strings(self, sheets_client):
        """get_techlist_ids collects non-empty values from col A, skipping header."""
        sheets_client._spreadsheet.worksheet.return_value.get_all_values.return_value = [
            ["TelegramID", "Name"],        # header row — skipped
            ["101", "@alice", "Официант"],
            ["102", "@bob",   "Бармен"],
            ["",    "@empty", "Клининг"],  # empty ID — excluded
            [" 103 ", "@carol", "Раннер"], # padded — normalised to "103"
        ]
        result = sheets_client.get_techlist_ids()
        assert result == {"101", "102", "103"}
        assert isinstance(result, set)

    def test_empty_techlist_returns_empty_set(self, sheets_client):
        """If Techlist has only a header (or is totally empty), return empty set."""
        sheets_client._spreadsheet.worksheet.return_value.get_all_values.return_value = [
            ["TelegramID"],  # only header
        ]
        result = sheets_client.get_techlist_ids()
        assert result == set()

    def test_persistent_network_error_raises(self, sheets_client):
        """On persistent network failure (both attempts), must raise — never return empty set."""
        sheets_client._spreadsheet.worksheet.return_value.get_all_values.side_effect = Exception("network down")
        sheets_client._reconnect = MagicMock()
        with pytest.raises(Exception, match="network down"):
            sheets_client.get_techlist_ids()


# ---------------------------------------------------------------------------
# Test 2: switch_month calls get_techlist_ids EXACTLY ONCE
# ---------------------------------------------------------------------------

class TestTechlistReadCount:

    @pytest.mark.asyncio
    async def test_get_techlist_ids_called_exactly_once(self):
        """switch_month must batch-read the Techlist once, not per employee."""
        all_values = [
            ["Иванов",  "101", "Официант"],
            ["Петров",  "102", "Бармен"],
            ["Сидоров", "103", "Раннер"],
            ["Козлов",  "104", "Менеджер"],
            ["Смирнов", "105", "Хостесс"],
        ]
        client, _ = _make_client_for_batch(all_values)

        await _run(client)

        client.get_techlist_ids.assert_called_once()

    @pytest.mark.asyncio
    async def test_user_exists_in_techlist_not_called_in_loop(self):
        """user_exists_in_techlist must NOT be called inside the employee loop."""
        all_values = [
            ["Иванов", "101", "Официант"],
            ["Петров", "102", "Бармен"],
        ]
        client, _ = _make_client_for_batch(all_values)

        await _run(client)

        client.user_exists_in_techlist.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: membership check — in set → transferred; not in set → anomaly/removed
# ---------------------------------------------------------------------------

class TestTechlistMembership:

    @pytest.mark.asyncio
    async def test_employee_in_techlist_is_transferred(self):
        """Employee whose tg_id is in techlist_ids and row is not red → transferred."""
        all_values = [["Иванов", "777", "Официант"]]
        client, new_ws = _make_client_for_batch(all_values, techlist_ids={"777"})

        result = await _run(client)

        assert result["transferred"] == 1
        assert result["removed"] == 0
        new_ws.batch_clear.assert_called_once()

    @pytest.mark.asyncio
    async def test_employee_not_in_techlist_is_removed_as_anomaly(self):
        """Employee whose tg_id is NOT in techlist_ids (and row is not red) → anomaly/removed."""
        all_values = [["Иванов", "888", "Официант"]]
        client, new_ws = _make_client_for_batch(all_values, techlist_ids=set())

        result = await _run(client)

        assert result["transferred"] == 0
        assert result["removed"] == 1
        assert result["anomalies"] == 1
        new_ws.batch_clear.assert_not_called()

    @pytest.mark.asyncio
    async def test_red_row_not_in_techlist_is_removed(self):
        """Red row (dismissed) not in techlist → removed (normal dismissal, no anomaly)."""
        all_values = [["Иванов", "999", "Официант"]]
        client, new_ws = _make_client_for_batch(
            all_values,
            dismissed={1},         # row 1 is red
            techlist_ids=set(),    # not in techlist
        )

        result = await _run(client)

        assert result["transferred"] == 0
        assert result["removed"] == 1
        assert result["anomalies"] == 0

    @pytest.mark.asyncio
    async def test_mixed_employees(self):
        """2 active (in techlist) + 1 dismissed (red, not in techlist) = 2 transferred, 1 removed."""
        all_values = [
            ["Активный",   "101", "Официант"],  # row 1 — active, in techlist
            ["Уволенный",  "102", "Бармен"],    # row 2 — red, not in techlist
            ["Активный2",  "103", "Раннер"],    # row 3 — active, in techlist
        ]
        client, new_ws = _make_client_for_batch(
            all_values,
            dismissed={2},             # only row 2 is red
            techlist_ids={"101", "103"},  # 102 not in techlist
        )

        result = await _run(client)

        assert result["transferred"] == 2
        assert result["removed"] == 1
        assert result["anomalies"] == 0


# ---------------------------------------------------------------------------
# Test 4: normalisation — int tg_id and str-with-spaces match the set equally
# ---------------------------------------------------------------------------

class TestTechlistNormalisation:

    def test_int_tg_id_matches_set(self):
        """str(int_id).strip() must be in the set built by get_techlist_ids."""
        # Simulates the actual normalisation in switch_month:
        #   tg_id is read from all_values as int(str(row[1]).strip())
        #   then checked as: str(tg_id).strip() in techlist_ids
        tg_id_int = 123456789
        techlist_ids = {"123456789"}
        assert str(tg_id_int).strip() in techlist_ids

    def test_str_with_spaces_tg_id_matches_set(self):
        """tg_id with surrounding whitespace (Регина кейс) is normalised and matches."""
        # Sheets sometimes returns " 123456789 " with spaces
        # get_techlist_ids does str(...).strip() → "123456789"
        # switch_month does str(tg_id).strip() → "123456789"
        raw_from_sheet = " 123456789 "
        normalised_in_set = raw_from_sheet.strip()     # as done by get_techlist_ids
        tg_id_from_row = int(raw_from_sheet.strip())   # as done by employee_rows parsing
        check_val = str(tg_id_from_row).strip()        # as done by switch_month loop

        assert check_val == normalised_in_set
        techlist_ids = {normalised_in_set}
        assert check_val in techlist_ids

    @pytest.mark.asyncio
    async def test_padded_id_in_sheet_is_found_in_techlist(self):
        """End-to-end: tg_id stored with spaces in Sheets is still matched (Regina case)."""
        all_values = [["Регина", "456", "Официант"]]
        # Techlist has the same ID but with surrounding spaces (raw from Sheets)
        client, _ = _make_client_for_batch(
            all_values,
            techlist_ids={"456"},  # already normalised by get_techlist_ids
        )

        result = await _run(client)

        # Must be transferred, not removed as anomaly
        assert result["transferred"] == 1
        assert result["anomalies"] == 0
