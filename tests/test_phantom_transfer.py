"""Тесты переноса фантомного сотрудника при switch_month."""
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.scheduler.monthly_switch import _transfer_phantom_to_new_month
from config import PHANTOM_CHECK_FILLING_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_old_values(phantom_row: int = 5) -> list[list[str]]:
    """Лист с фантомом на указанной строке (1-based)."""
    rows = []
    for i in range(1, phantom_row + 5):
        if i == phantom_row:
            rows.append(["Наполняемость чека", str(PHANTOM_CHECK_FILLING_ID), "Официант"])
        else:
            rows.append(["Иванов", "12345", "Официант"])
    return rows


def _make_new_values(section_row: int = 5) -> list[list[str]]:
    """Новый лист с заголовком секции в колонке C на указанной строке (A/B пустые)."""
    rows = []
    for i in range(1, section_row + 5):
        if i == section_row:
            rows.append(["", "", "Официанты"])
        else:
            rows.append(["Петров", "67890", "Официант"])
    return rows


def _make_sheets_client(old_values, new_values):
    """Создаёт мок sheets_client с двумя разными листами."""
    old_ws = MagicMock()
    old_ws.get_all_values.return_value = old_values

    new_ws = MagicMock()
    new_ws.get_all_values.return_value = new_values

    client = MagicMock()
    client._spreadsheet.worksheet.side_effect = lambda name: (
        old_ws if name == "Апрель 2026" else new_ws
    )
    return client, old_ws, new_ws


