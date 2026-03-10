# HorecaTime — Telegram-бот учёта рабочего времени

## Суть проекта
Перенос Telegram-бота с Google Apps Script на Python (aiogram 3.x).
Apps Script версия — рабочий референс в продакшне. Файлы скриптов доступны в ассетах проекта.

---

## Стек
- Python 3.11+, aiogram 3.13.1
- gspread 6.1.2, oauth2client 4.1.3
- APScheduler 3.10.4
- aiosqlite 0.20.0
- SQLite — только FSM + кеш ролей, НЕ основная БД
- Google Sheets — единственный источник данных (single source of truth)

---

## Структура проекта

```
project/
├── main.py                        ✅ точка входа, роутеры, middleware, SQLiteStorage
├── config.py                      ✅ загрузка .env, списки ID + DEVELOPER_ID
├── app/
│   ├── logging_config.py          ✅
│   ├── bot/
│   │   ├── handlers/
│   │   │   ├── auth.py            ✅ полный approve-flow
│   │   │   ├── userhours.py       🔄 в разработке
│   │   │   ├── userreports.py     ❌
│   │   │   ├── admin.py           ❌
│   │   │   └── superadmin.py      ❌
│   │   ├── fsm/
│   │   │   ├── auth_states.py     ✅
│   │   │   └── ...остальные       ❌
│   │   ├── keyboards/
│   │   │   ├── common.py          ✅ отдел + позиции + main_menu_keyboard()
│   │   │   └── admin.py           ❌
│   │   └── middlewares/
│   │       └── roles.py           ✅ импорт ID из config (не из auth.py!), роль developer
│   ├── services/
│   │   ├── google_sheets.py       ✅ с _reconnect()
│   │   ├── roles_cache.py         ✅
│   │   ├── timeparsing.py         ❌
│   │   ├── businesslogic.py       ❌
│   │   └── pdfservice.py          ❌
│   ├── scheduler/
│   │   └── monthly_switch.py      ❌
│   └── db/
│       ├── models.py              ✅ таблицы users + fsm_storage
│       └── fsm_storage.py         ✅ SQLiteStorage для aiogram FSM
├── docker/
│   ├── Dockerfile                 ❌
│   └── docker-compose.yml         ❌
├── db/bot.db                      ✅ создаётся автоматически
└── logs/
    ├── app.log
    ├── errors.log
    └── googleapi.log
```

---

## Логирование — ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА

Три лог-файла, настроены в `app/logging_config.py`:
- `logs/app.log` — общий поток: старт, действия пользователей, успешные операции
- `logs/errors.log` — только ошибки и исключения
- `logs/googleapi.log` — все обращения к Google Sheets (запросы, ответы, реконнекты)

**Всегда логировать:**
- Старт и остановку бота
- Каждый вызов Google Sheets API (в googleapi.log)
- Реконнекты (`_reconnect()`)
- Approve/reject пользователя
- Добавление пользователя в месячный лист
- Критические ошибки → лог + Telegram-алерт разработчику

**Никогда не использовать** `print()` — только `logging`.

---

## Google Sheets — структура

**Техлист** (колонки):
- A(1): Telegram ID
- B(2): ник
- C(3): TG-имя
- D(4): последнее сообщение
- E(5): registered_at
- F(6): last_seen_at
- G(7): message_id
- H(8): ФИО от пользователя
- I(9): этап взаимодействия (0/1/2/3)
- J(10): «ДА/НЕТ» — в штате
- K(11): отдел (Зал/Бар/Кухня)
- L(12): позиция

**Месячный лист** («Часы», «Январь 2025» и т.д.):
- A: ФИО, B: Telegram ID, C: позиция
- Строка 3: даты месяца
- Данные: D5:R60 и T5:AI60
- Колонка 38: часовая ставка
- Ключевые ячейки: C2 (месяц), T2 (год)

**Маппинг позиций → секции листа:**
```python
POSITION_TO_SECTION = {
    # Кухня
    "Су-шеф": "Руководящий состав",
    "Горячий цех": "Горячий цех",
    "Холодный цех": "Холодный цех",
    "Кондитерский цех": "Кондитерский цех",
    "Заготовочный цех": "Заготовочный цех",
    "Коренной цех": "Коренной цех",
    "МОП": "МОП",
    # Бар
    "Бармен": "Бармены",
    "Барбэк": "Барбэки",
    # Зал (порядок секций: Менеджеры → Официанты → Раннеры → Хостесс)
    "Менеджер": "Менеджеры",
    "Официант": "Официанты",
    "Раннер": "Раннеры",
    "Хостесс": "Хостесс",
}
DEPARTMENT_TO_HEADER = {"Кухня": "КУХНЯ", "Бар": "БАР", "Зал": "ЗАЛ"}
```

