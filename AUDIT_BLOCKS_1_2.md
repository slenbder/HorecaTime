# Аудит кодовой базы HorecaTime — Блоки 1 и 2

**Дата:** 2026-05-29
**Объём:** все `.py` файлы проекта (`app/`, `config.py`, `main.py`, `migrate_user_rates_once.py`). Тесты учитывались только как «места вызова».
**Режим:** только поиск и доклад, код НЕ изменялся.

> Методическая заметка: системный `grep` в окружении — это `ugrep`, который при `-r` пропускает часть файлов. Все ключевые находки перепроверены детерминированно через `find ... -exec grep` и прямым чтением файлов.

---

## БЛОК 1: Корректность и потенциальные баги

### 1. `float()` без `.replace(",", ".")`

Контекст: при русской локали Google Sheets значения приходят как `"1,5"` — `float("1,5")` бросает `ValueError`.

**Результат: критичных багов не найдено.** Все пользовательские вводы нормализуются `.replace(",", ".")` до `float()`.

| Файл:строка | Ситуация | Приоритет |
|---|---|---|
| `app/bot/handlers/admin.py:349` | `base_rate = float(text)` — но `text` уже `.strip().replace(",", ".")` на строке 347. Безопасно. | OK |
| `app/bot/handlers/admin.py:375` | `extra_rate = float(text)` — `text` нормализован на 373. Безопасно. | OK |
| `app/bot/handlers/userhours.py:374` | `ah = float(text)` — `text` нормализован на 371. Безопасно. | OK |
| `app/bot/handlers/userhours.py:1095` | `ah_raw = float(text)` — `text` нормализован на 1092. Безопасно. | OK |
| `app/services/google_sheets.py:958` | `int(float(value))` — `value` уже `.replace(",", ".")` на 956. Безопасно. | OK |
| `app/bot/handlers/auth.py:485` | `h = float(parts[3])` — **единственный** `float()` без `.replace()`. Источник — `callback.data`, сгенерированный самим ботом через `_fmt()` (всегда с точкой), поэтому риск низкий. Для надёжности стоит обернуть/нормализовать. | **МИНОРНО** |

Все `float()` внутри `google_sheets.py` (строки 84, 88, 93, 775, 861, 1019, 1023, 1028, 1038) содержат `.replace(",", ".")`.

---

### 2. `ws.update_cell()` (gspread)

`update_cell` нельзя передать `value_input_option`; по умолчанию использует `USER_ENTERED`. Рекомендуется заменять на `ws.update(..., value_input_option="RAW")`.

**Найдено 5 вызовов.** Ни один сейчас не падает (никому не передаётся `value_input_option`), но все пишут с дефолтным `USER_ENTERED`.

| Файл:строка | Что пишется | Риск | Приоритет |
|---|---|---|---|
| `app/services/google_sheets.py:779` | `update_cell(user_row, weekend_col, new_val)` — **число** `float` (накопленные выходные часы Раннера) с `USER_ENTERED` | Несогласованность с `RAW` везде вокруг + риск локали при интерпретации числа/даты | **ВАЖНО** |
| `app/services/google_sheets.py:306` | `update_cell(row_index, COL_IN_STAFF_TABLE, "ДА")` — текст | Безвредно (не число/дата), но стоит унифицировать | МИНОРНО |
| `app/services/google_sheets.py:311` | то же, в ветке после реконнекта | Безвредно | МИНОРНО |
| `app/scheduler/monthly_switch.py:434` | `update_cell(2, 3, MONTH_NAMES_RU[...])` — название месяца (текст) | Безвредно | МИНОРНО |
| `app/scheduler/monthly_switch.py:435` | `update_cell(2, 20, next_year)` — год (int) | Безвредно (число) | МИНОРНО |

---

### 3. `value_input_option` не указан / `USER_ENTERED` для пользовательских данных

Требование: для пользовательских данных — `"RAW"`, `"USER_ENTERED"` допустим только для формул.

**Результат: нарушений не найдено.** Все три `USER_ENTERED` применяются исключительно к формулам:

