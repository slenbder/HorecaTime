"""
Тесты retry-логики в GoogleSheetsClient._call и fail-loud switch_month.

Покрывает:
- APIError 429 → backoff+retry без reconnect
- APIError 500/503 → reconnect + один повторный вызов
- транзиентные сетевые ошибки (ConnectionError/Timeout) → reconnect + один повтор
- не-429/500/503 APIError → propagate немедленно, без reconnect
- 429 исчерпан (3 попытки) → raise
- 500/503/network error: повтор тоже упал → raise, reconnect вызван ровно один раз
- провал батча в switch_month → raise RuntimeError (один алерт)
"""
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from requests.exceptions import ConnectionError as RequestsConnectionError, Timeout as RequestsTimeout

from app.services.google_sheets import GoogleSheetsClient
from app.scheduler.monthly_switch import switch_month


# ---------------------------------------------------------------------------
# Helpers — создаём реальный (но без сети) GoogleSheetsClient
# ---------------------------------------------------------------------------

def _make_client() -> GoogleSheetsClient:
    """Создаёт GoogleSheetsClient без реального подключения."""
    client = object.__new__(GoogleSheetsClient)
    client._spreadsheet = MagicMock()
    client._client = MagicMock()
    return client


def _make_api_error(code: int):
    """Создаёт gspread APIError с указанным HTTP кодом."""
    from gspread.exceptions import APIError
    mock_response = MagicMock()
    mock_response.json.return_value = {"error": {"code": code, "message": "test error"}}
    return APIError(mock_response)


# ---------------------------------------------------------------------------
# Tests: _call — 429 backoff
# ---------------------------------------------------------------------------

class TestCallBackoff:

    def test_429_retried_without_reconnect(self):
        """Первый вызов 429 → sleep → второй вызов успешен. reconnect НЕ вызывается."""
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=[_make_api_error(429), "ok"])

        with patch("app.services.google_sheets.time.sleep") as mock_sleep:
            result = client._call(fn, "arg1")

        assert result == "ok"
        assert fn.call_count == 2
        client._reconnect.assert_not_called()
        mock_sleep.assert_called_once_with(2)  # первый backoff = 2s

    def test_429_two_retries_succeed_on_third(self):
        """Два 429 → два backoff → третий вызов успешен."""
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=[_make_api_error(429), _make_api_error(429), "ok"])

        with patch("app.services.google_sheets.time.sleep") as mock_sleep:
            result = client._call(fn, "arg1")

        assert result == "ok"
        assert fn.call_count == 3
        client._reconnect.assert_not_called()
        assert mock_sleep.call_args_list == [call(2), call(4)]

    def test_429_exhausted_raises_after_three_attempts(self):
        """Три подряд 429 → raise после исчерпания попыток."""
        from gspread.exceptions import APIError
        client = _make_client()

        fn = MagicMock(side_effect=[
            _make_api_error(429), _make_api_error(429), _make_api_error(429)
        ])

        with patch("app.services.google_sheets.time.sleep"):
            with pytest.raises(APIError) as exc_info:
                client._call(fn, "arg1")

        assert exc_info.value.code == 429
        assert fn.call_count == 3

    def test_non_429_api_error_propagates_immediately(self):
        """Не-429 APIError (напр. 403) → propagate немедленно, без retry, без reconnect."""
        from gspread.exceptions import APIError
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=_make_api_error(403))

        with patch("app.services.google_sheets.time.sleep") as mock_sleep:
            with pytest.raises(APIError) as exc_info:
                client._call(fn)

        assert exc_info.value.code == 403
        assert fn.call_count == 1
        client._reconnect.assert_not_called()
        mock_sleep.assert_not_called()

    def test_success_on_first_attempt_no_sleep(self):
        """Первый вызов успешен → нет sleep, нет retry."""
        client = _make_client()

        fn = MagicMock(return_value="success")

        with patch("app.services.google_sheets.time.sleep") as mock_sleep:
            result = client._call(fn, "a", "b", key="val")

        assert result == "success"
        fn.assert_called_once_with("a", "b", key="val")
        mock_sleep.assert_not_called()

    def test_kwargs_passed_through(self):
        """_call корректно передаёт keyword arguments в fn."""
        client = _make_client()

        fn = MagicMock(return_value=None)
        client._call(fn, [1, 2, 3], value_input_option="USER_ENTERED")

        fn.assert_called_once_with([1, 2, 3], value_input_option="USER_ENTERED")


