from aiogram.fsm.state import StatesGroup, State


class AuthStates(StatesGroup):
    choosing_department = State()  # выбор отдела: зал/бар
    choosing_position = State()    # выбор позиции: раннер/официант/хостес/бармен
    entering_fio = State()         # ввод ФИО текстом
    waiting_dev_message = State()  # ввод сообщения для разработчика