| Файл:строка | Содержимое | Вердикт |
|---|---|---|
| `app/services/google_sheets.py:635` | формулы `=СУММПРОИЗВ(...)` / `=...` для S/AJ/AK | `USER_ENTERED` корректно |
| `app/scheduler/monthly_switch.py:252` | формулы `=SUM(...)` фантома | `USER_ENTERED` корректно |
| `app/scheduler/monthly_switch.py:516` | формулы S/AJ/AK при очистке месяца | `USER_ENTERED` корректно |

Все записи пользовательских данных (`add_or_update_pending_user`, `write_shift`, `write_check_filling_to_phantom`, `ensure_user...insert_row`) используют `"RAW"`. Дополнительно неявный `USER_ENTERED` приходит от `update_cell` — см. пункт 2.

---

### 4. Сетевые вызовы `GoogleSheetsClient` без паттерна `try/except + _reconnect() + повтор`

Эталонный паттерн (есть в `mark_user_approved`, `write_shift`, `write_check_filling_to_phantom`, `get_phantom_checks_summary`, `get_summary_hours`, `get_employees_by_dept`, `get_sheet_id_by_name`, `get_section_range`): обернуть сетевой вызов в `try`, при ошибке `self._reconnect()` и повторить.

Методы с неполной защитой:

| Файл:строка | Метод | Проблема | Приоритет |
|---|---|---|---|
| `app/services/google_sheets.py:174` | `get_user_by_telegram_id` | `ws.get_all_values()` не обёрнут (реконнект есть только на получение листа в `_get_techlist_worksheet`); сбой чтения не повторяется | **ВАЖНО** |
| `app/services/google_sheets.py:209,220,248` | `add_or_update_pending_user` | `get_all_values`, `batch_update`, `update` — **запись заявки** без `try/except + _reconnect + повтор` | **ВАЖНО** |
| `app/services/google_sheets.py:327` | `user_exists_in_techlist` | `ws.get_all_values()` без защиты | **ВАЖНО** |
| `app/services/google_sheets.py:445,510` | `ensure_user_in_current_month_hours` | `get_all_values` (445) и **критичная вставка** `insert_row` (510) без `_reconnect`-повтора; `batch_update`/`format` лишь логируют warning | **ВАЖНО** |
| `app/services/google_sheets.py:1154` | `dismiss_employee` | `format` и `delete_rows` в `try/except`, но **без** `_reconnect`/повтора — только лог ошибки; удаление строки из Техлиста может молча не выполниться | **ВАЖНО** |
| `app/services/google_sheets.py:779` | `write_shift` (хвост) | `update_cell` для выходных Раннера вне защищённого реконнектом блока | МИНОРНО |
| `app/services/google_sheets.py:276` | `is_user_fully_authorized` | `get_all_values` в `try/except` → `return False`, но без `_reconnect`/повтора | МИНОРНО |
| `app/services/google_sheets.py:1111` | `get_dismissed_rows` | прямой REST-вызов в `try/except` без реконнекта (безопасный дефолт — пустое множество) | МИНОРНО |
| `app/services/google_sheets.py:148` | `_auto_resize_columns` | `try/except` без реконнекта (косметика — ширина столбцов) | МИНОРНО |

---

### 5. FSM-обработчики без явного `state.clear()` при ошибке

Глобальный обработчик `@dp.error()` в `main.py:71` логирует/алертит, но **НЕ сбрасывает FSM-состояние**. Значит необработанное исключение в хендлере, выставившем state, оставляет пользователя «зависшим».

Общая ситуация хорошая: основные хендлеры (`process_fio`, `process_shift_input`, `_write_and_finish*`, `_apply_rate_change`, ветки `dismiss_*`/`promote_*`/`demote_*`) корректно вызывают `state.clear()` в `except`. Найден реальный пробел:

| Файл:строка | Обработчик | Проблема | Приоритет |
|---|---|---|---|
| `app/bot/handlers/auth.py:1343` | `dismiss_select` (state `waiting_dismiss_confirm`) | сетевой вызов `sheets_client.get_user_from_techlist(target_id)` на строке 1352 **не обёрнут** в `try/except`; при сбое исключение уходит в глобальный хендлер, `state.clear()` не вызывается → пользователь застревает в `waiting_dismiss_confirm` | **ВАЖНО** |

