# HorecaTime — Контекст проекта

## Суть проекта
Python/aiogram 3 Telegram-бот для учёта рабочего времени в ресторане.  
Мигрируем с Google Apps Script (файлы скриптов доступны в ассетах проекта — референс логики).  
Репозиторий: https://github.com/slenbder/HorecaTime

---

## Текущий фокус

**Что делаем сейчас:** Phase 4 — рефакторинг монолитов в auth.py (in progress)
**Активная ветка:** `refactor/phase-4-monoliths`
**Тесты:** 56 passing ✅
**Roadmap:** Завершить Phase 4 → PR в main → лицензирование

**Статус всех фаз:**
- ✅ Phase 1 (10 багов) — PR #52, #53
- ✅ Phase 2 (11 багов + тесты) — PR #54
- ✅ Docker деплой — PR #55
- ✅ Рефакторинг custom_position — PR #56
- ✅ Phase 3 (улучшения) — PR #57
- 🔄 Phase 4 (рефакторинг монолитов auth.py) — текущая ветка

**Phase 4 — process_approve декомпозиция (6/6 шагов + hotfix):**
- ✅ `_parse_approve_callback(callback_data)` — парсинг callback → `(admin_tg_id, user_tg_id) | None`
- ✅ `_fetch_user_info(sheets_client, user_tg_id)` — читает данные из Техлиста → dict | None
- ✅ `_register_user_in_sheets(...)` — регистрация в месячном листе + approve в Техлисте
- ✅ `_setup_user_access(...)` — SQLite + кеш ролей + команды + уведомление пользователю
- ✅ `_notify_approval(...)` — уведомление администратору
- ✅ `process_approve` — оркестратор (вызывает все 5 помощников)
- ✅ `fix(dismiss)` — admins видны в списке при увольнении (баг из 24c1103, filter role=='user' убран)