# ---------------------------------------------------------------------------
# Tests: _call — 500/503 и транзиентные сетевые ошибки → reconnect + 1 повтор
# ---------------------------------------------------------------------------

class TestCallReconnectRetry:

    @pytest.mark.parametrize("code", [500, 503])
    def test_5xx_reconnects_and_retries_once_then_succeeds(self, code):
        """APIError 500/503 → reconnect() вызывается один раз → второй вызов успешен."""
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=[_make_api_error(code), "ok"])

        with patch("app.services.google_sheets.time.sleep") as mock_sleep:
            result = client._call(fn, "arg1")

        assert result == "ok"
        assert fn.call_count == 2
        client._reconnect.assert_called_once()
        mock_sleep.assert_not_called()  # 500/503 не использует backoff-sleep, только reconnect

    @pytest.mark.parametrize("code", [500, 503])
    def test_5xx_retry_fails_raises_after_exactly_one_retry(self, code):
        """APIError 500/503 → reconnect + один повтор → повтор тоже упал → raise.
        reconnect() вызван РОВНО один раз, fn вызван РОВНО два раза (без третьей попытки)."""
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=[_make_api_error(code), _make_api_error(code)])

        from gspread.exceptions import APIError
        with pytest.raises(APIError) as exc_info:
            client._call(fn, "arg1")

        assert exc_info.value.code == code
        assert fn.call_count == 2
        client._reconnect.assert_called_once()

    def test_other_5xx_like_codes_not_retried(self):
        """APIError с кодом вне {429,500,503} (напр. 403) — без reconnect, без retry."""
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=_make_api_error(403))

        from gspread.exceptions import APIError
        with pytest.raises(APIError):
            client._call(fn)

        assert fn.call_count == 1
        client._reconnect.assert_not_called()

    @pytest.mark.parametrize("error_cls", [RequestsConnectionError, RequestsTimeout])
    def test_transient_network_error_reconnects_and_retries_once_then_succeeds(self, error_cls):
        """ConnectionError/Timeout → reconnect() один раз → второй вызов успешен."""
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=[error_cls("boom"), "ok"])

        result = client._call(fn, "arg1")

        assert result == "ok"
        assert fn.call_count == 2
        client._reconnect.assert_called_once()

    @pytest.mark.parametrize("error_cls", [RequestsConnectionError, RequestsTimeout])
    def test_transient_network_error_retry_fails_raises_after_one_retry(self, error_cls):
        """ConnectionError/Timeout persists через повтор → raise, reconnect вызван один раз."""
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=[error_cls("boom"), error_cls("boom again")])

        with pytest.raises(error_cls):
            client._call(fn, "arg1")

        assert fn.call_count == 2
        client._reconnect.assert_called_once()

    def test_generic_exception_not_retried_no_reconnect(self):
        """Обычное исключение (не APIError, не сетевая ошибка) — propagate немедленно,
        без reconnect, без retry (see google_sheets.py call-site refactor)."""
        client = _make_client()
        client._reconnect = MagicMock()

        fn = MagicMock(side_effect=ValueError("business logic error"))

        with pytest.raises(ValueError):
            client._call(fn)

        assert fn.call_count == 1
        client._reconnect.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: staleness fix — retry после reconnect() должен идти против свежего
# объекта (self._spreadsheet / worksheet), а не против того, что был получен
# ДО reconnect(). Регрессионные тесты на баг, найденный при код-ревью рефакторинга.
# ---------------------------------------------------------------------------

