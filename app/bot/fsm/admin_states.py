from aiogram.fsm.state import State, StatesGroup


class SetRateStates(StatesGroup):
    waiting_position = State()   # выбор позиции
    waiting_employee = State()   # выбор сотрудника
    waiting_new_rate = State()   # ввод ставки
