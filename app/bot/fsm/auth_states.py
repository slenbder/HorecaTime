from aiogram.fsm.state import StatesGroup, State


class AuthStates(StatesGroup):
    choosing_department = State()  # выбор отдела: зал/бар/кухня
    choosing_position = State()    # выбор позиции: раннер/официант/хостес/бармен
    entering_fio = State()         # ввод ФИО текстом
    waiting_dev_message = State()  # ввод сообщения для разработчика
    waiting_dismiss_dept_type = State()  # выбор: Сотрудник или Администратор
    waiting_dismiss_dept = State()       # выбор подразделения
    waiting_dismiss_confirm = State()    # подтверждение увольнения
    waiting_broadcast_text = State()     # ожидание текста рассылки
    waiting_broadcast_dept = State()     # выбор отдела для рассылки (admin_*)
    waiting_kitchen_title = State()      # ввод должности для Шеф/Су-шеф
    waiting_dop_position = State()       # выбор Грузчик/Закупщик
    waiting_promote_dept = State()       # /promote: выбор подразделения
    waiting_promote_position = State()   # /promote: выбор позиции
    waiting_promote_user = State()       # /promote: выбор конкретного сотрудника
    waiting_promote_confirm = State()    # /promote: подтверждение
    waiting_promote_email = State()      # /promote: ввод email новым админом
    waiting_demote_dept = State()        # /demote: выбор подразделения
    waiting_demote_user = State()        # /demote: выбор конкретного админа
    waiting_demote_confirm = State()     # /demote: подтверждение


class SetRateStates(StatesGroup):
    waiting_set_rate_dept = State()      # /set_rate_all: выбор отдела
    waiting_set_rate_position = State()  # /set_rate_all: выбор позиции
    waiting_set_rate_employee = State()  # /set_rate_all: выбор сотрудника
    waiting_set_rate_base = State()      # /set_rate_all: ввод базовой ставки
    waiting_set_rate_extra = State()     # /set_rate_all: ввод повышенной ставки (Раннер/Бармен/Барбэк)
