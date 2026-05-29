# Аудит кодовой базы HorecaTime — полный отчёт (Блоки 1–5)

**Дата:** 2026-05-29
**Объём:** все `.py` файлы проекта (`app/`, `config.py`, `main.py`, `migrate_user_rates_once.py`) + директория `tests/`.
**Режим:** только поиск и доклад — исходный код НЕ изменялся.

> Методическая заметка: системный `grep` в окружении — это `ugrep` (при `-r` пропускает часть файлов). Все ключевые находки перепроверены детерминированно через `find ... -exec grep`, прямым чтением файлов, AST-разбором и `pyflakes`.

---

## Оглавление

- [Блок 1. Корректность и потенциальные баги](#блок-1-корректность-и-потенциальные-баги)
  - [1.1 `float()` без `.replace(",", ".")`](#11-float-без-replace)
  - [1.2 `ws.update_cell()`](#12-wsupdate_cell)
  - [1.3 `value_input_option` для пользовательских данных](#13-value_input_option-для-пользовательских-данных)
  - [1.4 Сетевые вызовы без `try/except + _reconnect() + повтор`](#14-сетевые-вызовы-без-tryexcept--_reconnect--повтор)
  - [1.5 FSM-обработчики без `state.clear()` при ошибке](#15-fsm-обработчики-без-stateclear-при-ошибке)
  - [1.6 Числа/`telegram_id` как `str()`](#16-числаtelegram_id-как-str)
- [Блок 2. Мёртвый и избыточный код](#блок-2-мёртвый-и-избыточный-код)
  - [2.7 Неиспользуемые импорты](#27-неиспользуемые-импорты)
  - [2.8 Неиспользуемые функции/методы](#28-неиспользуемые-функцииметоды)
  - [2.9 Неиспользуемые константы `config.py`](#29-неиспользуемые-константы-configpy)
  - [2.10 Закомментированный код](#210-закомментированный-код)
  - [2.11 TODO/FIXME/HACK/XXX](#211-todofixmehackxxx)
- [Блок 3. Архитектурные нелогичности](#блок-3-архитектурные-нелогичности)
  - [3.1 Дублирование логики admin/superadmin/auth](#31-дублирование-логики-adminsuperadminauth)
  - [3.2 Магические числа и строки](#32-магические-числа-и-строки)
  - [3.3 Проверка роли: SQLite vs config](#33-проверка-роли-sqlite-vs-config)
  - [3.4 PII (`full_name`) в логах](#34-pii-full_name-в-логах)
  - [3.5 Паттерн уведомлений](#35-паттерн-уведомлений)
- [Блок 4. Тестовое покрытие](#блок-4-тестовое-покрытие)
  - [4.6 Публичные функции без тестов](#46-публичные-функции-без-тестов)
  - [4.7 Тесты деталей реализации](#47-тесты-деталей-реализации-вместо-поведения)
  - [4.8 Дублирующиеся тесты](#48-дублирующиеся-тесты)
- [Блок 5. Порядок и стиль](#блок-5-порядок-и-стиль)
  - [5.9 Функции длиннее 60 строк](#59-функции-длиннее-60-строк)
  - [5.10 Нарушения именования](#510-нарушения-именования)
  - [5.11 Несогласованность обработки ошибок](#511-несогласованность-обработки-ошибок)
- [Сводная таблица по всем блокам](#сводная-таблица-по-всем-блокам)
- [Топ-10 проблем для первоочередного исправления](#топ-10-проблем-для-первоочередного-исправления)

---
---

# Блок 1. Корректность и потенциальные баги

## 1.1 `float()` без `.replace()`

Контекст: при русской локали Google Sheets значения приходят как `"1,5"` — `float("1,5")` бросает `ValueError`.

**Результат: критичных багов не найдено.** Все пользовательские вводы нормализуются `.replace(",", ".")` до `float()`.

| Файл:строка | Ситуация | Приоритет |
|---|---|---|
| `app/bot/handlers/admin.py:349` | `base_rate = float(text)` — `text` уже `.strip().replace(",", ".")` (стр. 347). Безопасно. | OK |
| `app/bot/handlers/admin.py:375` | `extra_rate = float(text)` — `text` нормализован (стр. 373). Безопасно. | OK |
| `app/bot/handlers/userhours.py:374` | `ah = float(text)` — `text` нормализован (стр. 371). Безопасно. | OK |
| `app/bot/handlers/userhours.py:1095` | `ah_raw = float(text)` — `text` нормализован (стр. 1092). Безопасно. | OK |
| `app/services/google_sheets.py:958` | `int(float(value))` — `value` уже `.replace(",", ".")` (стр. 956). Безопасно. | OK |
| `app/bot/handlers/auth.py:485` | `h = float(parts[3])` — **единственный** `float()` без `.replace()`. Источник — `callback.data` от самого бота (`_fmt()`, всегда с точкой), риск низкий. | МИНОРНО |

Все `float()` внутри `google_sheets.py` (84, 88, 93, 775, 861, 1019, 1023, 1028, 1038) содержат `.replace(",", ".")`.

## 1.2 `ws.update_cell()`

`update_cell` не принимает `value_input_option`; по умолчанию использует `USER_ENTERED`. Рекомендуется заменять на `ws.update(..., value_input_option="RAW")`.

**Найдено 5 вызовов.** Ни один не падает (никому не передаётся `value_input_option`), но все пишут с дефолтным `USER_ENTERED`.

| Файл:строка | Что пишется | Риск | Приоритет |
|---|---|---|---|
| `app/services/google_sheets.py:779` | `update_cell(user_row, weekend_col, new_val)` — **число** `float` (выходные часы Раннера) с `USER_ENTERED` | Несогласованность с `RAW` + риск локали | **ВАЖНО** |
| `app/services/google_sheets.py:306` | `update_cell(row_index, COL_IN_STAFF_TABLE, "ДА")` — текст | Безвредно | МИНОРНО |
| `app/services/google_sheets.py:311` | то же, ветка после реконнекта | Безвредно | МИНОРНО |
| `app/scheduler/monthly_switch.py:434` | `update_cell(2, 3, MONTH_NAMES_RU[...])` — название месяца (текст) | Безвредно | МИНОРНО |
| `app/scheduler/monthly_switch.py:435` | `update_cell(2, 20, next_year)` — год (int) | Безвредно | МИНОРНО |

## 1.3 `value_input_option` для пользовательских данных

Требование: для пользовательских данных — `"RAW"`, `"USER_ENTERED"` допустим только для формул.

**Результат: нарушений не найдено.** Все три `USER_ENTERED` применяются исключительно к формулам:

| Файл:строка | Содержимое | Вердикт |
|---|---|---|
| `app/services/google_sheets.py:635` | формулы `=СУММПРОИЗВ(...)` для S/AJ/AK | корректно |
| `app/scheduler/monthly_switch.py:252` | формулы `=SUM(...)` фантома | корректно |
| `app/scheduler/monthly_switch.py:516` | формулы S/AJ/AK при очистке месяца | корректно |

Все записи пользовательских данных используют `"RAW"`. Неявный `USER_ENTERED` приходит только от `update_cell` — см. 1.2.

## 1.4 Сетевые вызовы без `try/except + _reconnect() + повтор`

Эталонный паттерн есть в `mark_user_approved`, `write_shift`, `write_check_filling_to_phantom`, `get_phantom_checks_summary`, `get_summary_hours`, `get_employees_by_dept`, `get_sheet_id_by_name`, `get_section_range`. Методы с неполной защитой:

| Файл:строка | Метод | Проблема | Приоритет |
|---|---|---|---|
| `google_sheets.py:174` | `get_user_by_telegram_id` | `ws.get_all_values()` не обёрнут; сбой чтения не повторяется | **ВАЖНО** |
| `google_sheets.py:209,220,248` | `add_or_update_pending_user` | **запись заявки** без `try/except + _reconnect + повтор` | **ВАЖНО** |
| `google_sheets.py:327` | `user_exists_in_techlist` | `ws.get_all_values()` без защиты | **ВАЖНО** |
| `google_sheets.py:445,510` | `ensure_user_in_current_month_hours` | `get_all_values` и **критичная вставка** `insert_row` без `_reconnect`-повтора | **ВАЖНО** |
| `google_sheets.py:1154` | `dismiss_employee` | `format`/`delete_rows` в `try/except`, но **без** `_reconnect`/повтора — удаление из Техлиста может молча не выполниться | **ВАЖНО** |
| `google_sheets.py:779` | `write_shift` (хвост) | `update_cell` для выходных Раннера вне защищённого блока | МИНОРНО |
| `google_sheets.py:276` | `is_user_fully_authorized` | `get_all_values` → `return False`, без `_reconnect`/повтора | МИНОРНО |
| `google_sheets.py:1111` | `get_dismissed_rows` | REST-вызов без реконнекта (безопасный дефолт — пустое множество) | МИНОРНО |
| `google_sheets.py:148` | `_auto_resize_columns` | `try/except` без реконнекта (косметика) | МИНОРНО |

## 1.5 FSM-обработчики без `state.clear()` при ошибке

Глобальный обработчик `@dp.error()` (`main.py:71`) логирует/алертит, но **НЕ сбрасывает FSM-состояние** — необработанное исключение в хендлере, выставившем state, оставляет пользователя «зависшим». Общее покрытие хорошее (`process_fio`, `process_shift_input`, `_write_and_finish*`, `_apply_rate_change`, ветки `dismiss/promote/demote` чистят state в `except`). Реальный пробел:

| Файл:строка | Обработчик | Проблема | Приоритет |
|---|---|---|---|
| `app/bot/handlers/auth.py:1343` | `dismiss_select` (state `waiting_dismiss_confirm`) | сетевой вызов `get_user_from_techlist` (стр. 1352) **не обёрнут**; при сбое `state.clear()` не вызывается → пользователь застревает | **ВАЖНО** |

> Хендлеры, делающие `return` при ошибке валидации (просьба ввести значение заново), сознательно НЕ чистят state — это корректный повтор ввода, не пробел.

## 1.6 Числа/`telegram_id` как `str()`

Контекст: строки не суммируются формулой `=СУММ()`.

**Результат: реальных багов суммирования нет.** Все `str(...)` — это `telegram_id` (идентификатор, не суммируется) либо часы в формате `"H/AH"`, которые суммируются формулами через `ЗНАЧЕН()/ПОДСТАВИТЬ()`, а не `=СУММ()`.

| Файл:строка | Что | Вердикт | Приоритет |
|---|---|---|---|
| `google_sheets.py:238` | `str(telegram_id)` → колонка A Техлиста | По дизайну: ID, строковое сравнение | МИНОРНО (by design) |
| `google_sheets.py:511` | `str(telegram_id)` → колонка B месячного листа | По дизайну: для B явно задаётся TEXT-формат (562-565) | МИНОРНО (by design) |
| `google_sheets.py:743,747` | часы `cell_value` (`"8/1.5"`) пишутся строкой через `RAW` | По дизайну: суммируются формулами S/AJ | OK |

Числа, которые реально суммируются, пишутся числами: чеки фантома `int` (868, 875), выходные Раннера `float` (779).

---
---

# Блок 2. Мёртвый и избыточный код

## 2.7 Неиспользуемые импорты

(проверено `pyflakes 3.4.0` + ручная сверка)

| Файл:строка | Импорт | Примечание |
|---|---|---|
| `app/bot/handlers/auth.py:32` | `SHEET_URL` | не используется в файле (используется в `userreports.py`) |
| `app/scheduler/monthly_switch.py:8` | `DB_PATH` | не используется |
| `app/bot/keyboards/common.py:1` | `InlineKeyboardButton` | не используется |
| `app/bot/fsm/admin_states.py:1` | `State` | не используется (файл — только эта строка, модуль фактически пустой) |
| `app/bot/fsm/admin_states.py:1` | `StatesGroup` | не используется (та же строка) |

## 2.8 Неиспользуемые функции/методы

Проверено `find ... -exec grep` по всему дереву (включая тесты):

| Файл:строка | Символ | Примечание | Приоритет |
|---|---|---|---|
| `app/services/timeparsing.py:89` | `check_overlap()` | вызывается **только в тестах** — мёртвая в проде | МИНОРНО |
| `app/services/roles_cache.py:39` | `clear_cache()` (`@staticmethod`) | не вызывается нигде | МИНОРНО |
| `app/bot/handlers/superadmin.py:68` | `_format_rates_grouped()` | не вызывается (используется `_format_position_group`) | МИНОРНО |
| `app/db/models.py:415` | `get_all_users_rates()` | не вызывается (используются `get_all_users` / `get_users_rates_by_department`) | МИНОРНО |

> Уточнение: декорированные aiogram-хендлеры (`@*_router.message/.callback_query`), напрямую вызываемые только из тестов (`process_department`, `cmd_set_rate`, `cb_bar_ah_yes/no` и т.п.), **НЕ являются мёртвым кодом** — они регистрируются декоратором и вызываются фреймворком. Также не мёртвые: `set_data` (`fsm_storage.py:37`, override `BaseStorage`), `emit` (`logging_config.py:74`, override `logging.Handler`), `global_error_handler` (`main.py:72`, `@dp.error()`).

## 2.9 Неиспользуемые константы `config.py`

Все 13 констант используются, кроме одной — только в тесте:

| Файл:строка | Константа | Примечание | Приоритет |
|---|---|---|---|
| `config.py:54` | `PHANTOM_CHECK_FILLING_NAME` | используется только в `tests/test_phantom_constants.py` (проверка факта существования); в проде не используется | МИНОРНО |

Остальные (`BOT_TOKEN`, `SUPERADMIN_IDS`, `DEVELOPER_ID`, `POSITIONS_WITH_EXTRA`, `EXTRA_RATE_LABELS`, `GOOGLE_CREDENTIALS_PATH`, `SPREADSHEET_ID`, `DB_PATH`, `TECH_SHEET_NAME`, `SHEET_URL`, `SENTRY_DSN`, `PHANTOM_CHECK_FILLING_ID`, `PHANTOM_HOURLY_RATE`) — используются. `SENTRY_DSN` — через локальный импорт в `app/logging_config.py:107`.

## 2.10 Закомментированный код

**Не найдено.** Комментарии в `google_sheets.py` (465, 627-629, 766) и др. — пояснительные (описывают колонки/формулы таблицы), не отключённый код.

## 2.11 TODO/FIXME/HACK/XXX

**Не найдено** ни одного маркера во всей кодовой базе.

### Бонус (вне запрошенных категорий, найдено `pyflakes`)

| Файл:строка | Проблема | Приоритет |
|---|---|---|
| `main.py:160` | повторный `import logging` внутри `except` (модуль импортирован на стр. 2) — затенение, безвредно | МИНОРНО |
| `app/bot/handlers/auth.py:332` | локальная переменная `tg_name` присваивается, но нигде не используется | МИНОРНО |

---
---

# Блок 3. Архитектурные нелогичности

## 3.1 Дублирование логики admin/superadmin/auth

| Что дублируется | Где | Приоритет |
|---|---|---|
| **`_fmt_money(v)`** — идентичное форматирование денег | `admin.py:85`, `superadmin.py:45`, `userreports.py:54` (3 копии) | **ВАЖНО** |
| **`_fmt(v)` / `_fmt_cell(v)`** — `str(int(v)) if v==int(v) else str(v)` | `google_sheets.py:98`, `google_sheets.py:740`, `auth.py:527`, `auth.py:645`, `userreports.py:50` (5 копий) | **ВАЖНО** |
| **`_fmt_emp_rate(emp)`** — форматирование ставки, идентично | `admin.py:91`, `superadmin.py:49` (2 копии) | **ВАЖНО** |
| **Цикл рендеринга ставок** (get_user_rate → base/extra/label → future) | `admin.py:126-149` (`cmd_rates`) ≈ `superadmin.py:134-157` (`cmd_rates_all`) | **ВАЖНО** |
| **Словарь отдел→позиции** в 3 почти одинаковых вариантах | `admin.py:35` (`_DEPT_POSITIONS`), `superadmin.py:36` (`_DEPT_POSITIONS_ORDER`), `superadmin.py:231` (`_PROMOTE_VALID_POSITIONS`) | **ВАЖНО** |
| **Маппинг отдел↔admin_role** в 4 местах | `admin.py:25` (`_ROLE_TO_DEPT`), `superadmin.py:239` (`_DEPT_TO_ADMIN_ROLE`), `superadmin.py:477` (`_DEPT_TO_ADMIN_ROLES`), `models.py:454` (`role_map`) | **ВАЖНО** |
| **Клавиатуры выбора отдела** — 4 почти идентичных билдера | `admin.py:67` (`_dept_keyboard`), `admin.py:76` (`_hall_dept_keyboard`), `superadmin.py:247` (`_promote_dept_keyboard`), `superadmin.py:502` (`_demote_dept_keyboard`) | **ВАЖНО** |
| **`_MONTH_NAMES`** — идентичный список сокращений | `admin.py:33`, `superadmin.py:34` (2 копии) | МИНОРНО |
| **Проверка прав** `tg_id in SUPERADMIN_IDS or tg_id == DEVELOPER_ID` | `superadmin.py:29`, `admin.py:53`, `admin.py:209-210` | МИНОРНО |
| **`_get_admins_for_demote`** частично повторяет `get_admins_by_department` | `superadmin.py:485` vs `models.py:441` | МИНОРНО |
| **«⛔️ Недостаточно прав.»** повторяется ~10 раз дословно | `admin.py`, `superadmin.py` | МИНОРНО |

**Вывод:** напрашивается общий модуль (`app/utils/formatting.py` + `_shared.py`) с `_fmt`/`_fmt_money`/`_fmt_emp_rate`, рендером ставок и фабрикой клавиатур; справочники отделов/позиций/ролей — в `config.py`.

## 3.2 Магические числа и строки

(Исключения по ТЗ — TG_ID фантома `1984002026`, ставка `1500`, лимит 60 ч Бармена — НЕ репортятся.)

| Файл:строка | Магия | Приоритет |
|---|---|---|
| `google_sheets.py:713` | `set(range(4, 19)) \| set(range(20, 36))` — диапазоны колонок данных «зашиты» | **ВАЖНО** |
| `google_sheets.py:856` | `col = 3 + day if day <= 15 else 19 + (day - 15)` + порог `15` | **ВАЖНО** |
| `google_sheets.py:767,856,947-951,1042-1049`, `monthly_switch.py` | индексы колонок `19`(S)/`36`(AJ)/`37`(AK)/`38`(AL)/`39`(AM)/`40`(AN) разбросаны (нет `COL_S=19` и т.п.) | **ВАЖНО** |
| `admin.py:31,237`, `superadmin.py:250,505`, `auth.py`, `models.py` | литерал `["Зал", "Бар", "Кухня", "МОП"]` захардкожен ~9 раз | **ВАЖНО** |
| `auth.py:495,605` | `ah = value * 0.5` — коэффициент «0.5 ч за фото» | МИНОРНО |
| `userhours.py:546,762,918`, др. | `asyncio.sleep(1.0)` — окно дебаунса медиагрупп | МИНОРНО |
| `admin.py:467` | `asyncio.sleep(0.05)` — троттл рассылки | МИНОРНО |
| `google_sheets.py:1141,1174` | цвет `#FFCCCC` (`{1.0,0.8,0.8}`) и пороги `0.95/0.85` | МИНОРНО |
| `auth.py:500` | `2000 + int(year_s)` — век жёстко зашит | МИНОРНО |
| `google_sheets.py:1271` | `last_col = "AN"` — последняя колонка строкой | МИНОРНО |

## 3.3 Проверка роли: SQLite vs config

**Нарушений не найдено — паттерн корректен и единообразен.**
- `RoleMiddleware` (`roles.py:39-48`): сначала `DEVELOPER_ID`/`SUPERADMIN_IDS` (config), затем `admin_*` через SQLite (`get_user_role`). ✓
- `superadmin._is_allowed` (`superadmin.py:29`): только config — верно. ✓
- `admin._resolve_sender_role` (`admin.py:52`): config-first, fallback в SQLite. ✓

| Файл:строка | Замечание | Приоритет |
|---|---|---|
| `roles_cache.py:17-26` | `RolesCacheService.get_user_role` назван «кешем», но на каждый вызов читает SQLite (`get_user`) — настоящего кеширования нет | МИНОРНО |
| `models.py:454` | `role_map` внутри `get_admins_by_department` — ещё одна копия отдел→роль (см. 3.1) | МИНОРНО |

## 3.4 PII (`full_name`) в логах

Правило документировано: `docs/TECH_REFERENCE.md:717` — «**НЕ логировать** `full_name` — только `telegram_id`». Email маскируется корректно (`auth.py:1212` через `mask_email`); `format_alert` PII-безопасен. Нарушения — `full_name` в открытом виде:

| Файл:строка | Проблема | Приоритет |
|---|---|---|
| `app/db/models.py:105` | `logger.info("Пользователь %s (%s) сохранён ...", telegram_id, full_name, role)` | **ВАЖНО** |
| `app/bot/handlers/superadmin.py:387` | `logger.info("promote_select: ... (%s)", ..., full_name)` | **ВАЖНО** |
| `app/bot/handlers/superadmin.py:437` | `logger.info("promote_confirm: %s ...", full_name, ...)` | **ВАЖНО** |
| `app/bot/handlers/superadmin.py:571` | `logger.info("demote_select: ... (%s)", ..., full_name)` | **ВАЖНО** |
| `app/bot/handlers/superadmin.py:616` | `logger.info("demote_confirm: %s ...", full_name, ...)` | **ВАЖНО** |
| `app/bot/handlers/auth.py:1171` | `logger.info("Пользователь %s (%s) отправляет сообщение разработчику", tg_id, full_name)` | **ВАЖНО** |
| `app/bot/handlers/auth.py:1519` | `logger.info("Сотрудник %s (%s) уволен ...", target_id, full_name, admin_id)` | **ВАЖНО** |
| `migrate_user_rates_once.py:55,67,70` | `full_name` в логах разового скрипта миграции | МИНОРНО |

## 3.5 Паттерн уведомлений

**Нарушений не найдено — `get_admins_by_department()` используется единообразно** (15+ мест в `auth.py`, `userhours.py`), захардкоженных ID или старых констант нет. Функция корректно объединяет админов отдела + `SUPERADMIN_IDS`.

| Файл:строка | Замечание | Приоритет |
|---|---|---|
| `superadmin.py:485` | `_get_admins_for_demote` делает свой SQL-запрос вместо переиспользования `get_admins_by_department` (другой тип: dict vs list[int]) | МИНОРНО |

---
---

# Блок 4. Тестовое покрытие

## 4.6 Публичные функции без тестов

**26 функций без тестов + 2 «полых» (числятся в тестах, но критичная логика не проверяется).**

### `google_sheets.py` (`GoogleSheetsClient`)
Покрыты (реальная реализация): `write_check_filling_to_phantom`, `get_phantom_checks_summary`, `get_summary_hours`, `get_sheet_id_by_name`, `get_section_range`, `_format_shift_value`. `ensure_user_in_current_month_hours` — частично (только простая ветка «Кухня»).

| Файл:строка | Функция | Риск |
|---|---|---|
| `google_sheets.py:651` | `write_shift(...)` — запись смены/часов, накопление выходных Раннера. Везде замокана | **КРИТИЧНО** |
| `google_sheets.py:195` | `add_or_update_pending_user(...)` — запись заявок в Техлист | **КРИТИЧНО** |
| `google_sheets.py:1111` | `get_dismissed_rows(...)` — решает какие строки УДАЛИТЬ при смене месяца. Всегда заглушка `[]` | **КРИТИЧНО** |
| `google_sheets.py:1154` | `dismiss_employee(...)` — красит ячейку + удаляет строку из Техлиста (деструктивно) | **КРИТИЧНО** |
| `google_sheets.py:168` | `get_user_by_telegram_id(...)` — фундамент авторизации | ВАЖНО |
| `google_sheets.py:258` | `is_user_approved(...)` — гейт доступа | ВАЖНО |
| `google_sheets.py:267` | `is_user_fully_authorized(...)` — гейт доступа | ВАЖНО |
| `google_sheets.py:300` | `mark_user_approved(...)` — запись статуса | ВАЖНО |
| `google_sheets.py:320` | `user_exists_in_techlist(...)` — используется в switch_month | ВАЖНО |
| `google_sheets.py:1071` | `get_employees_by_dept(...)` — фильтр для увольнений | ВАЖНО |
| `google_sheets.py:314` | `get_user_from_techlist(...)` — тонкий алиас | МИНОРНО |

### `models.py`
Покрыты: `get_user_rate`, `set_user_rate`, `set_user_rate_future`, `get_user_rate_future`, `delete_user_rate_future`, `get_all_future_rates`, `get_user_rate_history`, `snapshot_user_rates_history`.

| Файл:строка | Функция | Риск |
|---|---|---|
| `models.py:159` | `delete_user(...)` — каскадный DELETE по 4 таблицам; не импортируется тестами | **КРИТИЧНО** |
| `models.py:14` | `init_database()` — схема + миграции; тесты строят схему руками → дрейф не ловится | ВАЖНО |
| `models.py:89` | `save_user(...)` — основная персистенция пользователя | ВАЖНО |
| `models.py:111` | `get_user(...)` — используется везде, всегда патчится | ВАЖНО |
| `models.py:182` | `get_user_role(...)` — авторизация | ВАЖНО |
| `models.py:213` | `get_all_users(...)` — получатели рассылок | ВАЖНО |
| `models.py:390` | `get_users_rates_by_department(...)` — JOIN для set-rate | ВАЖНО |
| `models.py:441` | `get_admins_by_department(...)` — кто получает алерты | ВАЖНО |
| `models.py:138` | `get_users_by_role(...)` | МИНОРНО |
| `models.py:195` | `get_users_by_department(...)` | МИНОРНО |
| `models.py:415` | `get_all_users_rates(...)` (вдобавок мёртвый код — см. 2.8) | МИНОРНО |

### `monthly_switch.py`
Покрыты: `apply_future_rates` (реальная БД), частично `switch_month` (только ветка форматирования).

| Файл:строка | Функция | Риск |
|---|---|---|
| `monthly_switch.py:576` | `notify_upcoming_switch(...)` — массовая рассылка, логика дедупликации не тестируется | ВАЖНО |
| `monthly_switch.py:605` | `notify_switch_done(...)` — массовая рассылка, не тестируется | ВАЖНО |
| `monthly_switch.py:29` | `get_next_sheet_name()` — хелпер дат | МИНОРНО |

### `userreports.py`
Покрыты частично: `cmd_hours_first/second/last` — только ветка «ставка не задана»; `_build_hours_first/second_lines` — пути Официант/Раннер.

| Файл:строка | Функция | Риск |
|---|---|---|
| `userreports.py:326` | `cmd_schedule(...)` — генерация PDF-графика, гейтинг по роли — полностью без тестов | ВАЖНО |
| `userreports.py:387` | `cmd_sheet(...)` — статическая ссылка | МИНОРНО |

### «Полое» покрытие

| Файл:строка | Что не покрыто | Риск |
|---|---|---|
| `monthly_switch.py:278` (`switch_month`) | Классификация уволенных/аномалий (470-499), `batch_clear`+формулы активных (503-517), удаление строк (532) — тест подаёт `get_all_values()==[]`, строки не обрабатываются | **КРИТИЧНО** |
| `userreports.py:58` (`_build_runner_earnings_lines`) | Ветка `h_weekend > 0` (расчёт ЗП с разбивкой) никогда не исполняется | **КРИТИЧНО** |

## 4.7 Тесты деталей реализации вместо поведения

| Файл:строка | Суть / почему хрупко | Приоритет |
|---|---|---|
| `test_fsm_states_new.py:15-26` | Интроспекция `ShiftStates.__dict__` + проверка **порядка объявления** атрибутов | **ВАЖНО** |
| `test_google_sheets_phantom.py:143,152,167` | `mock_ws.cell.assert_not_called()` — утверждает, что НЕ используется внутренний API | **ВАЖНО** |
| `test_plain_text_formatting.py:49-82` | Жёстко: `worksheets()` вызван ровно 3 раза + разбор `batch_update.call_args_list` с точными `startRowIndex=4, sheetId=12345` | **ВАЖНО** |
| `test_google_sheets_methods/phantom/plain_text` (`:13-15/16-18/18-20`) | `object.__new__(GoogleSheetsClient)` + установка приватных `_spreadsheet`/`_client` | Medium |
| `test_google_sheets_phantom.py:53,66-69,94,111-118` | Декодирование A1-адреса и проверка точных номеров колонок | Medium |
| `test_plain_text_formatting.py:121-129` | `assert len(calls)==2` на `format` + точные диапазоны `"B4:B4"` | Medium |
| `test_plain_text_formatting.py:146,164` | `assert position in _SIMPLE_H_POSITIONS` — приватное множество модуля | Medium |
| `test_plain_text_formatting.py:150-173` | Проверка токенов формул `ЛЕВСИМВ`/`ПСТР` вместо результата | Medium |
| `test_phantom_transfer.py:112-124` | `assert_called_once` + точные диапазоны/`value_input_option` | Medium |
| `test_approve_callbacks.py:36,58,...` | Чтение/запись приватных глобалей `_pending_loyalty`/`_pending_filling` | Medium |
| `test_approve_callbacks.py:53-57`; `test_bar_ah_flow.py:249,273` | Проверка позиционных аргументов по индексу `write_shift.call_args[0][5]` | МИНОРНО |

## 4.8 Дублирующиеся тесты

6 кластеров, все низкого приоритета:

| Кластер | Где | Суть |
|---|---|---|
| A | `test_google_sheets_methods.py:11-16`, `test_google_sheets_phantom.py:15-19`, `test_plain_text_formatting.py:16-21` | Фабрика `_make_client` скопирована 3 раза → в `conftest.py` |
| B | `test_models_user_rates.py:13-52`, `test_apply_future_rates.py:17-56`, `test_user_rates_future.py:18-49`, `test_snapshot_user_rates.py:14-53` | Хелперы `_create_schema`/`_insert_user` скопированы 4 раза |
| C | `test_hours_without_rate.py:30,45,60` | Сценарий «нет ставки → early-return» для трёх команд (параметризовать) |
| D | `test_google_sheets_phantom.py:43,57,86-118` | Маппинг день→колонка проверяется дважды |
| E | `test_user_rates_future.py:72,89` vs `test_apply_future_rates.py:77,105` | Создание будущей ставки + проверка персистентности дублируется |
| F | `test_google_sheets_phantom.py:71,169`, `test_phantom_transfer.py:127` | «фантом не найден → graceful no-op» в трёх местах |

---
---

# Блок 5. Порядок и стиль

## 5.9 Функции длиннее 60 строк

26 функций. Кандидаты на декомпозицию (по убыванию длины):

| Длина | Файл:строка | Функция | Как разбить |
|---|---|---|---|
| 296 | `monthly_switch.py:278` | `switch_month` | создание листа → перенос фантома → классификация строк → очистка+формулы активных → удаление уволенных → уведомления |
| 232 | `google_sheets.py:416` | `ensure_user_in_current_month_hours` | поиск секции/строки → вставка → границы → TEXT-формат → построение+вставка формул |
| 142 | `auth.py:314` | `process_fio` | валидация ФИО → регистрация в Техлисте → уведомление админов |
| 136 | `google_sheets.py:651` | `write_shift` | поиск строки юзера → поиск колонки дня → запись ячейки → накопление выходных Раннера |
| 127 | `main.py:27` | `main` | init логов/Sentry → сборка Dispatcher+роутеры → регистрация планировщиков → запуск polling |
| 127 | `auth.py:682` | `approve_filling_callback` | парс+валидация → запись в Sheets → уведомления |
| 119 | `monthly_switch.py:156` | `_transfer_phantom_to_new_month` | поиск секции → вставка строки → формулы → формат |
| 116 | `auth.py:563` | `approve_loyalty_callback` | парс → запись → уведомления |
| 104 | `google_sheets.py:788` | `write_check_filling_to_phantom` | резолв листа → поиск строки фантома → чтение+сумма → запись |
| 100 | `userhours.py:1215` | `_process_simple_h_shifts` | валидация → запись → отчёт+уведомление |
| 97 | `auth.py:462` | `approve_ah_callback` | парс → расчёт AH → запись → уведомления |
| 96 | `userhours.py:1113` | `_write_and_finish_bar` | сбор данных → запись смены → отчёт админам |
| 93 | `userhours.py:1321` | `_write_and_finish` | то же для Раннера |
| 91 | `google_sheets.py:976` | `get_summary_hours` | извлечь чтение и сборку dict (парсеры уже вынесены) |
| 85 | `auth.py:1002` | `process_approve` | резолв → регистрация → доступ → уведомление |
| 80 | `google_sheets.py:893` | `get_phantom_checks_summary` | резолв листа → поиск строки → парс значения |
| 79 | `auth.py:1441` | `dismiss_confirm_handler` | подтверждение → удаление из Sheets+SQLite → уведомления |
| 79 | `auth.py:109` | `cmd_start` | проверка статуса → ветки guest/pending/approved |
| 78 | `userhours.py:277` | `process_shift_input` | парс ввода → запись → отчёт |
| 75 | `userhours.py:466` | `_write_waiter_no_photo` | — |
| 74 | `userhours.py:543` | `_delayed_process_waiter` | — |
| 73 | `models.py:14` | `init_database` | разбить по таблицам/миграциям |
| 71 | `superadmin.py:595` | `cb_demote_confirm` | смена роли → уведомление сотрудника → уведомление суперадминов |
| 64 | `userhours.py:619` | `_send_waiter_report` | — |
| 62 | `google_sheets.py:1154` | `dismiss_employee` | окраска месячного листа / удаление из Техлиста — две независимые операции |
| 62 | `google_sheets.py:195` | `add_or_update_pending_user` | ветка update / ветка insert |

Приоритет: `switch_month`, `ensure_user_in_current_month_hours`, `write_shift` — **ВАЖНО** (большие + критичные); остальные — МИНОРНО.

## 5.10 Нарушения именования

**В целом код следует `snake_case`; camelCase в собственном коде НЕ найден** (совпадения `maxBytes`/`backupCount`/`includeGridData` — параметры библиотек/REST).

| Файл:строка | Проблема | Приоритет |
|---|---|---|
| `auth.py:486`, `userhours.py:634,818,977` | Однобуквенная заглавная `N` (кол-во фото) — против snake_case (лучше `photo_count`) | МИНОРНО |
| `superadmin.py:485` vs `models.py:441` | Один концепт «админы отдела» назван по-разному и с разной видимостью | МИНОРНО |
| `roles_cache.py:17` | `get_user_role` возвращает **dict** пользователя, а `models.get_user_role` — **str** роли: конфликт семантики при одинаковом имени | МИНОРНО |

Публичных функций с ошибочным `_`-префиксом не найдено (мёртвая `_format_rates_grouped` — см. 2.8).

## 5.11 Несогласованность обработки ошибок

Доминирующий паттерн: `logger.exception(...)` (45 вызовов) либо `logger.error(..., exc_info=True)` (11) + `format_alert(...)` для Sheets-операций. Отклонения:

| Файл:строка | Проблема | Приоритет |
|---|---|---|
| `superadmin.py:216` | `logger.error("switch_month_confirm: ошибка ...: %s", e)` — **без** `exc_info` и `format_alert` для критичной операции смены месяца | **ВАЖНО** |
| `google_sheets.py:1188,1213` | в `dismiss_employee` ошибки логируются **без** `exc_info` (деструктивная операция) | **ВАЖНО** |
| `monthly_switch.py:200-201, 350-351` | `except Exception: pass` — молчаливое проглатывание без лога | **ВАЖНО** |
| Общая статистика | из 54 `logger.error` только 11 с `exc_info=True` → много мест в `except`-блоках теряют трейсбек; унифицировать на `logger.exception` | **ВАЖНО** |
| `auth.py:636-637, 752-753` | `except Exception: pass` — молчаливое проглатывание | МИНОРНО |
| `userhours.py:108-109` | `except Exception: pass` | МИНОРНО |
| `logging_config.py:93-94` | `except Exception: pass` (на этапе настройки логирования — условно допустимо) | МИНОРНО |

---
---

# Сводная таблица по всем блокам

| Блок | Пункт | Найдено | КРИТИЧНО | ВАЖНО | МИНОРНО / OK |
|---|---|---|---|---|---|
| 1 | 1.1 `float()` без `.replace()` | 1 (потенц.) | 0 | 0 | 1 |
| 1 | 1.2 `ws.update_cell()` | 5 | 0 | 1 | 4 |
| 1 | 1.3 `value_input_option` для данных | 0 | 0 | 0 | 0 (нарушений нет) |
| 1 | 1.4 Сетевые вызовы без реконнект-повтора | 9 | 0 | 5 | 4 |
| 1 | 1.5 FSM без `state.clear()` при ошибке | 1 | 0 | 1 | 0 |
| 1 | 1.6 Числа/`telegram_id` как `str()` | 3 | 0 | 0 | 3 (by design) |
| 2 | 2.7 Неиспользуемые импорты | 5 | — | — | 5 |
| 2 | 2.8 Неиспользуемые функции | 4 | — | — | 4 |
| 2 | 2.9 Неиспользуемые константы | 1 | — | — | 1 |
| 2 | 2.10 Закомментированный код | 0 | — | — | 0 |
| 2 | 2.11 TODO/FIXME/HACK/XXX | 0 | — | — | 0 |
| 2 | Бонус (shadow import, unused var) | 2 | — | — | 2 |
| 3 | 3.1 Дублирование admin/superadmin/auth | 11 | 0 | 7 | 4 |
| 3 | 3.2 Магические числа/строки | 9 | 0 | 4 | 5 |
| 3 | 3.3 Роль через SQLite vs config | 2 | 0 | 0 | 2 (нарушений нет) |
| 3 | 3.4 PII (`full_name`) в логах | 8 | 0 | 7 | 1 |
| 3 | 3.5 Паттерн уведомлений | 1 | 0 | 0 | 1 (нарушений нет) |
| 4 | 4.6 Публичные функции без тестов | 26 (+2 «полых») | 6 | 13 | 9 |
| 4 | 4.7 Тесты деталей реализации | 11 | 0 | 3 | 8 |
| 4 | 4.8 Дублирующиеся тесты | 6 | 0 | 0 | 6 |
| 5 | 5.9 Функции > 60 строк | 26 | 0 | 3 | 23 |
| 5 | 5.10 Нарушения именования | 3 | 0 | 0 | 3 |
| 5 | 5.11 Несогласованность обработки ошибок | 7 | 0 | 4 | 3 |

**Итого по приоритетам:** КРИТИЧНО — 6 · ВАЖНО — 48 · МИНОРНО/OK — ~88.
Все КРИТИЧНЫЕ — в Блоке 4 (тестовое покрытие деструктивных и расчётных функций).

---

# Топ-10 проблем для первоочередного исправления

1. **КРИТИЧНО — нет тестов на деструктивные/расчётные операции с реальной реализацией.** `write_shift`, `dismiss_employee`, `get_dismissed_rows`, `delete_user` всегда замоканы; ветка удаления/классификации внутри `switch_month` и расчёт выходных в `_build_runner_earnings_lines` не исполняются. Прямой риск молчаливой порчи часов/ЗП и ошибочного удаления сотрудников при смене месяца. *(4.6)*

2. **ВАЖНО — утечка PII (`full_name`) в логах** вопреки документированному правилу `TECH_REFERENCE.md:717`. 7 мест: `models.py:105`, `superadmin.py:387/437/571/616`, `auth.py:1171/1519`. Заменить `full_name` на `telegram_id`. *(3.4)*

3. **ВАЖНО — записи в Sheets без `try/except + _reconnect() + повтор`.** Особенно `dismiss_employee` (`delete_rows`), `add_or_update_pending_user`, `ensure_user…insert_row`, чтения в `get_user_by_telegram_id`/`user_exists_in_techlist`. Риск молчаливого несрабатывания операций при сетевом сбое. *(1.4)*

4. **ВАЖНО — потеря трейсбеков и молчаливые `except: pass`.** `superadmin.py:216`, `google_sheets.py:1188/1213` логируют критичные ошибки без `exc_info`; `monthly_switch.py:200/350`, `auth.py:636/752` глотают исключения без лога. Унифицировать на `logger.exception` в `except`-блоках. *(5.11)*

5. **ВАЖНО — `dismiss_select` оставляет пользователя в «зависшем» FSM-состоянии** при сбое сети (`auth.py:1343/1352`): сетевой вызов без `try/except`, глобальный `@dp.error()` state не чистит. Обернуть в `try/except` + `state.clear()`. *(1.5)*

6. **ВАЖНО — `update_cell` с числом и дефолтным `USER_ENTERED`** в `write_shift` (`google_sheets.py:779`, выходные Раннера). Заменить на `ws.update(..., value_input_option="RAW")`. *(1.2)*

7. **ВАЖНО — массовое дублирование форматирования и справочников.** `_fmt`/`_fmt_money`/`_fmt_emp_rate` (3–5 копий), 4 копии маппинга отдел↔роль, 3 словаря отдел→позиции, 4 билдера клавиатур, литерал `["Зал","Бар","Кухня","МОП"]` ~9 раз. Вынести в общий модуль + `config.py`. *(3.1, 3.2)*

8. **ВАЖНО — переусложнённые функции в критичных путях.** `switch_month` (296), `ensure_user_in_current_month_hours` (232), `write_shift` (136) тяжело тестировать; декомпозиция (5.9) напрямую облегчит закрытие пробелов из п.1. *(5.9)*

9. **ВАЖНО — магические индексы колонок Sheets** (`19/36/37/38/39/40`, `range(4,19)|range(20,36)`, формула день→колонка) разбросаны по `google_sheets.py`/`monthly_switch.py`. Вынести в именованные константы — снизит риск ошибок при правках раскладки таблицы. *(3.2)*

10. **МИНОРНО — мёртвый код и неиспользуемые импорты.** 4 мёртвые функции (`check_overlap`, `clear_cache`, `_format_rates_grouped`, `get_all_users_rates`), 5 неиспользуемых импортов, 1 константа только в тестах. Быстрая безопасная чистка. *(2.7–2.9)*
