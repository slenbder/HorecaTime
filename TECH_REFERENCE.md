# HorecaTime — Техническая справка

Этот файл содержит детальные технические схемы, структуры данных и примеры, которые дополняют основной **CLAUDE.md**.

---

## Терминология (критично важно!)

**Отдел (department)** — подразделение в ресторане:
- Зал
- Бар
- Кухня
- МОП

**Позиция (position)** — роль сотрудника в отделе:
- Официант, Раннер, Хостесс, Менеджер (Зал)
- Бармен, Барбэк (Бар)
- Су-шеф, Горячий цех, Холодный цех и т.д. (Кухня)
- Клининг, Котломой (МОП)

**Должность (custom_title)** — персональное название:
- Используется только для Су-шеф (например "Су-шеф Иванов")
- И для Грузчик/Закупщик (например "Грузчик Петров")
- Хранится отдельно от позиции

---

## Структура Google Sheets

### Техлист (колонки)

| Колонка | Название | Описание |
|---------|----------|----------|
| A (1) | Telegram ID | Уникальный идентификатор пользователя |
| B (2) | @Ник | Username в Telegram |
| C (3) | ФИО | Полное имя от пользователя |
| D (4) | Отдел | Зал/Бар/Кухня/МОП |
| E (5) | Позиция | Официант/Раннер/Бармен/... |
| F (6) | Дата регистрации | DD.MM.YY HH:MM (Moscow time) |
| G (7) | Статус | "ДА" — утверждён в графике |

### Месячный лист

**Формат названия:** `{MONTH_NAMES_RU[month]} {year}` (например "Март 2026")

**Структура:**
- **A:** ФИО
- **B:** Telegram ID
- **C:** Позиция (или custom_title для Су-шеф)
- **Строка 3:** Даты месяца
- **Данные смен:** D5:R60 (дни 1-15), T5:AI60 (дни 16-конец)
- **Ключевые ячейки:** C2 (месяц), T2 (год)

**Итоговые колонки (формат H/AH):**
- **S (19):** H/AH первая половина месяца (дни 1-15)
- **AJ (36):** H/AH вторая половина месяца (дни 16-конец)
- **AK (37):** H/AH за весь месяц

**Служебные колонки для Раннера (числовой формат):**
- **AL (38):** Итого выходных H за месяц (формула =AM+AN, вставляется при добавлении)
- **AM (39):** Выходные H за первую половину (дни 1-15), накапливается при write_shift
- **AN (40):** Выходные H за вторую половину (дни 16-конец), накапливается при write_shift

**Формат ячеек:**
- **D:AK** = "Обычный текст" (TEXT) — настраивается вручную в таблице
- **AL/AM/AN** = числовой формат для корректной работы формул

**Защита от инъекций:**
- **value_input_option="RAW"** во всех операциях записи
- Защита от formula injection (`=HYPERLINK()`, `=IMPORTXML()` и т.д.)

---

## Маппинг позиций → секции листа

Эта информация дублирует `config.py` константу `POSITION_TO_SECTION`:

```python
POSITION_TO_SECTION = {
    # Кухня
    "Су-шеф": "Руководящий состав",
    "Горячий цех": "Горячий цех",
    "Холодный цех": "Холодный цех",
    "Кондитерский цех": "Кондитерский цех",
    "Заготовочный цех": "Заготовочный цех",
    "Коренной цех": "Коренной цех",
    "Грузчик": "Дополнительные сотрудники",
    "Закупщик": "Дополнительные сотрудники",
    # МОП
    "Клининг": "Клининг",
    "Котломой": "Котломой",
    # Бар
    "Бармен": "Бармены",
    "Барбэк": "Барбэки",
    # Зал (порядок секций: Менеджеры → Официанты → Раннеры → Хостесс)
    "Менеджер": "Менеджеры",
    "Официант": "Официанты",
    "Раннер": "Раннеры",
    "Хостесс": "Хостесс",
}

DEPARTMENT_TO_HEADER = {
    "Кухня": "КУХНЯ",
    "Бар": "БАР",
    "Зал": "ЗАЛ",
    "МОП": "Моп"
}
```

