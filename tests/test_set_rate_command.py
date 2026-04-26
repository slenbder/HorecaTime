import pytest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch, AsyncMock, MagicMock, ANY

from app.bot.handlers.admin import (
    cmd_set_rate,
    process_department,
    process_position,
    process_employee,
    process_period_choice,
    process_base_rate,
    process_extra_rate,
)


class _MockFSM:
    """Minimal FSMContext mock that accumulates state data across handler calls."""

    def __init__(self):
        self._data = {}

    async def get_data(self):
        return dict(self._data)

    async def update_data(self, **kwargs):
        self._data.update(kwargs)

    async def set_state(self, state=None):
        pass

    async def clear(self):
        self._data = {}


def _make_message(user_id: int, text: str = "") -> MagicMock:
    msg = MagicMock()
    msg.from_user.id = user_id
    msg.text = text
    msg.answer = AsyncMock()
    return msg


def _make_callback(user_id: int, data: str) -> MagicMock:
    cb = MagicMock()
    cb.from_user.id = user_id
    cb.data = data
    cb.message.edit_text = AsyncMock()
    cb.answer = AsyncMock()
    return cb


class TestSetRateCommand:

    @pytest.mark.asyncio
    async def test_admin_set_rate_current_month(self):
        """admin_hall устанавливает базовую ставку Официанту с текущего месяца."""
        state = _MockFSM()
        msg = _make_message(111)
        mock_set_rate = AsyncMock()

        async def _users_by_dept(db_path, dept):
            if dept == "МОП":
                return []
            return [{"telegram_id": 222, "full_name": "Иванов", "position": "Официант"}]

        with (
            patch("app.bot.handlers.admin.get_user_role", new=AsyncMock(return_value="admin_hall")),
            patch("app.bot.handlers.admin.get_users_rates_by_department", new=AsyncMock(side_effect=_users_by_dept)),
            patch("app.bot.handlers.admin.set_user_rate", new=mock_set_rate),
            patch("app.bot.handlers.admin.POSITIONS_WITH_EXTRA", new=set()),
        ):
            await cmd_set_rate(msg, state)

            await process_position(_make_callback(111, "setrate_pos:Официант"), state)
            await process_employee(_make_callback(111, "setrate_emp:222"), state)
            await process_period_choice(_make_callback(111, "setrate_period:current"), state)

            msg_rate = _make_message(111, "350")
            await process_base_rate(msg_rate, state)

        mock_set_rate.assert_called_once_with(ANY, 222, 350.0, None)
        answer_text = msg_rate.answer.call_args[0][0]
        assert "✅ Ставка установлена" in answer_text

    @pytest.mark.asyncio
    async def test_superadmin_set_rate_next_month(self):
        """Суперадмин устанавливает ставку сотруднику Кухни со следующего месяца."""
        state = _MockFSM()
        msg = _make_message(999)
        mock_set_future = AsyncMock()

        now = datetime.now(ZoneInfo("Europe/Moscow"))
        next_month = now.month + 1 if now.month < 12 else 1
        next_year = now.year if now.month < 12 else now.year + 1

        with (
            patch("app.bot.handlers.admin.SUPERADMIN_IDS", new={999}),
            patch("app.bot.handlers.admin.get_user_role", new=AsyncMock(return_value=None)),
            patch("app.bot.handlers.admin.get_users_rates_by_department",
                  new=AsyncMock(return_value=[{"telegram_id": 333, "full_name": "Петров", "position": "Горячий цех"}])),
            patch("app.bot.handlers.admin.set_user_rate_future", new=mock_set_future),
            patch("app.bot.handlers.admin.POSITIONS_WITH_EXTRA", new=set()),
        ):
            await cmd_set_rate(msg, state)

            await process_department(_make_callback(999, "setrate_dept:Кухня"), state)
            await process_position(_make_callback(999, "setrate_pos:Горячий цех"), state)
            await process_employee(_make_callback(999, "setrate_emp:333"), state)
            await process_period_choice(_make_callback(999, "setrate_period:next"), state)

            msg_rate = _make_message(999, "400")
            await process_base_rate(msg_rate, state)

        mock_set_future.assert_called_once_with(ANY, 333, 400.0, None, next_month, next_year)
        answer_text = msg_rate.answer.call_args[0][0]
        assert "✅ Ставка установлена" in answer_text

    @pytest.mark.asyncio
    async def test_admin_set_rate_runner_with_extra(self):
        """admin_hall устанавливает базовую + повышенную ставку Раннеру с текущего месяца."""
        state = _MockFSM()
        msg = _make_message(111)
        mock_set_rate = AsyncMock()

        async def _users_by_dept(db_path, dept):
            if dept == "МОП":
                return []
            return [{"telegram_id": 444, "full_name": "Сидоров", "position": "Раннер"}]

        with (
            patch("app.bot.handlers.admin.get_user_role", new=AsyncMock(return_value="admin_hall")),
            patch("app.bot.handlers.admin.get_users_rates_by_department", new=AsyncMock(side_effect=_users_by_dept)),
            patch("app.bot.handlers.admin.set_user_rate", new=mock_set_rate),
            patch("app.bot.handlers.admin.POSITIONS_WITH_EXTRA", new={"Раннер"}),
            patch("app.bot.handlers.admin.EXTRA_RATE_LABELS", new={"Раннер": "выходные"}),
        ):
            await cmd_set_rate(msg, state)

            await process_position(_make_callback(111, "setrate_pos:Раннер"), state)
            await process_employee(_make_callback(111, "setrate_emp:444"), state)
            await process_period_choice(_make_callback(111, "setrate_period:current"), state)

            # Базовая ставка — бот должен запросить повышенную
            msg_base = _make_message(111, "200")
            await process_base_rate(msg_base, state)

            # Повышенная ставка — завершает флоу
            msg_extra = _make_message(111, "300")
            await process_extra_rate(msg_extra, state)

        mock_set_rate.assert_called_once_with(ANY, 444, 200.0, 300.0)
        answer_text = msg_extra.answer.call_args[0][0]
        assert "✅ Ставка установлена" in answer_text
        assert "200" in answer_text
        assert "300" in answer_text
