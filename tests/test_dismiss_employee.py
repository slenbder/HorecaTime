"""Tests for dismiss_employee and get_dismissed_rows."""
from unittest.mock import MagicMock, patch

import pytest

from app.services.google_sheets import GoogleSheetsClient


class TestDismissEmployee:

    def test_dismiss_colors_cell_red(self, sheets_client):
        """dismiss_employee formats cell A<row> with #FFCCCC for the matched telegram_id."""
        month_ws = MagicMock()
        month_ws.get_all_values.return_value = [
            ["OtherUser", "1", "Официант"],
            ["OtherUser2", "2", "Раннер"],
            ["TestUser", "123", "Бармен"],   # row 3 (1-based)
        ]
        tech_ws = MagicMock()
        tech_ws.get_all_values.return_value = []

        with (
            patch.object(sheets_client, "_get_current_month_worksheet", return_value=month_ws),
            patch.object(sheets_client, "_get_techlist_worksheet", return_value=tech_ws),
        ):
            sheets_client.dismiss_employee(123)

        month_ws.format.assert_called_once_with(
            "A3",
            {"backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}},
        )

    def test_dismiss_deletes_from_techlist(self, sheets_client):
        """dismiss_employee calls delete_rows with the correct 1-based row index."""
        month_ws = MagicMock()
        month_ws.get_all_values.return_value = [["TestUser", "123", "Бармен"]]

        tech_ws = MagicMock()
        tech_ws.get_all_values.return_value = [
            ["99"],          # row 1 — no match (column A = telegram_id)
            ["456", "@x"],   # row 2 — no match
            ["123", "@t"],   # row 3 — matches!
        ]

        with (
            patch.object(sheets_client, "_get_current_month_worksheet", return_value=month_ws),
            patch.object(sheets_client, "_get_techlist_worksheet", return_value=tech_ws),
        ):
            sheets_client.dismiss_employee(123)

        tech_ws.delete_rows.assert_called_once_with(3)

    def test_dismiss_user_not_found_no_error(self, sheets_client):
        """dismiss_employee with an unknown telegram_id completes without raising."""
        month_ws = MagicMock()
        month_ws.get_all_values.return_value = [
            ["User1", "1", "Официант"],
            ["User2", "2", "Раннер"],
        ]
        tech_ws = MagicMock()
        tech_ws.get_all_values.return_value = [["1"], ["2"]]

        with (
            patch.object(sheets_client, "_get_current_month_worksheet", return_value=month_ws),
            patch.object(sheets_client, "_get_techlist_worksheet", return_value=tech_ws),
        ):
            sheets_client.dismiss_employee(999)  # not present in either sheet

        month_ws.format.assert_not_called()
        tech_ws.delete_rows.assert_not_called()

    def test_get_dismissed_rows_returns_red_rows(self, sheets_client):
        """get_dismissed_rows returns indices of red-background rows and omits others."""
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
                        },  # row 1 — red
                        {
                            "values": [{
                                "effectiveFormat": {
                                    "backgroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0}
                                }
                            }]
                        },  # row 2 — white
                        {
                            "values": [{
                                "effectiveFormat": {
                                    "backgroundColor": {"red": 1.0, "green": 0.8, "blue": 0.8}
                                }
                            }]
                        },  # row 3 — red
                    ]
                }]
            }]
        }
        sheets_client._client.http_client.request.return_value = mock_resp

        result = sheets_client.get_dismissed_rows("Май 2026")

        assert result == {1, 3}
