"""Тесты обработчиков апрува карт лояльности и наполняемости чеков."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_callback(data: str, message_text: str = "", caller_id: int = 999) -> MagicMock:
    cb = MagicMock()
    cb.data = data
    cb.message.text = message_text
    cb.from_user.id = caller_id
    cb.answer = AsyncMock()
    cb.message.edit_text = AsyncMock()
    cb.message.answer = AsyncMock()
    cb.bot.send_message = AsyncMock()
    return cb


# ---------------------------------------------------------------------------
# Tests: approve_loyalty_callback
# ---------------------------------------------------------------------------

class TestApproveLoyaltyCallback:

    @pytest.mark.asyncio
    async def test_approve_loyalty_success(self):
        """Апрув 2 карт → write_shift вызван с ah=1.0, офик уведомлён, pending очищен."""
        from app.bot.handlers.auth import approve_loyalty_callback
        import app.bot.handlers.auth as auth_module

        callback_key = "loy_test_ok"
        auth_module._pending_loyalty[callback_key] = {
            "tg_id": 12345,
            "shift_date": "01.05.26",
            "shift_hours": 10.0,
            "full_name": "Тест Тестов",
            "photo_ids": ["p1", "p2"],
        }
        cb = _make_callback(f"approve_loyalty:{callback_key}:2", caller_id=999)

        with (
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.upsert_shift", new=AsyncMock(return_value=None)),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_shift = MagicMock()
            await approve_loyalty_callback(cb)

        mock_sc.write_shift.assert_called_once()
        _, kwargs = mock_sc.write_shift.call_args
        call_args = mock_sc.write_shift.call_args[0]
        assert call_args[0] == 12345   # telegram_id
        assert call_args[4] == 10.0   # h
        assert call_args[5] == 1.0    # ah = 2 * 0.5
        assert callback_key not in auth_module._pending_loyalty
        cb.message.edit_text.assert_called_once()
        cb.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_approve_loyalty_double_click(self):
        """Сообщение уже содержит ✅ → отвечает 'Уже обработано.', ничего не пишет."""
        from app.bot.handlers.auth import approve_loyalty_callback

        cb = _make_callback(
            "approve_loyalty:somekey:2",
            message_text="🎴 Карты...\n✅ Одобрено 2 фото → 1 ч",
        )
        await approve_loyalty_callback(cb)

        cb.answer.assert_called_once_with("Уже обработано.")

    @pytest.mark.asyncio
    async def test_approve_loyalty_no_data(self):
        """Ключ отсутствует в pending → 'Данные устарели.'"""
        from app.bot.handlers.auth import approve_loyalty_callback
        import app.bot.handlers.auth as auth_module

        auth_module._pending_loyalty.pop("missing_key", None)
        cb = _make_callback("approve_loyalty:missing_key:1")

        await approve_loyalty_callback(cb)

        cb.answer.assert_called_with("Данные устарели.", show_alert=True)

    @pytest.mark.asyncio
    async def test_approve_loyalty_zero_approved(self):
        """Апрув 0 карт → ah=0.0, write_shift всё равно вызван."""
        from app.bot.handlers.auth import approve_loyalty_callback
        import app.bot.handlers.auth as auth_module

        callback_key = "loy_zero"
        auth_module._pending_loyalty[callback_key] = {
            "tg_id": 55555,
            "shift_date": "10.05.26",
            "shift_hours": 8.0,
            "full_name": "Ноль Тестов",
            "photo_ids": ["p1"],
        }
        cb = _make_callback(f"approve_loyalty:{callback_key}:0", caller_id=999)

        with (
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.upsert_shift", new=AsyncMock(return_value=None)),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_shift = MagicMock()
            await approve_loyalty_callback(cb)

        call_args = mock_sc.write_shift.call_args[0]
        assert call_args[5] == 0.0    # ah = 0 * 0.5


# ---------------------------------------------------------------------------
# Tests: approve_filling_callback
# ---------------------------------------------------------------------------

class TestApproveFilllingCallback:

    @pytest.mark.asyncio
    async def test_approve_filling_success(self):
        """Апрув 3 чеков → write_check_filling_to_phantom вызван, пул показан, очищен."""
        from app.bot.handlers.auth import approve_filling_callback
        import app.bot.handlers.auth as auth_module

        callback_key = "fill_ok"
        auth_module._pending_filling[callback_key] = {
            "tg_id": 77777,
            "shift_date": "05.05.26",
            "shift_hours": 10.0,
            "full_name": "Чек Тестов",
            "photo_ids": ["p1", "p2", "p3"],
        }
        cb = _make_callback(f"approve_filling:{callback_key}:3", caller_id=999)

        with (
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.add_check_filling", new=AsyncMock(return_value=50)) as mock_add,
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_check_filling_to_phantom.return_value = True
            mock_sc.get_phantom_checks_summary.return_value = 47

            await approve_filling_callback(cb)

        # SQLite-инкремент первым, зеркало получает готовую сумму из БД
        mock_add.assert_awaited_once()
        assert mock_add.await_args.args[1:] == ("2026-05-05", 3)
        mock_sc.write_check_filling_to_phantom.assert_called_once_with("05.05.26", 3, total=50)
        mock_sc.get_phantom_checks_summary.assert_called_once_with("first")  # день 5 ≤ 15
        assert callback_key not in auth_module._pending_filling
        cb.message.edit_text.assert_called_once()
        cb.message.answer.assert_called_once()    # сводка админу
        cb.bot.send_message.assert_called_once()  # уведомление офику

    @pytest.mark.asyncio
    async def test_approve_filling_mirror_failure_still_succeeds(self):
        """Фаза 2b: зеркало вернуло False → апрув успешен (данные в SQLite), дев уведомлён."""
        from app.bot.handlers.auth import approve_filling_callback
        import app.bot.handlers.auth as auth_module
        from config import DEVELOPER_ID

        callback_key = "fill_fail"
        auth_module._pending_filling[callback_key] = {
            "tg_id": 88888,
            "shift_date": "20.05.26",
            "shift_hours": 8.0,
            "full_name": "Фейл Тестов",
            "photo_ids": ["p1"],
        }
        cb = _make_callback(f"approve_filling:{callback_key}:1", caller_id=999)

        with (
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.add_check_filling", new=AsyncMock(return_value=1)),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_check_filling_to_phantom.return_value = False
            mock_sc.get_phantom_checks_summary.return_value = 1
            await approve_filling_callback(cb)

        # Операция успешна: сводка показана, сообщение отредактировано
        mock_sc.get_phantom_checks_summary.assert_called_once_with("second")
        cb.message.edit_text.assert_called_once()
        # Разработчик уведомлён о рассинхроне зеркала
        dev_calls = [
            c for c in cb.bot.send_message.call_args_list
            if c.args and c.args[0] == DEVELOPER_ID
        ]
        assert dev_calls, "разработчик не уведомлён о рассинхроне зеркала"

    @pytest.mark.asyncio
    async def test_approve_filling_second_half_period(self):
        """День > 15 → период 'second' передаётся в get_phantom_checks_summary."""
        from app.bot.handlers.auth import approve_filling_callback
        import app.bot.handlers.auth as auth_module

        callback_key = "fill_second"
        auth_module._pending_filling[callback_key] = {
            "tg_id": 99999,
            "shift_date": "20.05.26",
            "shift_hours": 8.0,
            "full_name": "Вторая Тестов",
            "photo_ids": ["p1"],
        }
        cb = _make_callback(f"approve_filling:{callback_key}:1", caller_id=999)

        with (
            patch("app.bot.handlers.auth.get_admins_by_department", new=AsyncMock(return_value=[999])),
            patch("app.bot.handlers.auth.add_check_filling", new=AsyncMock(return_value=10)),
            patch("app.bot.handlers.auth.sheets_client") as mock_sc,
        ):
            mock_sc.write_check_filling_to_phantom.return_value = True
            mock_sc.get_phantom_checks_summary.return_value = 10

            await approve_filling_callback(cb)

        mock_sc.get_phantom_checks_summary.assert_called_once_with("second")


# ---------------------------------------------------------------------------
# Tests: approved_count validation
# ---------------------------------------------------------------------------

class TestApprovalCountValidation:

    @pytest.mark.asyncio
    async def test_approve_loyalty_exceeds_photo_count(self):
        """approved_count > len(photo_ids) → ❌ алерт, write_shift НЕ вызван."""
        from app.bot.handlers.auth import approve_loyalty_callback
        import app.bot.handlers.auth as auth_module

        callback_key = "loy_forged"
        auth_module._pending_loyalty[callback_key] = {
            "tg_id": 11111,
            "shift_date": "01.05.26",
            "shift_hours": 10.0,
            "full_name": "Тест Тестов",
            "photo_ids": ["p1", "p2"],  # только 2 фото
        }
        cb = _make_callback(f"approve_loyalty:{callback_key}:99")

        with patch("app.bot.handlers.auth.sheets_client") as mock_sc:
            await approve_loyalty_callback(cb)

        cb.answer.assert_called_once_with("❌ Недопустимое значение.", show_alert=True)
        mock_sc.write_shift.assert_not_called()

    @pytest.mark.asyncio
    async def test_approve_filling_exceeds_photo_count(self):
        """approved_count > len(photo_ids) → ❌ алерт, write_check_filling НЕ вызван."""
        from app.bot.handlers.auth import approve_filling_callback
        import app.bot.handlers.auth as auth_module

        callback_key = "fill_forged"
        auth_module._pending_filling[callback_key] = {
            "tg_id": 22222,
            "shift_date": "05.05.26",
            "shift_hours": 8.0,
            "full_name": "Фейк Тестов",
            "photo_ids": ["p1"],  # только 1 фото
        }
        cb = _make_callback(f"approve_filling:{callback_key}:99")

        with patch("app.bot.handlers.auth.sheets_client") as mock_sc:
            await approve_filling_callback(cb)

        cb.answer.assert_called_once_with("❌ Недопустимое значение.", show_alert=True)
        mock_sc.write_check_filling_to_phantom.assert_not_called()