---

## SQLite — таблицы (db/bot.db)

```sql
users (
    telegram_id INTEGER PRIMARY KEY,
    full_name   TEXT NOT NULL,
    role        TEXT NOT NULL,  -- user/admin_hall/admin_bar/admin_kitchen/superadmin/developer
    department  TEXT,           -- Зал/Бар/Кухня
    hourly_rate REAL,
    created_at  TEXT NOT NULL
)

fsm_storage (
    chat_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    bot_id  INTEGER NOT NULL,
    state   TEXT,
    data    TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (chat_id, user_id, bot_id)
)
```

---

## Роли

| Роль | Доступ |
|---|---|
| `user` | Внесение часов, свои данные |
| `admin_hall` | + ставки и сообщения зала |
| `admin_bar` | + ставки и сообщения бара |
| `admin_kitchen` | + ставки кухни |
| `superadmin` | Всё + переключение месяца + PDF + рассылка всем |
| `developer` | Все права superadmin + алерты об ошибках + получает сообщения через inline-кнопку «Написать разработчику», которая отображается у всех ролей кроме него самого |

---

## .env переменные

```
BOT_TOKEN
GOOGLE_CREDENTIALS_PATH
SPREADSHEET_ID
ADMIN_HALL_IDS        # через запятую
ADMIN_BAR_IDS
ADMIN_KITCHEN_IDS
SUPERADMIN_IDS
DEVELOPER_ID          # один ID (не список)
```

---

## Позиции по отделам

```python
VALID_POSITIONS = {
    "Зал":   ["Менеджер", "Официант", "Раннер", "Хостесс"],
    "Бар":   ["Бармен", "Барбэк"],
    "Кухня": ["Су-шеф", "Горячий цех", "Холодный цех",
               "Кондитерский цех", "Заготовочный цех", "Коренной цех", "МОП"],
}
```

---

## Бизнес-логика — ключевые правила

**Расчёт часов:**
- `H = endTime - startTime`, округление до 0.5 (`roundToHalf`)
- Пересечение полуночи обрабатывается: `H = 24 - start + end`
- Выходные: пятница, суббота, воскресенье — ставка выходного дня

**Форматы ввода даты:** `1.1` / `01.01` / `1.01.25` / `01.01.25`
**Форматы ввода времени:** `1000-1800` / `10-18` / `10.00-18.00`
**Спецзначения:** `X` = рабочий день (без часов), `О/o/0` = нулевая смена

**Добавление в месячный лист:**
1. Найти секцию по позиции (`POSITION_TO_SECTION`)
2. Fallback: конец блока отдела (`DEPARTMENT_TO_HEADER`)
3. Fallback: конец листа
4. Защита от дублей — проверка по Telegram ID в колонке B

---

## Текущий этап разработки

**Этап 0 ✅ завершён:**
- Полный approve-flow авторизации (FSM AuthStates)
- GoogleSheetsClient с _reconnect()
- RolesCacheService (SQLite)
- RoleMiddleware (импорт из config, circular import устранён)
- SQLiteStorage для FSM (состояния переживают рестарт)
- Клавиатуры выбора отдела и позиции (включая позицию «Менеджер»)
- Роль `developer` (DEVELOPER_ID из env, проверяется в middleware перед superadmin)
- `main_menu_keyboard(role)` с inline-кнопкой «Написать разработчику» для всех ролей кроме `developer`

**Этап 1 🔄 в работе:**
- `setMyCommands` по ролям через `BotCommandScopeChat`
- Обработчик callback `contact_dev`

**Что впереди:**
- Этап 2: timeparsing.py с тестами
- Этап 3: FSM внесения часов (раннер как эталон)
- Этап 4: FSM для официанта, хостес, бармена
- Этапы 5-10: отчёты, админка, PDF, Docker, деплой

---

## Важные договорённости

- **Не использовать** `print()` нигде в коде
- **Не менять** структуру таблиц Google Sheets — это продакшн
- **Circular import**: ID ролей импортировать из `config.py`, не из `auth.py`
- **Apps Script файлы** в ассетах проекта — референс логики, не трогать
- **Git workflow**: ветки от `main`, PR без автомерджа, коммит после каждой задачи
- Название месячных листов: `{MONTH_NAMES_RU[month]} {year}` (например «Март 2025»)
