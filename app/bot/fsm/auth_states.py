from aiogram.fsm.state import StatesGroup, State


class AuthStates(StatesGroup):
    waiting_role_type = State()    # выбор: Сотрудник или Администратор
    choosing_department = State()  # выбор отдела: зал/бар/кухня (для сотрудника)
    choosing_position = State()    # выбор позиции: раннер/официант/хостес/бармен
    entering_fio = State()         # ввод ФИО текстом
    waiting_admin_dept = State()   # выбор отдела для администратора
    waiting_dev_message = State()  # ввод сообщения для разработчика