---

## SQLite — схемы таблиц

### Таблица `users`

```sql
CREATE TABLE users (
    telegram_id INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    role        TEXT NOT NULL,  -- user/admin_hall/admin_bar/admin_kitchen/superadmin/developer
    department  TEXT,           -- Зал/Бар/Кухня/МОП
    position    TEXT,           -- Официант/Раннер/Бармен/... (заполняется при approve)
    created_at  TEXT NOT NULL
);
```

**Важно:** Поле `hourly_rate` удалено — ставки теперь в `user_rates`.

### Таблица `fsm_storage`

```sql
CREATE TABLE fsm_storage (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    bot_id  INTEGER NOT NULL,
    state   TEXT,
    data    TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (chat_id, user_id, bot_id)
);
```

### Таблица `rates` (шаблон для новых сотрудников)

```sql
CREATE TABLE rates (
    position         TEXT PRIMARY KEY,
    base_rate        REAL NOT NULL,
    extra_rate       REAL  -- NULL для позиций без повышенной ставки
);
```

**Критично важно:** 
- `rates` = **ТОЛЬКО ШАБЛОН** для новых сотрудников
- Используется **ТОЛЬКО при апруве** (копируется в `user_rates`)
- Расчёт зарплаты идёт **ТОЛЬКО через `user_rates`**, НЕ через `rates`
- `/set_rate_all` (superadmin) редактирует `rates` как шаблоны

### Таблица `user_rates` (персональные ставки)

```sql
CREATE TABLE user_rates (
    telegram_id  INTEGER PRIMARY KEY,
    base_rate    REAL NOT NULL,
    extra_rate   REAL,           -- NULL для позиций без повышенной ставки
    updated_at   TEXT NOT NULL,
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE CASCADE
);
```

**Использование:**
- У каждого сотрудника своя персональная ставка
- Создаётся при апруве (копируется из `rates`)
- Редактируется через `/set_rate` (admin) или `/set_rate_all` (superadmin)
- Используется для расчёта зарплаты в `/hours_*`

### Таблица `user_rates_history` (снимки при переключении месяца)

```sql
CREATE TABLE user_rates_history (
    telegram_id  INTEGER NOT NULL,
    base_rate    REAL NOT NULL,
    extra_rate   REAL,
    month        INTEGER NOT NULL,
    year         INTEGER NOT NULL,
    PRIMARY KEY (telegram_id, month, year)
);
```

**Использование:**
- Снимок делается при `switch_month()`
- Используется в `/hours_last` для расчёта зарплаты за прошлый месяц
- Защита от изменений ставок "задним числом"

### Таблица `rates_history` (legacy, для старых данных)

```sql
CREATE TABLE rates_history (
    position     TEXT NOT NULL,
    base_rate    REAL NOT NULL,
    extra_rate   REAL,
    month        INTEGER NOT NULL,
    year         INTEGER NOT NULL,
    PRIMARY KEY (position, month, year)
);
```

**Использование:**
- Хранит старые данные до миграции на `user_rates`
- Fallback в `/hours_last` если нет данных в `user_rates_history`

---

## Позиции с повышенной ставкой

```python
POSITIONS_WITH_EXTRA = {"Раннер", "Бармен", "Барбэк"}
```

**Раннер:**
- `base_rate` — будние дни
- `extra_rate` — выходные (пт/сб/вс)

**Бармен/Барбэк:**
- `base_rate` — первые 60 часов
- `extra_rate` — свыше 60 часов + тусовочные AH

---

## Примеры сообщений бота

### Отчёты по часам

**Официант:**
```
📊 Первая половина месяца (1–15)
Отработано: 96 ч
Доп. часы: 12 ч
💰 Заработок: 42000 р
```

**Менеджер / Хостесс / Кухня:**
```
📊 Первая половина месяца (1–15)
Отработано: 88 ч
💰 Заработок: 26400 р
```