def _make_bot() -> AsyncMock:
    bot = AsyncMock()
    bot.send_message = AsyncMock()
    return bot


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPhantomTransfer:

    @pytest.mark.asyncio
    async def test_phantom_transferred(self):
        """Фантом перенесён: insert_rows вызван в новом листе."""
        old_vals = _make_old_values(phantom_row=5)
        new_vals = _make_new_values(section_row=5)
        client, old_ws, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.insert_rows.assert_called_once()

    @pytest.mark.asyncio
    async def test_phantom_position_end_of_section(self):
        """Фантом вставляется после последнего сотрудника секции (insert_after_row + 1)."""
        # Заголовок на строке 7; строки 8-11 — сотрудники (range(1, 12))
        old_vals = _make_old_values(phantom_row=3)
        new_vals = _make_new_values(section_row=7)
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        call_kwargs = new_ws.insert_rows.call_args
        row_arg = call_kwargs[1].get("row") or call_kwargs[0][1]
        assert row_arg == 12  # insert_after_row(11) + 1

    @pytest.mark.asyncio
    async def test_phantom_values_inserted(self):
        """Строка фантома содержит имя, TG_ID и позицию в A/B/C."""
        old_vals = _make_old_values(phantom_row=5)
        new_vals = _make_new_values(section_row=5)
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        inserted_data = new_ws.insert_rows.call_args[0][0]
        row = inserted_data[0]
        assert row[0] == "Наполняемость чека"
        assert str(row[1]) == str(PHANTOM_CHECK_FILLING_ID)
        assert row[2] == "Официант"

    @pytest.mark.asyncio
    async def test_phantom_formulas_inserted(self):
        """Формулы S/AJ/AK вставлены через batch_update с USER_ENTERED."""
        old_vals = _make_old_values(phantom_row=5)
        new_vals = _make_new_values(section_row=5)
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.batch_update.assert_called_once()
        bu_args, bu_kwargs = new_ws.batch_update.call_args
        ranges = [item["range"] for item in bu_args[0]]
        values = [item["values"][0][0] for item in bu_args[0]]

        # Три формулы должны присутствовать
        assert len(ranges) == 3
        assert any(v.startswith("=SUM(D") for v in values), "Формула для S не найдена"
        assert any(v.startswith("=SUM(T") for v in values), "Формула для AJ не найдена"
        assert any(v.startswith("=S") and "+" in v for v in values), "Формула для AK не найдена"

        # Убеждаемся что USER_ENTERED передан
        assert bu_kwargs.get("value_input_option") == "USER_ENTERED"

    @pytest.mark.asyncio
    async def test_phantom_not_found_warning(self):
        """Фантом не найден → warning залогирован, insert_rows НЕ вызван, нет исключения."""
        old_vals = [
            ["Иванов", "11111", "Официант"],
            ["Петров", "22222", "Раннер"],
        ]
        new_vals = _make_new_values(section_row=3)
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        # Не должно бросать исключение
        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.insert_rows.assert_not_called()

    # -----------------------------------------------------------------------
    # Новые тесты Шага 1: поиск секции через колонку C
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_phantom_finds_section_by_column_c(self):
        """Секция найдена когда заголовок в колонке C (A/B пустые) — фантом перенесён."""
        old_vals = _make_old_values(phantom_row=2)
        # заголовок "Официанты" в C, A и B пустые
        new_vals = [
            ["Петров", "67890", "Официант"],
            ["", "", "Официанты"],   # заголовок в C
            ["Сидоров", "11111", "Официант"],
        ]
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.insert_rows.assert_called_once()

    @pytest.mark.asyncio
    async def test_phantom_no_false_positive_in_column_a(self):
        """Заголовок "Официанты" только в колонке A — секция НЕ находится → raise."""
        old_vals = _make_old_values(phantom_row=2)
        new_vals = [
            ["Петров", "67890", "Официант"],
            ["Официанты", "", ""],   # заголовок в A, не в C
            ["Сидоров", "11111", "Официант"],
        ]
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        import pytest as _pytest
        with _pytest.raises(RuntimeError, match="секция 'Официанты' не найдена"):
            await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.insert_rows.assert_not_called()

    @pytest.mark.asyncio
    async def test_section_not_found_raises(self):
        """Секция 'Официанты' отсутствует в новом листе → raise RuntimeError, не тихий return."""
        old_vals = _make_old_values(phantom_row=2)
        # Нет строки с A=="" и B=="" и C=="Официанты"
        new_vals = [
            ["Петров", "67890", "Официант"],
            ["Сидоров", "11111", "Бармен"],
        ]
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        import pytest as _pytest
        with _pytest.raises(RuntimeError, match="секция 'Официанты' не найдена"):
            await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.insert_rows.assert_not_called()

    # -----------------------------------------------------------------------
    # Фикс: фантом исключён из проверки аномалий switch_month, поэтому
    # duplicate_sheet уже копирует его строку в новый лист — обнуляем
    # смены на месте вместо вставки новой (иначе дублирование).
    # -----------------------------------------------------------------------

    @pytest.mark.asyncio
    async def test_phantom_already_in_new_sheet_cleared_not_duplicated(self):
        """Фантом уже есть в новом листе (не удалён как аномалия) → смены
        обнуляются на месте (batch_clear), insert_rows НЕ вызывается."""
        old_vals = _make_old_values(phantom_row=5)
        new_vals = [
            ["Петров", "67890", "Официант"],
            ["Наполняемость чека", str(PHANTOM_CHECK_FILLING_ID), "Официант"],
            ["Сидоров", "11111", "Официант"],
        ]
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.insert_rows.assert_not_called()
        new_ws.batch_clear.assert_called_once_with(["D2:R2", "T2:AI2"])

    @pytest.mark.asyncio
    async def test_phantom_already_in_new_sheet_formulas_recalculated(self):
        """Формулы S/AJ/AK — простой SUM (не H/AH), для фактической строки фантома."""
        old_vals = _make_old_values(phantom_row=5)
        new_vals = [
            ["Наполняемость чека", str(PHANTOM_CHECK_FILLING_ID), "Официант"],
            ["Петров", "67890", "Официант"],
        ]
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.batch_update.assert_called_once()
        bu_args, bu_kwargs = new_ws.batch_update.call_args
        ranges = [item["range"] for item in bu_args[0]]
        values = [item["values"][0][0] for item in bu_args[0]]
        assert ranges == ["S1", "AJ1", "AK1"]
        assert values == ["=SUM(D1:R1)", "=SUM(T1:AI1)", "=S1+AJ1"]
        assert bu_kwargs.get("value_input_option") == "USER_ENTERED"

    @pytest.mark.asyncio
    async def test_phantom_already_in_new_sheet_old_sheet_not_read(self):
        """Фантом найден в новом листе → старый лист вообще не читается (не нужен)."""
        old_vals = _make_old_values(phantom_row=5)
        new_vals = [
            ["Наполняемость чека", str(PHANTOM_CHECK_FILLING_ID), "Официант"],
        ]
        client, old_ws, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        old_ws.get_all_values.assert_not_called()

    @pytest.mark.asyncio
    async def test_phantom_missing_from_new_sheet_falls_back_to_insert(self):
        """Фантома нет в новом листе (ручное удаление) → fallback: вставка новой строки,
        как раньше (устойчивость к нестандартному состоянию листа)."""
        old_vals = _make_old_values(phantom_row=5)
        new_vals = _make_new_values(section_row=5)  # без фантома
        client, _, new_ws = _make_sheets_client(old_vals, new_vals)

        await _transfer_phantom_to_new_month(client, "Апрель 2026", "Май 2026", _make_bot())

        new_ws.insert_rows.assert_called_once()
