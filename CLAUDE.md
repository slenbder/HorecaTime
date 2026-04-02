# HorecaTime — Контекст проекта

## Суть проекта
Python/aiogram 3 Telegram-бот для учёта рабочего времени в ресторане.  
Мигрируем с Google Apps Script (файлы скриптов доступны в ассетах проекта — референс логики).  
Репозиторий: https://github.com/slenbder/HorecaTime

---

## Текущий фокус

**Что делаем сейчас:** Персонализация ставок завершена (Этап 10+), аудит в процессе
**Активная ветка:** `fix/post-audit-bugs`  
**Roadmap:** AUDIT.md → Phase 2 завершение → Phase 3 (улучшения) → Docker → деплой

**Этап 10+ завершён:**
- Таблицы `user_rates` + `user_rates_history` в SQLite
- Миграция данных `migrate_user_rates_once.py`
- При апруве копируется шаблон из `rates` → `user_rates`
- `/rates` показывает персональные ставки (группировка, схлопывание одинаковых)
- `/set_rate` — FSM: позиция → сотрудник → базовая → повышенная (2 шага)
- `/rates_all` + `/set_rate_all` — для superadmin с выбором отдела
- `/hours_*` считают через `user_rates`
- Снимок `user_rates_history` при `switch_month()`

**Аудит Phase 1 ✅ завершена (5 критичных):**
1. `_pending_custom_titles` → FSM data (валидация 2-50 символов)
2. `/message_dept` включает МОП для admin_hall
3. Инъекция формул → `value_input_option="RAW"` в Google Sheets
4. HTML-escape через `html.escape()` для комментариев и упоминаний
5. `_delayed_process_waiter` обёрнут в try/except + state.clear()

**Аудит Phase 2 (в процессе):**
- Проверки ролей в callbacks
- Email маскировка в логах
- `make_mention()` вынесена в `app/utils/text_utils.py`
- Константы позиций консолидированы в `config.py`

---

## Стек

- Python 3.11+, aiogram 3.13.1
- gspread 6.1.2, oauth2client 4.1.3
- APScheduler 3.10.4, aiosqlite 0.20.0
- **SQLite** — FSM + кеш ролей + персональные ставки (НЕ основная БД данных сотрудников)
- **Google Sheets** — единственный источник данных сотрудников и смен (single source of truth)

---

## Критичные технические решения

### Терминология (важно!)
- **Отдел** (department) = Зал/Бар/Кухня/МОП — подразделение в ресторане
- **Позиция** (position) = Официант/Раннер/Бармен — роль сотрудника в отделе
- **Должность** (custom_title) = "Су-шеф Иванов" — персональное название только для Шеф/Су-шеф и Грузчик/Закупщик

### БД и архитектура
- **Google Sheets** = source of truth для всех данных сотрудников и смен
- **SQLite** = только FSM состояния + кеш ролей + персональные ставки (`user_rates`)
- Название месячного листа: `"{Месяц} {Год}"` (например "Март 2026")
- Техлист: A(TG_ID), B(@Ник), C(ФИО), D(Отдел), E(Позиция), F(Дата рег), G("ДА")
- Месячный лист: D:AK = "Обычный текст" формат (предотвращает интерпретацию чисел как дат)
- `value_input_option="RAW"` во всех операциях записи (защита от formula injection)

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
Ветка: fix/post-audit-bugs
Файл: app/bot/handlers/auth.py
Проблема: [описание бага]
Фикс: [шаги решения]
Требования: [проверки, pytest 37/37]
Commit: "fix(scope): описание"
```

### Правила работы
- **Один промпт = один баг** — последовательное выполнение
- Тесты (`pytest tests/` — 37/37 passing) после каждого фикса
- Прямые коммиты в feature-ветку (без PR до стабилизации)
- Решения формализуются в документацию **в реальном времени**
- Token efficiency: новая вкладка per phase, минимум файлов в контексте

### Обработка вопросов Claude Code
- Структурные/технические → Slenbder отвечает напрямую
- Бизнес-логика/неоднозначности → консультация с Claude (claude.ai)
- Ответы ищем в AUDIT.md (раздел "Предложение" для каждого бага)

---

## Ключевые паттерны и принципы

### Логирование
- **НИКОГДА** `print()` — только `logging`
- Три лог-файла: `app.log` (общий), `errors.log` (ошибки), `googleapi.log` (Sheets API)
- Email маскируется: `p***r@gmail.com` через `mask_email()` из `app/utils/text_utils.py`
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
- Формулы S/AJ/AK вставляются автоматически
- AL/AM/AN = числовой формат (выходные часы Раннера)

---

## Важные файлы проекта

- **AUDIT.md** — живой роадмап багов (Phases 1-3)
- **CLAUDE.md** — этот файл, контекст проекта
- **HISTORY.md** — архив завершённых этапов 0-10
- **TECH_REFERENCE.md** — схемы БД, маппинги, примеры сообщений
- **config.py** — константы, ID, списки позиций
- **app/utils/text_utils.py** — `make_mention()`, `mask_email()`
- **app/db/models.py** — в .gitignore! Требует миграцию на деплое
- **migrate_user_rates_once.py** — одноразовая миграция (оставлен как документация)

---

## На горизонте

### Ближайшие задачи
- **Phase 2 завершение** — тесты, зависимости, .env.example
- **Phase 3** — улучшения из AUDIT.md
- **Docker** setup и деплой
- **Apps Script миграция** (отложено)

### Долгосрочные планы
- **Лицензионная система** (license server + PyArmor)
- **Web-панель** для конфигурации
- **Модель подписки**
- **Универсализация** для сторонних клиентов

---

## Key Learnings

- **Отдел ≠ Позиция ≠ Должность** — путаница в терминах ведёт к багам
- **callback_data < 64 байт** — данные в dict, не в callback
- **D:AK "Plain text"** — предотвращает интерпретацию дат
- **value_input_option="RAW"** — защита от formula injection
- **html.escape()** — защита от HTML injection
- **user_rates для расчёта**, rates только шаблон
- **Token efficiency** — новая вкладка per phase
- **AUDIT.md line numbers устаревают** — использовать `~244` + контекст
- **app/db/models.py в .gitignore** — миграция на деплое
- **Решения сразу в docs**, не откладывать

---

## Контактные данные

- **Developer Telegram ID:** `8624217185` (в .env как `DEVELOPER_ID`)
- **Test account Telegram ID:** `6073294261`
- **Client contact:** Ариф
- **Test restaurant:** Собственный ресторан Slenbder
