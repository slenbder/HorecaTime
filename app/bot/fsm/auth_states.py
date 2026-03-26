from aiogram.fsm.state import StatesGroup, State


class AuthStates(StatesGroup):
    waiting_role_type = State()    # выбор: Сотрудник или Администратор
    choosing_department = State()  # выбор отдела: зал/бар/кухня (для сотрудника)
    choosing_position = State()    # выбор позиции: раннер/официант/хостес/бармен
    entering_fio = State()         # ввод ФИО текстом
    waiting_admin_dept = State()   # выбор отдела для администратора
    waiting_admin_email = State()  # ввод email для администраторов
    waiting_dev_message = State()  # ввод сообщения для разработчика
    waiting_dismiss_dept_type = State()  # выбор: Сотрудник или Администратор
    waiting_dismiss_dept = State()       # выбор подразделения
    waiting_dismiss_confirm = State()    # подтверждение увольнения
    waiting_broadcast_text = State()     # ожидание текста рассылки
    waiting_broadcast_dept = State()     # выбор отдела для рассылки (admin_*)
    waiting_kitchen_title = State()      # ввод должности для Шеф/Су-шеф
    waiting_dop_position = State()       # выбор Грузчик/Закупщик


class SetRateStates(StatesGroup):
    waiting_set_rate_position = State()  # выбор позиции через inline-кнопки
    waiting_set_rate_base = State()      # ввод базовой ставки
    waiting_set_rate_extra = State()     # ввод повышенной ставки (только для позиций с extra_rate)
