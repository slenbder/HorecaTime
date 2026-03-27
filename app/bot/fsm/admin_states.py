from aiogram.fsm.state import State, StatesGroup


class SetRateStates(StatesGroup):
    waiting_position = State()    # выбор позиции
    waiting_employee = State()    # выбор сотрудника
    waiting_new_rate = State()    # ввод базовой ставки
    waiting_extra_rate = State()  # ввод повышенной ставки (только Раннер/Бармен/Барбэк)