**Раннер:**
```
📊 Первая половина месяца (1–15)
Отработано: 85 ч
Доп. часы: 8 ч
• 70 ч × 200 р = 14000 р (будние дни)
• 15 ч × 300 р = 4500 р (выходные дни)
• 8 ч × 200 р = 1600 р (доп. часы)
💰 Итого: 20100 р
```

**Бармен / Барбэк:**
```
📊 Первая половина месяца (1–15)
Отработано: 75 ч
Доп. часы: 15 ч
• 60 ч × 350 р = 21000 р
• 15 ч × 500 р = 7500 р (свыше 60ч)
• 15 ч × 500 р = 7500 р (доп. часы)
💰 Итого: 36000 р
```

### Уведомление о новой смене (для администраторов)

```
📝 Новая смена от @username (ФИО)

📅 Дата: 15 марта 2026
⏰ Время: 18:00 – 23:30 (5.5 ч)
💼 Позиция: Официант

📸 Фото AH: 3 шт.
```

### Заявка на регистрацию

```
📋 Заявка на регистрацию

👤 @username
📝 ФИО: Иван Иванов
🏢 Отдел: Зал
💼 Позиция: Официант

[Одобрить] [Отклонить]
```

### Заявка администратора (для superadmin)

```
📋 Заявка на администратора

👤 @username
📝 ФИО: Пётр Петров
🏢 Отдел: Зал
💼 Позиция: Менеджер
📧 Email: p***r@gmail.com

[Одобрить] [Отклонить]
```

**Важно:** Email маскируется через `mask_email()` из `app/utils/text_utils.py`.

---

## Логика расчёта зарплаты

### Официант, Менеджер, Хостесс, Кухня (кроме Раннера)

```python
user_rate = get_user_rate(telegram_id)
salary = total_hours * user_rate.base_rate + ah_hours * user_rate.base_rate
```

### Раннер

```python
user_rate = get_user_rate(telegram_id)
regular_hours = total_hours - weekend_h_hours
salary = regular_hours * user_rate.base_rate + weekend_h_hours * user_rate.extra_rate
```

**Важно:** Выходные часы (пт/сб/вс) считаются по `extra_rate`, будние по `base_rate`.

### Бармен / Барбэк

```python
user_rate = get_user_rate(telegram_id)
regular_hours = min(total_hours, 60)
overtime_hours = max(total_hours - 60, 0)
salary = regular_hours * user_rate.base_rate + (ah_hours + overtime_hours) * user_rate.extra_rate
```

**Важно:** Первые 60 часов по `base_rate`, всё что свыше + тусовочные AH по `extra_rate`.

---

## Константы позиций (config.py)

После Audit Phase 2 #8 все списки позиций консолидированы в константы:

```python
# Позиции с повышенной ставкой
POSITIONS_WITH_EXTRA = {"Раннер", "Бармен", "Барбэк"}

# Порядок отображения позиций по отделам (для UI)
DEPT_POSITIONS_ORDER = {
    "Зал": ["Менеджер", "Официант", "Раннер", "Хостесс"],
    "Бар": ["Бармен", "Барбэк"],
    "Кухня": ["Су-шеф", "Горячий цех", "Холодный цех", "Кондитерский цех", 
              "Заготовочный цех", "Коренной цех", "Грузчик", "Закупщик"],
    "МОП": ["Клининг", "Котломой"]
}

# Основные списки отделов
HALL_POSITIONS = ["Менеджер", "Официант", "Раннер", "Хостесс"]
BAR_POSITIONS = ["Бармен", "Барбэк"]
KITCHEN_POSITIONS = ["Су-шеф", "Горячий цех", "Холодный цех", "Кондитерский цех", 
                     "Заготовочный цех", "Коренной цех"]
ADDITIONAL_POSITIONS = ["Грузчик", "Закупщик"]
MOP_POSITIONS = ["Клининг", "Котломой"]

# Функциональные группировки
RUNNER_POSITION = "Раннер"
BAR_AH_POSITIONS = ["Бармен", "Барбэк"]
WAITER_POSITIONS = ["Официант"]
SIMPLE_H_POSITIONS = (["Менеджер", "Хостесс"] + KITCHEN_POSITIONS + 
                      ADDITIONAL_POSITIONS + MOP_POSITIONS)
LEADERSHIP_POSITION = "Руководящий состав"  # бывший "Шеф/Су-шеф"
```

