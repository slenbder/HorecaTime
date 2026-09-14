"""
Тесты дедупликации Telegram-алертов (fix/dedupe-telegram-alerts).

Покрывает:
- TelegramHandler.emit() пропускает запись с extra={"telegram_already_alerted": True}
  (Фикс 1 — global_error_handler больше не дублирует send_critical_alert/send_warning_alert)
- TelegramHandler.emit() по-прежнему шлёт алерт, когда флага нет (регрессия)
- error_logger.error(..., exc_info=True) в userhours._send_waiter_report
  (Фикс 2 — чтобы IGNORED_ERRORS видел тип исключения)
- healthcheck() логирует сбой Google Sheets на уровне WARNING, а не ERROR
  (Фикс 3 — не дублировать собственный агрегированный алерт)
"""
import logging
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.logging_config import TelegramHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_record(msg: str = "test error", extra: dict | None = None, exc_info=None) -> logging.LogRecord:
    logger = logging.getLogger("test_telegram_handler_dedup")
    return logger.makeRecord(
        logger.name, logging.ERROR, __file__, 1, msg, (), exc_info, extra=extra,
    )


# ---------------------------------------------------------------------------
# Фикс 1: TelegramHandler.emit() — дедуп по telegram_already_alerted
# ---------------------------------------------------------------------------

class TestTelegramHandlerDedup:

    def test_emit_skips_send_when_telegram_already_alerted(self):
        """Запись с extra={'telegram_already_alerted': True} → requests.post НЕ вызывается."""
        handler = TelegramHandler(bot_token="test_token", chat_id=123)
        record = _make_record(extra={"telegram_already_alerted": True})

        with patch("requests.post") as mock_post:
            handler.emit(record)

        mock_post.assert_not_called()

    def test_emit_still_sends_without_flag_no_exc_info(self):
        """Без флага и без exc_info → requests.post вызывается как раньше (нет регрессии)."""
        handler = TelegramHandler(bot_token="test_token", chat_id=123)
        record = _make_record()

        with patch("requests.post") as mock_post:
            handler.emit(record)

        mock_post.assert_called_once()

    def test_emit_still_sends_without_flag_exc_info_not_ignored(self):
        """Без флага, exc_info есть, но тип исключения НЕ в IGNORED_ERRORS → алерт уходит как раньше."""
        handler = TelegramHandler(bot_token="test_token", chat_id=123)
        try:
            raise ValueError("boom")
        except ValueError:
            exc_info = sys.exc_info()
        record = _make_record(exc_info=exc_info)

        with patch("requests.post") as mock_post:
            handler.emit(record)

        mock_post.assert_called_once()


# ---------------------------------------------------------------------------
# Фикс 2: userhours._send_waiter_report — exc_info=True при сбое уведомления
# ---------------------------------------------------------------------------

class TestSendWaiterReportExcInfo:

    @pytest.mark.asyncio
    async def test_send_waiter_report_logs_exc_info_on_telegram_failure(self):
        """TelegramNetworkError при bot.send_message → error_logger.error вызван с exc_info=True."""
        from aiogram.exceptions import TelegramNetworkError
        from app.bot.handlers.userhours import _send_waiter_report

        message = MagicMock()
        message.from_user.username = "waiter1"
        message.answer = AsyncMock()
        message.bot.send_media_group = AsyncMock()
        message.bot.send_message = AsyncMock(
            side_effect=TelegramNetworkError(method=MagicMock(), message="сеть недоступна")
        )

        state = AsyncMock()
        state.clear = AsyncMock()

        result = {
            "day": 1, "month": 5, "year": 2026,
            "h": 8.0, "start": 10.0, "end": 18.0,
        }

        with (
            patch("app.bot.handlers.userhours.create_pending_approval", new=AsyncMock(return_value=1)),
            patch("app.bot.handlers.userhours.get_admins_by_department", new=AsyncMock(return_value=[111])),
            patch("app.bot.handlers.userhours.get_user", return_value={"full_name": "Тест Тестов"}),
            patch("app.bot.handlers.userhours.error_logger") as mock_error_logger,
        ):
            await _send_waiter_report(message, state, 12345, result, ["photo1"])

        mock_error_logger.error.assert_called_once()
        _, kwargs = mock_error_logger.error.call_args
        assert kwargs.get("exc_info") is True


# ---------------------------------------------------------------------------
# Фикс 3: healthcheck() — сбой Google Sheets логируется как WARNING
# ---------------------------------------------------------------------------

class TestHealthcheckLogLevel:

    @pytest.mark.asyncio
    async def test_healthcheck_logs_warning_not_error_on_sheets_failure(self, caplog, tmp_path, monkeypatch):
        """Сбой Google Sheets в healthcheck() → запись в лог уровня WARNING, не ERROR."""
        from app.scheduler.healthcheck import healthcheck

        monkeypatch.setattr("app.scheduler.healthcheck.DB_PATH", str(tmp_path / "healthcheck_test.db"))

        bot = MagicMock()
        bot.send_message = AsyncMock()

        with (
            patch("app.services.google_sheets.GoogleSheetsClient", side_effect=RuntimeError("Sheets недоступен")),
            patch("app.scheduler.healthcheck.count_errors_in_log", return_value=0),
            caplog.at_level(logging.WARNING, logger="app.scheduler.healthcheck"),
        ):
            await healthcheck(bot)

        sheets_records = [r for r in caplog.records if "Google Sheets" in r.message]
        assert sheets_records, "Ожидалась запись лога про сбой Google Sheets"
        assert all(r.levelno == logging.WARNING for r in sheets_records)
        assert not any(r.levelno == logging.ERROR for r in sheets_records)
