"""Тесты новых FSM states для карт лояльности и наполняемости чеков."""
import pytest

from app.bot.fsm.shift_states import ShiftStates


class TestFSMStatesNew:

    def test_waiting_loyalty_cards_exists(self):
        assert hasattr(ShiftStates, "waiting_loyalty_cards")

    def test_waiting_check_filling_exists(self):
        assert hasattr(ShiftStates, "waiting_check_filling")

    def test_states_order(self):
        """Порядок: shift_input → loyalty_cards → check_filling → ah_input → ah_comment."""
        from aiogram.fsm.state import State
        state_keys = [k for k, v in ShiftStates.__dict__.items() if isinstance(v, State)]
        idx_shift = state_keys.index("waiting_shift_input")
        idx_loyalty = state_keys.index("waiting_loyalty_cards")
        idx_filling = state_keys.index("waiting_check_filling")
        idx_ah = state_keys.index("waiting_ah_input")
        idx_comment = state_keys.index("waiting_ah_comment")

        assert idx_shift < idx_loyalty < idx_filling < idx_ah < idx_comment

    def test_old_states_preserved(self):
        """Существующие states waiting_ah_input и waiting_ah_comment не удалены."""
        assert hasattr(ShiftStates, "waiting_ah_input")
        assert hasattr(ShiftStates, "waiting_ah_comment")
        assert hasattr(ShiftStates, "waiting_shift_input")