**Phase 3 — улучшения (PR #57):**
- `fix(userhours)`: cleanup буферов при пустом `photo_ids`
- `fix(admin)`: убран `full_name` из логов ставок (PII protection)
- `test(timeparsing)`: mixed midnight case для `check_overlap`

---

## Стек

- Python 3.11+, aiogram 3.13.1
- gspread 6.1.2, oauth2client 4.1.3
- APScheduler 3.10.4, aiosqlite 0.20.0
- **SQLite** — FSM + кеш ролей + персональные ставки (НЕ основная БД данных сотрудников)
- **Google Sheets** — единственный источник данных сотрудников и смен (single source of truth)
- **Docker** — multi-stage Dockerfile + docker-compose.yml, SQLite в volume `data/`

---

## Критичные технические решения

### Терминология (важно!)
- **Отдел** (department) = Зал/Бар/Кухня/МОП — подразделение в ресторане
- **Позиция** (position) = Официант/Раннер/Бармен — роль сотрудника в отделе
- **Должность** (custom_position) = "Шеф ЗЦ", "Бренд-шеф" — только для Руководящий состав и Грузчик/Закупщик
- Техлист: **E = базовая позиция** (всегда каноническая), **H = custom_position** (пусто для остальных)

### БД и архитектура
- **Google Sheets** = source of truth для всех данных сотрудников и смен
- **SQLite** = только FSM состояния + кеш ролей + персональные ставки (`user_rates`)
- Название месячного листа: `"{Месяц} {Год}"` (например "Апрель 2026")
- Техлист: A(TG_ID), B(@Ник), C(ФИО), D(Отдел), E(Позиция), F(Дата рег), G("ДА"), **H(Должность)**
- Месячный лист: D:AK = "Обычный текст" формат (предотвращает интерпретацию чисел как дат)
- `value_input_option="RAW"` для пользовательских данных (защита от formula injection)
- `value_input_option="USER_ENTERED"` только для hardcoded формул (S/AJ/AK/AL)

### Роли и права
- **SUPERADMIN_IDS / DEVELOPER_ID** импортируются из `config.py`
- Суперадмины и developer **не регистрируются** в таблице `users`
- Проверка прав — всегда через константы из config.py (НЕ из SQLite)
- admin_hall управляет отделами: **Зал + МОП**

### Ставки и зарплата
- **Персональные ставки** в `user_rates` (SQLite) — у каждого сотрудника своя
- Таблица `rates` = шаблон для новых сотрудников (используется только при апруве)
- При `switch_month()` снимки: `rates_history` + `user_rates_history`
- При апруве ставка копируется: `rates` (шаблон) → `user_rates` (персональная)
- Расчёт зарплаты ТОЛЬКО через `user_rates`, НЕ через `rates`

### Позиции с повышенной ставкой
- **Раннер:** базовая (будни) + повышенная (пт/сб/вс)
- **Бармен/Барбэк:** базовая (до 60ч) + повышенная (>60ч + AH)
- Ввод ставки через FSM: сначала базовая, потом повышенная (2 отдельных шага)

### Увольнение
- Ячейка A в месячном листе → `#FFCCCC`
- Удаление из Техлиста
- Строка **НЕ удаляется** из месячного листа (история)
- Красные строки **НЕ переносятся** в новый месяц
- Удаление из SQLite (`users`, `user_rates`) + сброс FSM/кеш/команд

### Telegram ограничения
- **callback_data** максимум 64 байта — данные в `_pending_admins`, не в callback
- Email администратора — только `@gmail.com`
- `LinkPreviewOptions(is_disabled=True)` во всех HTML-сообщениях с упоминаниями
- `html.escape()` для всех user inputs в HTML-сообщениях

### Approve flow (после рефакторинга PR #56 + Phase 4)
- **Нет reverse mapping** — `position` и `custom_position` читаются напрямую из E и H Техлиста
- **Один линейный путь** для всех позиций (нет Path A/B, нет FSM-ветки для admin)
- `process_approve` = оркестратор из 5 приватных функций

---

## Workflow — трёхслойная система

```
Claude (claude.ai)        →  Планирование, архитектура, промпты
        ↓
Claude Code (terminal)    →  Выполнение кода
        ↓
Отчёт → Claude           →  Анализ результатов
```

### Формат промптов для Claude Code (русский язык!)
```
Ветка: refactor/phase-4-monoliths
Файл: app/bot/handlers/auth.py
Проблема: [описание]
Фикс: [шаги решения]
Требования: [проверки, pytest 56/56]
Commit: "refactor(scope): описание"
```

### Правила работы
- **Один промпт = одна задача** — последовательное выполнение
- Тесты (`pytest tests/` — 56 passing) после каждого изменения
- Прямые коммиты в feature-ветку (без PR до стабилизации)
- Решения формализуются в документацию **в реальном времени**
- Token efficiency: новая вкладка per phase, минимум файлов в контексте

### Обработка вопросов Claude Code
- Структурные/технические → Slenbder отвечает напрямую
- Бизнес-логика/неоднозначности → консультация с Claude (claude.ai)
- Ответы ищем в FINAL_AUDIT.md (раздел "Предложение" для каждого бага)

---

## Ключевые паттерны и принципы

### Логирование
- **НИКОГДА** `print()` — только `logging`
- Три лог-файла: `app.log` (общий), `errors.log` (ошибки), `googleapi.log` (Sheets API)
- Email маскируется: `p***r@gmail.com` через `mask_email()` из `app/utils/text_utils.py`
- **НЕ логировать PII**: `full_name` не пишем в логи (только `telegram_id`)
- Логировать: старт/стоп, API calls, реконнекты, approve/reject

### Уведомления
- admin_dept + superadmin (через `set()` для дедупликации)
- Зал/МОП → `ADMIN_HALL_IDS + SUPERADMIN_IDS`
- Бар → `ADMIN_BAR_IDS + SUPERADMIN_IDS`
- Кухня → `ADMIN_KITCHEN_IDS + SUPERADMIN_IDS`

### Регистрация callback handlers
- Специфичные раньше общих: `approve_ah_callback` ДО `approve_`/`reject_`
- Порядок регистрации роутеров: auth → userhours → userreports → admin → superadmin

### Константы и маппинг
- Все списки позиций, отделов → `config.py`
- `POSITIONS_WITH_EXTRA = {"Раннер", "Бармен", "Барбэк"}`
- Маппинги отделов, позиций в `TECH_REFERENCE.md`

### Google Sheets формат
- D:AK = "Обычный текст" (настраивается вручную)
- Формулы S/AJ/AK вставляются автоматически (`USER_ENTERED`)
- AL/AM/AN = числовой формат (выходные часы Раннера)

---

## Важные файлы проекта

- **docs/FINAL_AUDIT.md** — живой роадмап багов (Phases 1-3)
- **CLAUDE.md** — этот файл, контекст проекта (**НИКОГДА НЕ УДАЛЯТЬ**)
- **HISTORY.md** — архив завершённых этапов (**НИКОГДА НЕ УДАЛЯТЬ**)
- **TECH_REFERENCE.md** — схемы БД, маппинги, примеры сообщений (**НИКОГДА НЕ УДАЛЯТЬ**)
- **config.py** — константы, ID, списки позиций
- **app/utils/text_utils.py** — `make_mention()`, `mask_email()`
- **app/db/models.py** — в .gitignore! Требует миграцию на деплое
- **migrate_user_rates_once.py** — одноразовая миграция (оставлен как документация)

---

## На горизонте

### Ближайшие задачи
- **Завершить Phase 4** — смержить `refactor/phase-4-monoliths` → main
- **Monitoring** — алерты при ошибках записи в таблицу
- **Apps Script миграция** (отложено)

### Долгосрочные планы
- **Лицензионная система** (license server + PyArmor)
- **Web-панель** для конфигурации
- **Модель подписки**
- **Универсализация** для сторонних клиентов

---

## Key Learnings

- **Отдел ≠ Позиция ≠ Должность** — путаница в терминах ведёт к багам
- **Техлист E = базовая позиция, H = custom_position** — E всегда каноническая, H только для РС/Грузчик/Закупщик
- **Нет reverse mapping** — position и custom_position читаются напрямую из Техлиста E и H
- **Approve — один линейный путь** — process_approve = оркестратор из 5 приватных функций
- **callback_data < 64 байт** — данные в dict, не в callback
- **D:AK "Plain text"** — предотвращает интерпретацию дат
- **value_input_option="RAW"** — для user data; "USER_ENTERED" только для формул
- **html.escape()** — защита от HTML injection
- **user_rates для расчёта**, rates только шаблон
- **Token efficiency** — новая вкладка per phase
- **app/db/models.py в .gitignore** — миграция на деплое
- **Решения сразу в docs**, не откладывать
- **admin_* могут вносить смены**: проверка роли в `/shift` включает `admin_hall/bar/kitchen`
- **SQLite WAL mode + timeout** — предотвращает "database is locked" при конкурентных запросах
- **PII в логах**: full_name не логируем, только telegram_id
- **admins видны при увольнении**: фильтр `role == 'user'` в dismiss убран

---

## Контактные данные

- **Developer Telegram ID:** `8624217185` (в .env как `DEVELOPER_ID`)
- **Test account Telegram ID:** `6073294261`
- **Client contact:** Ариф
- **Test restaurant:** Собственный ресторан Slenbder