> Хендлеры, которые при ошибке валидации делают `return` (с просьбой ввести значение заново), сознательно НЕ чистят state — это корректный повтор ввода, не пробел.

---

### 6. `telegram_id` / числа пишутся как `str()` вместо `int/float`

Контекст: строки не суммируются формулой `=СУММ()`.

**Результат: реальных багов суммирования нет.** Все найденные `str(...)` — это `telegram_id` (идентификатор, не суммируется) либо часы в формате `"H/AH"`, которые суммируются формулами через `ЗНАЧЕН()/ПОДСТАВИТЬ()`, а не `=СУММ()`.

| Файл:строка | Что | Вердикт | Приоритет |
|---|---|---|---|
| `app/services/google_sheets.py:238` | `str(telegram_id)` → колонка A Техлиста | По дизайну: ID, поиск по строковому сравнению, не суммируется | МИНОРНО (by design) |
| `app/services/google_sheets.py:511` | `str(telegram_id)` → колонка B месячного листа | По дизайну: для колонки B явно задаётся TEXT-формат (строки 562-565), чтобы Sheets не интерпретировал как число/дату | МИНОРНО (by design) |
| `app/services/google_sheets.py:743,747` | часы `cell_value` (`"8/1.5"`) пишутся строкой через `RAW` | По дизайну: формат `H/AH`, суммируется формулами S/AJ; `=СУММ()` к ним не применяется | OK |

Числовые значения, которые действительно должны суммироваться, пишутся числами: чеки фантома — `int new_checks` (`google_sheets.py:868,875`), выходные Раннера — `float new_val` (`779`).

---

## БЛОК 2: Мёртвый и избыточный код

### 7. Неиспользуемые импорты (5)

(проверено `pyflakes 3.4.0` + ручная сверка)

| Файл:строка | Импорт | Примечание |
|---|---|---|
| `app/bot/handlers/auth.py:32` | `SHEET_URL` | импортируется из `config`, но не используется в этом файле (используется в `userreports.py`) |
| `app/scheduler/monthly_switch.py:8` | `DB_PATH` | импортируется из `config`, не используется |
| `app/bot/keyboards/common.py:1` | `InlineKeyboardButton` | импортируется, не используется |
| `app/bot/fsm/admin_states.py:1` | `State` | импортируется, не используется (файл состоит только из этой строки — модуль фактически пустой) |
| `app/bot/fsm/admin_states.py:1` | `StatesGroup` | импортируется, не используется (та же строка) |

### 8. Объявленные, но не вызываемые функции/методы (4)

Проверено `find ... -exec grep` по всему дереву (включая тесты):

| Файл:строка | Символ | Примечание | Приоритет |
|---|---|---|---|
| `app/services/timeparsing.py:89` | `check_overlap()` | обычная функция, вызывается **только в тестах** — мёртвая в проде | МИНОРНО |
| `app/services/roles_cache.py:39` | `clear_cache()` (`@staticmethod`) | не вызывается нигде | МИНОРНО |
| `app/bot/handlers/superadmin.py:68` | `_format_rates_grouped()` | не вызывается (реально используется `_format_position_group`) | МИНОРНО |
| `app/db/models.py:415` | `get_all_users_rates()` | не вызывается (используются `get_all_users` / `get_users_rates_by_department`) | МИНОРНО |

> Уточнение: декорированные aiogram-хендлеры (`@*_router.message/.callback_query`), напрямую вызываемые только из тестов (`process_department`, `process_position`, `cmd_set_rate`, `cb_bar_ah_yes/no`, `cmd_hours_first/second` и т.п.), **НЕ являются мёртвым кодом** — они регистрируются декоратором и вызываются фреймворком в рантайме. Также не мёртвые: `set_data` (`fsm_storage.py:37`, override `BaseStorage`), `emit` (`logging_config.py:74`, override `logging.Handler`), `global_error_handler` (`main.py:72`, `@dp.error()`).

### 9. Неиспользуемые константы `config.py` (0 мёртвых, 1 только в тестах)

Все 13 констант имеют реальное использование, кроме одной, что есть только в тесте:

| Файл:строка | Константа | Примечание | Приоритет |
|---|---|---|---|
| `config.py:54` | `PHANTOM_CHECK_FILLING_NAME` | используется только в `tests/test_phantom_constants.py` (тест проверяет сам факт её существования); в проде не используется | МИНОРНО |

Остальные (`BOT_TOKEN`, `SUPERADMIN_IDS`, `DEVELOPER_ID`, `POSITIONS_WITH_EXTRA`, `EXTRA_RATE_LABELS`, `GOOGLE_CREDENTIALS_PATH`, `SPREADSHEET_ID`, `DB_PATH`, `TECH_SHEET_NAME`, `SHEET_URL`, `SENTRY_DSN`, `PHANTOM_CHECK_FILLING_ID`, `PHANTOM_HOURLY_RATE`) — используются. `SENTRY_DSN` используется через локальный импорт в `app/logging_config.py:107`.

### 10. Закомментированный код (0)

Закомментированного исполняемого кода не найдено. Комментарии в `google_sheets.py` (строки 465, 627-629, 766) и др. — пояснительные (описывают колонки/формулы таблицы), не отключённый код.

### 11. TODO / FIXME / HACK / XXX (0)

Маркеров `TODO`, `FIXME`, `HACK`, `XXX` в кодовой базе нет.

---

## Бонус (вне запрошенных категорий, найдено `pyflakes`)

| Файл:строка | Проблема | Приоритет |
|---|---|---|
| `main.py:160` | повторный `import logging` внутри `except` (модуль уже импортирован на строке 2) — затенение, безвредно | МИНОРНО |
| `app/bot/handlers/auth.py:332` | локальная переменная `tg_name` присваивается, но нигде не используется | МИНОРНО |

---

## Сводная таблица

| № | Пункт | Найдено | КРИТИЧНО | ВАЖНО | МИНОРНО / OK |
|---|---|---|---|---|---|
| 1 | `float()` без `.replace()` | 1 (потенц.) | 0 | 0 | 1 |
| 2 | `ws.update_cell()` | 5 | 0 | 1 | 4 |
| 3 | `value_input_option` ≠ RAW для данных | 0 | 0 | 0 | 0 (все USER_ENTERED — формулы) |
| 4 | Сетевые вызовы без `try/except+_reconnect+повтор` | 9 | 0 | 5 | 4 |
| 5 | FSM без `state.clear()` при ошибке | 1 | 0 | 1 | 0 |
| 6 | Числа/`telegram_id` как `str()` | 3 | 0 | 0 | 3 (by design) |
| 7 | Неиспользуемые импорты | 5 | — | — | 5 |
| 8 | Неиспользуемые функции/методы | 4 | — | — | 4 |
| 9 | Неиспользуемые константы `config.py` | 1 | — | — | 1 (только в тестах) |
| 10 | Закомментированный код | 0 | — | — | 0 |
| 11 | TODO/FIXME/HACK/XXX | 0 | — | — | 0 |
| — | Бонус (shadow import, unused var) | 2 | — | — | 2 |

**Итого по приоритетам (Блок 1):** КРИТИЧНО — 0, ВАЖНО — 7, МИНОРНО — 8.

### Рекомендуемый порядок устранения (Блок 1)
1. **ВАЖНО** — `dismiss_employee` (`google_sheets.py:1154`): добавить `_reconnect`+повтор для `delete_rows` (иначе сотрудник может «не уволиться» молча).
2. **ВАЖНО** — `add_or_update_pending_user` (`209/220/248`): обернуть запись заявки в `try/except+_reconnect+повтор`.
3. **ВАЖНО** — `ensure_user...insert_row` (`510`): защитить вставку строки реконнектом.
4. **ВАЖНО** — `get_user_by_telegram_id` (`174`) и `user_exists_in_techlist` (`327`): защитить чтение.
5. **ВАЖНО** — `dismiss_select` (`auth.py:1343/1352`): обернуть `get_user_from_techlist` в `try/except` + `state.clear()`.
6. **ВАЖНО** — `write_shift` (`779`): заменить `update_cell` на `ws.update(..., value_input_option="RAW")`.
7. Остальные `update_cell` и косметические — по желанию для единообразия.