---

## Формулы месячного листа

При добавлении нового сотрудника в месячный лист автоматически вставляются формулы:

**Ячейка S (колонка 19) — первая половина месяца:**
```
=D{row}&IF(E{row}<>"","/"&E{row},"")&IF(F{row}<>"","/"&F{row},"")&...&IF(R{row}<>"","/"&R{row},"")
```

**Ячейка AJ (колонка 36) — вторая половина месяца:**
```
=T{row}&IF(U{row}<>"","/"&U{row},"")&IF(V{row}<>"","/"&V{row},"")&...&IF(AI{row}<>"","/"&AI{row},"")
```

**Ячейка AK (колонка 37) — весь месяц:**
```
=S{row}&IF(AJ{row}<>"","/"&AJ{row},"")
```

**Ячейка AL (колонка 38) — итого выходных H для Раннера:**
```
=AM{row}+AN{row}
```

---

## FSM State Machine — список состояний

### AuthStates (регистрация и управление)

```python
waiting_role_type       # Выбор user/admin
waiting_admin_dept      # Выбор отдела для администратора
waiting_dismiss_*       # Состояния при увольнении (5 вариантов)
waiting_kitchen_title   # Ввод custom_title для Су-шефа
waiting_dop_position    # Выбор Грузчик/Закупщик
waiting_admin_email     # Ввод email администратора
waiting_promote_*       # Состояния при повышении (3 варианта)
waiting_demote_*        # Состояния при понижении (2 варианта)
```

**Важно:** `_pending_custom_titles` заменён на FSM data (Audit Phase 1).

### ShiftStates (внесение смен)

```python
waiting_shift_input     # Ввод даты и времени смены
waiting_ah_input        # Ввод AH (для позиций с AH)
waiting_ah_comment      # Комментарий к AH
```

### SetRateStates (установка ставок)

```python
waiting_position        # Выбор позиции
waiting_employee        # Выбор сотрудника
waiting_base_rate       # Ввод базовой ставки
waiting_extra_rate      # Ввод повышенной ставки (Раннер/Бармен/Барбэк)
```

**Важно:** Ввод ставки разбит на 2 шага для позиций с `extra_rate`.

### MessageStates (рассылки)

```python
waiting_message         # Ввод текста сообщения для рассылки
```

### DevMessageState (обращение к разработчику)

```python
waiting_dev_message     # Ввод сообщения разработчику
```

---

## Защита от инъекций и атак

### Formula injection (Google Sheets)
- **value_input_option="RAW"** во всех операциях записи
- Защита от `=HYPERLINK()`, `=IMPORTXML()`, `=IMPORTDATA()`

### HTML injection (Telegram)
- `html.escape()` для всех user inputs в HTML-сообщениях
- Применяется к: `full_name`, комментариям, custom_title
- Функция `make_mention()` в `app/utils/text_utils.py` экранирует имена

### Callback data overflow
- Лимит 64 байта — данные хранятся в dict (`_pending_admins`), не в callback
- Только короткие идентификаторы в callback_data

### Email validation
- Только `@gmail.com` через `_is_valid_gmail()`
- Маскировка в логах через `mask_email()` → `p***r@gmail.com`

---

## Telegram ID админов и разработчика

Эти ID хранятся в `.env` и импортируются в `config.py`:

```bash
# Разработчик
DEVELOPER_ID=8624217185

# Суперадмины (через запятую)
SUPERADMIN_IDS=123456789,987654321

# Администраторы отделов
ADMIN_HALL_IDS=111111111,222222222
ADMIN_BAR_IDS=333333333
ADMIN_KITCHEN_IDS=444444444,555555555
```

**Важно:** 
- Все проверки прав через эти константы, **не через SQLite**
- admin_hall управляет отделами: **Зал + МОП**
