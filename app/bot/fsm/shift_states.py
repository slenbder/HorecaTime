from aiogram.fsm.state import StatesGroup, State


class ShiftStates(StatesGroup):
    waiting_shift_input = State()   # ожидание ввода смены (дата + время)
    waiting_ah_input    = State()   # ожидание ввода доп. часов (только раннер)
    waiting_ah_comment  = State()   # ожидание комментария к AH (только раннер)


class SetRateStates(StatesGroup):
    """FSM для команды /set_rate (установка ставки сотрудника)"""

    # Шаг 1: Выбор отдела (только для суперадмина)
    waiting_department = State()

    # Шаг 2: Выбор позиции в отделе
    waiting_position = State()

    # Шаг 3: Выбор сотрудника из списка
    waiting_employee = State()

    # Шаг 4: Выбор периода применения ставки
    waiting_period_choice = State()  # "С текущего месяца" / "Со следующего месяца"

    # Шаг 5: Ввод базовой ставки
    waiting_base_rate = State()

    # Шаг 6: Ввод повышенной ставки (только для позиций с POSITIONS_WITH_EXTRA)
    waiting_extra_rate = State()
