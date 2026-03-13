from aiogram.fsm.state import StatesGroup, State


class ShiftStates(StatesGroup):
    waiting_shift_input = State()   # ожидание ввода смены (дата + время)
    waiting_ah_input    = State()   # ожидание ввода доп. часов (только раннер)
    waiting_ah_comment  = State()   # ожидание комментария к AH (только раннер)