class TestCallWithWorksheetFreshness:

    def test_retry_refetches_worksheet_after_reconnect(self):
        """500/503 внутри op(ws) → reconnect() → get_ws() вызывается ЗАНОВО,
        и повтор op выполняется против свежего (второго) объекта листа,
        а не против того, что был получен до reconnect."""
        client = _make_client()
        client._reconnect = MagicMock()

        old_ws = MagicMock(name="old_ws")
        new_ws = MagicMock(name="new_ws")
        get_ws = MagicMock(side_effect=[old_ws, new_ws])

        def op(ws):
            if ws is old_ws:
                raise _make_api_error(503)
            return "ok-with-fresh-ws"

        result_ws, result = client._call_with_worksheet(get_ws, op)

        assert result == "ok-with-fresh-ws"
        assert result_ws is new_ws
        assert get_ws.call_count == 2
        client._reconnect.assert_called_once()

    def test_success_on_first_attempt_calls_get_ws_once(self):
        """Успех с первой попытки — get_ws() вызывается один раз, reconnect не нужен."""
        client = _make_client()
        client._reconnect = MagicMock()
        ws = MagicMock()
        get_ws = MagicMock(return_value=ws)

        result_ws, result = client._call_with_worksheet(get_ws, lambda w: w.get_all_values())

        assert result_ws is ws
        get_ws.assert_called_once()
        client._reconnect.assert_not_called()

    def test_get_techlist_worksheet_retry_uses_fresh_spreadsheet(self):
        """Регрессионный тест на исходный баг: retry внутри _get_techlist_worksheet
        после reconnect() должен читать self._spreadsheet ЗАНОВО (через lambda),
        а не держать bound-метод на объекте, протухшем до reconnect()."""
        client = _make_client()
        old_spreadsheet = client._spreadsheet
        old_spreadsheet.worksheet.side_effect = _make_api_error(503)

        new_spreadsheet = MagicMock(name="new_spreadsheet")
        new_spreadsheet.worksheet.return_value = "fresh-ws"

        def fake_reconnect():
            client._spreadsheet = new_spreadsheet
        client._reconnect = MagicMock(side_effect=fake_reconnect)

        result = client._get_techlist_worksheet()

        assert result == "fresh-ws"
        new_spreadsheet.worksheet.assert_called_once()
        # Старый spreadsheet должен быть вызван только один раз (первая, неудачная попытка)
        old_spreadsheet.worksheet.assert_called_once()


# ---------------------------------------------------------------------------
# Tests: fail-loud в switch_month
# ---------------------------------------------------------------------------

def _make_switch_client(batch_clear_error=None, batch_update_error=None, batch_delete_error=None):
    """Мок sheets_client для тестов fail-loud."""
    source_ws = MagicMock()
    source_ws.id = 88

    new_ws = MagicMock()
    new_ws.id = 99
    new_ws.title = "Май 2026"
    new_ws.col_count = 40
    new_ws.get_all_values.return_value = [["Иванов", "101", "Официант"]]

    existing_sheet = MagicMock()
    existing_sheet.title = "Апрель 2026"

    client = MagicMock()
    client._spreadsheet.worksheets.return_value = [existing_sheet]
    client._spreadsheet.worksheet.return_value = source_ws
    client._spreadsheet.duplicate_sheet.return_value = new_ws
    client.get_dismissed_rows.return_value = set()
    client.get_techlist_ids.return_value = {"101"}

    # Настраиваем _call: pass-through, но с нужными side_effect
    def _call_impl(fn, *args, **kwargs):
        if batch_clear_error and fn is new_ws.batch_clear:
            raise batch_clear_error
        if batch_update_error and fn is new_ws.batch_update:
            raise batch_update_error
        if batch_delete_error and "requests" in (args[0] if args else {}):
            raise batch_delete_error
        return fn(*args, **kwargs)

    client._call.side_effect = _call_impl
    return client


async def _run_switch(client):
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
        return await switch_month(bot, client, "test.db"), bot


class TestFailLoud:

    @pytest.mark.asyncio
    async def test_batch_clear_failure_raises_runtime_error(self):
        """Провал batch_clear → switch_month бросает RuntimeError с этапом 'очистка смен'."""
        client = _make_switch_client(batch_clear_error=Exception("network down"))

        with pytest.raises(RuntimeError, match="очистка смен"):
            await _run_switch(client)

    @pytest.mark.asyncio
    async def test_batch_clear_failure_single_alert(self):
        """Провал batch_clear → ровно один алерт разработчику, не N алертов."""
        client = _make_switch_client(batch_clear_error=Exception("network down"))
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
            pytest.raises(RuntimeError),
        ):
            await switch_month(bot, client, "test.db")

        # Один алерт разработчику (из outer except), не больше
        assert bot.send_message.call_count == 1
