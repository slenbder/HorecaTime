"""
Тесты установки Plain text формата для предотвращения интерпретации дат
в колонках D-AK месячного листа.
"""
from unittest.mock import MagicMock, AsyncMock, patch

import pytest

from app.scheduler.monthly_switch import _make_formulas, _SIMPLE_H_POSITIONS


# ---------------------------------------------------------------------------
# Factory: GoogleSheetsClient без реального __init__
# ---------------------------------------------------------------------------

def _make_client():
    from app.services.google_sheets import GoogleSheetsClient
    client = object.__new__(GoogleSheetsClient)
    client._spreadsheet = MagicMock()
    client._client = MagicMock()
    return client


# ---------------------------------------------------------------------------
# Test 1: switch_month устанавливает Plain text формат для D-AK нового листа
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_switch_month_sets_plain_text_format():
    from app.scheduler.monthly_switch import switch_month

    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    mock_sheets = MagicMock()

    mock_old_ws = MagicMock()
    mock_old_ws.title = "Май 2026"
    mock_old_ws.id = 11111

    mock_new_ws = MagicMock()
    mock_new_ws.id = 12345
    mock_new_ws.get_all_values.return_value = []

    # worksheets() вызывается 3 раза:
    # 1) _find_last_month_sheet
    # 2) проверка существования следующего листа (Июнь 2026 ещё нет)
    # 3) получение last_index для перемещения
    mock_sheets._spreadsheet.worksheets.side_effect = [
        [mock_old_ws],
        [mock_old_ws],
        [mock_old_ws, mock_new_ws],
    ]
    mock_sheets._spreadsheet.worksheet.return_value = mock_old_ws
    mock_sheets._spreadsheet.duplicate_sheet.return_value = mock_new_ws
    mock_sheets._spreadsheet.batch_update.return_value = None
    mock_sheets.get_dismissed_rows.return_value = []

    with patch("app.scheduler.monthly_switch.snapshot_user_rates_history", new_callable=AsyncMock):
        with patch("app.scheduler.monthly_switch.apply_future_rates", new_callable=AsyncMock):
            await switch_month(mock_bot, mock_sheets, ":memory:")

    # Найти вызов batch_update с repeatCell TEXT для D-AK нового листа
    format_call_found = False
    for call_args in mock_sheets._spreadsheet.batch_update.call_args_list:
        body = call_args[0][0]
        for req in body.get("requests", []):
            rc = req.get("repeatCell", {})
            if not rc:
                continue
            r = rc.get("range", {})
            if (
                r.get("sheetId") == 12345
                and r.get("startRowIndex") == 4
                and r.get("startColumnIndex") == 3
                and r.get("endColumnIndex") == 37
            ):
                fmt = rc["cell"]["userEnteredFormat"]["numberFormat"]
                assert fmt["type"] == "TEXT"
                format_call_found = True
                break

    assert format_call_found, (
        "batch_update с repeatCell TEXT для D-AK нового листа не вызван"
    )


# ---------------------------------------------------------------------------
# Test 2: ensure_user устанавливает TEXT-формат для новой строки
# ---------------------------------------------------------------------------

def test_ensure_user_sets_plain_text_for_new_row():
    client = _make_client()

    client.get_user_by_telegram_id = MagicMock(return_value={
        "fio_from_user": "Петров Петр",
        "department": "Кухня",
        "position": "Горячий цех",
    })

    mock_ws = MagicMock()
    mock_ws.id = 9999
    mock_ws.col_count = 40
    mock_ws.title = "Май 2026"
    client._get_current_month_worksheet = MagicMock(return_value=mock_ws)

    # row 1 (idx 0): заголовок
    # row 2 (idx 1): секция "Горячий цех" (A="" B="" C="Горячий цех")
    # row 3 (idx 2): существующий сотрудник tg_id=111
    # → новый сотрудник (tg_id=456) вставится в row 4 (new_row=4)
    mock_ws.get_all_values.return_value = [
        ["ФИО", "id telegram", "Должность"],
        ["", "", "Горячий цех"],
        ["Иванов", "111", "Повар"],
    ]

    result = client.ensure_user_in_current_month_hours(456)

    assert result is True

    calls = mock_ws.format.call_args_list
    assert len(calls) == 2, f"Ожидалось 2 вызова format, получено {len(calls)}"

    ranges_called = [c[0][0] for c in calls]
    assert "B4:B4" in ranges_called, f"Ожидался вызов format('B4:B4', ...), вызовы: {ranges_called}"
    assert "D4:AK4" in ranges_called, f"Ожидался вызов format('D4:AK4', ...), вызовы: {ranges_called}"

    for c in calls:
        assert c[0][1]["numberFormat"]["type"] == "TEXT"


# ---------------------------------------------------------------------------
# Tests 3-4: типы формул — простые для Кухни/МОП, сложные для Зала/Бара
# ---------------------------------------------------------------------------

class TestFormulaTypes:

    def test_kitchen_positions_use_simple_formula(self):
        kitchen_positions = [
            "Руководящий состав", "Горячий цех", "Холодный цех",
            "Кондитерский цех", "Заготовочный цех", "Коренной цех",
            "Хостесс", "Менеджер", "Грузчик", "Закупщик", "Клининг", "Котломой",
        ]

        for position in kitchen_positions:
            assert position in _SIMPLE_H_POSITIONS, (
                f"'{position}' должна быть в _SIMPLE_H_POSITIONS"
            )

            formula_s, formula_aj, _ = _make_formulas(10, position)

            assert "ЛЕВСИМВ" not in formula_s, f"'{position}': S содержит ЛЕВСИМВ"
            assert "ПСТР" not in formula_s, f"'{position}': S содержит ПСТР"
            assert "СУММПРОИЗВ" in formula_s, f"'{position}': S не содержит СУММПРОИЗВ"

            assert "ЛЕВСИМВ" not in formula_aj, f"'{position}': AJ содержит ЛЕВСИМВ"
            assert "ПСТР" not in formula_aj, f"'{position}': AJ содержит ПСТР"
            assert "СУММПРОИЗВ" in formula_aj, f"'{position}': AJ не содержит СУММПРОИЗВ"

    def test_hall_bar_positions_use_complex_formula(self):
        complex_positions = ["Официант", "Раннер", "Бармен", "Барбэк"]

        for position in complex_positions:
            assert position not in _SIMPLE_H_POSITIONS, (
                f"'{position}' не должна быть в _SIMPLE_H_POSITIONS"
            )

            formula_s, formula_aj, _ = _make_formulas(10, position)

            assert "ЛЕВСИМВ" in formula_s, f"'{position}': S не содержит ЛЕВСИМВ"
            assert "ПСТР" in formula_s, f"'{position}': S не содержит ПСТР"
            assert "ЛЕВСИМВ" in formula_aj, f"'{position}': AJ не содержит ЛЕВСИМВ"
            assert "ПСТР" in formula_aj, f"'{position}': AJ не содержит ПСТР"
