# Аудит кодовой базы HorecaTime — Блоки 3, 4, 5

**Дата:** 2026-05-29
**Объём:** все `.py` файлы (`app/`, `config.py`, `main.py`, `migrate_user_rates_once.py`) + директория `tests/`.
**Режим:** только поиск и доклад, код НЕ изменялся.
**Продолжение** аудита: Блоки 1–2 — в `AUDIT_BLOCKS_1_2.md`.

> Методическая заметка: системный `grep` в окружении — `ugrep` (при `-r` пропускает часть файлов). Все находки перепроверены через `find ... -exec grep` и прямым чтением файлов и AST-разбором.

---

## БЛОК 3: Архитектурные нелогичности

### 3.1 Дублирование логики между `admin.py`, `superadmin.py`, `auth.py`

| Что дублируется | Где | Приоритет |
|---|---|---|
| **`_fmt_money(v)`** — идентичная функция форматирования денег | `admin.py:85`, `superadmin.py:45`, `userreports.py:54` (3 копии) | **ВАЖНО** |
| **`_fmt(v)` / `_fmt_cell(v)`** — идентичное `str(int(v)) if v==int(v) else str(v)` | `google_sheets.py:98` (`_fmt_cell`), `google_sheets.py:740` (локальная), `auth.py:527`, `auth.py:645`, `userreports.py:50` (5 копий) | **ВАЖНО** |
| **`_fmt_emp_rate(emp)`** — форматирование ставки сотрудника, идентично | `admin.py:91`, `superadmin.py:49` (2 копии) | **ВАЖНО** |
| **Цикл рендеринга ставок** (get_user_rate → base/extra/label → future) | `admin.py:126-149` (`cmd_rates`) ≈ `superadmin.py:134-157` (`cmd_rates_all`) | **ВАЖНО** |
| **Словарь отдел→позиции** в 3 почти одинаковых вариантах | `admin.py:35` (`_DEPT_POSITIONS`), `superadmin.py:36` (`_DEPT_POSITIONS_ORDER`), `superadmin.py:231` (`_PROMOTE_VALID_POSITIONS`) | **ВАЖНО** |
| **Маппинг отдел↔admin_role** в 4 местах | `admin.py:25` (`_ROLE_TO_DEPT`), `superadmin.py:239` (`_DEPT_TO_ADMIN_ROLE`), `superadmin.py:477` (`_DEPT_TO_ADMIN_ROLES`), `models.py:454` (`role_map`) | **ВАЖНО** |
| **Клавиатуры выбора отдела** — 4 почти идентичных билдера (кнопки отделов + «Отмена») | `admin.py:67` (`_dept_keyboard`), `admin.py:76` (`_hall_dept_keyboard`), `superadmin.py:247` (`_promote_dept_keyboard`), `superadmin.py:502` (`_demote_dept_keyboard`) | **ВАЖНО** |
| **`_MONTH_NAMES`** — идентичный список сокращений месяцев | `admin.py:33`, `superadmin.py:34` (2 копии) | МИНОРНО |
| **Проверка прав** `tg_id in SUPERADMIN_IDS or tg_id == DEVELOPER_ID` | `superadmin.py:29` (`_is_allowed`), `admin.py:53` (`_resolve_sender_role`), `admin.py:209-210` (inline) | МИНОРНО |
| **`_get_admins_for_demote`** частично повторяет `get_admins_by_department` | `superadmin.py:485` vs `models.py:441` | МИНОРНО |
| **Ответ «⛔️ Недостаточно прав.»** повторяется ~10 раз дословно | `admin.py`, `superadmin.py` (множество) | МИНОРНО |

**Вывод:** напрашивается общий модуль `app/bot/handlers/_shared.py` (или `app/utils/formatting.py`) с `_fmt`, `_fmt_money`, `_fmt_emp_rate`, рендером ставок и фабрикой клавиатур отделов; справочники отделов/позиций/ролей — вынести в `config.py`.

### 3.2 Магические числа и строки вне `config.py`

(Исключения по ТЗ — TG_ID фантома `1984002026`, ставка `1500`, лимит 60 ч Бармена — НЕ репортятся.)

| Файл:строка | Магия | Приоритет |
|---|---|---|
| `google_sheets.py:713` | `set(range(4, 19)) \| set(range(20, 36))` — диапазоны колонок данных D–R/T–AI «зашиты» в код | **ВАЖНО** |
| `google_sheets.py:856` | `col = 3 + day if day <= 15 else 19 + (day - 15)` — формула день→колонка + порог `15` | **ВАЖНО** |
| `google_sheets.py:767,856,947-951,1042-1049`, `monthly_switch.py` | индексы итоговых колонок `19`(S)/`36`(AJ)/`37`(AK)/`38`(AL)/`39`(AM)/`40`(AN) разбросаны по коду (нет `COL_S=19` и т.п.) | **ВАЖНО** |
| `admin.py:31,237`, `superadmin.py:250,505`, `auth.py`, `models.py` | литерал `["Зал", "Бар", "Кухня", "МОП"]` захардкожен ~9 раз вместо общей константы | **ВАЖНО** |
| `auth.py:495,605` | `ah = value * 0.5` — коэффициент «0.5 ч за фото» магическим числом | МИНОРНО |
| `userhours.py:546,762,918`, др. | `asyncio.sleep(1.0)` — окно дебаунса медиагрупп без именованной константы | МИНОРНО |
| `admin.py:467` | `asyncio.sleep(0.05)` — троттл рассылки без константы | МИНОРНО |
| `google_sheets.py:1141,1174` | цвет `#FFCCCC` (`{1.0,0.8,0.8}`) и пороги `0.95/0.85` распознавания «красной» строки | МИНОРНО |
| `auth.py:500` | `2000 + int(year_s)` — век жёстко зашит при парсинге `DD.MM.YY` | МИНОРНО |
| `google_sheets.py:1271` | `last_col = "AN"` — последняя колонка строкой | МИНОРНО |

### 3.3 Проверка роли: SQLite vs константы `config.py`

**Нарушений не найдено — паттерн корректен и единообразен.**
- `RoleMiddleware` (`roles.py:39-48`): сначала `DEVELOPER_ID`/`SUPERADMIN_IDS` (config), затем `admin_*` через SQLite (`get_user_role`). ✓
- `superadmin._is_allowed` (`superadmin.py:29`): только config — верно для superadmin/developer. ✓
- `admin._resolve_sender_role` (`admin.py:52`): config-first, fallback в SQLite. ✓

| Файл:строка | Замечание | Приоритет |
|---|---|---|
| `roles_cache.py:17-26` | `RolesCacheService.get_user_role` назван «кешем», но на каждый вызов читает SQLite (`get_user`) — настоящего кеширования нет, имя вводит в заблуждение | МИНОРНО |
| `models.py:454` | `role_map` внутри `get_admins_by_department` — ещё одна копия отдел→роль (см. 3.1) | МИНОРНО |

### 3.4 Нарушения правила «не логировать PII»

Правило документировано: `docs/TECH_REFERENCE.md:717` — «**НЕ логировать** `full_name` — только `telegram_id`». Email маскируется корректно (`auth.py:1212` через `mask_email`); `format_alert` PII-безопасен (берёт только tg_id/position/department). Нарушения — логирование `full_name` в открытом виде:

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

### 3.5 Несоответствия паттерна уведомлений

**Нарушений не найдено — `get_admins_by_department()` используется единообразно** (15+ мест в `auth.py`, `userhours.py`), захардкоженных ID или старых констант для уведомлений нет. `get_admins_by_department` корректно объединяет админов отдела + `SUPERADMIN_IDS`.

| Файл:строка | Замечание | Приоритет |
|---|---|---|
| `superadmin.py:485` | `_get_admins_for_demote` делает свой SQL-запрос «админы отдела» вместо переиспользования `get_admins_by_department` (другой возвращаемый тип: dict vs list[int]) | МИНОРНО |

---

## БЛОК 4: Тестовое покрытие

### 4.6 Публичные функции БЕЗ тестов (26 + 2 «полых»)

#### `google_sheets.py` (`GoogleSheetsClient`)
Покрыты (реальная реализация): `write_check_filling_to_phantom`, `get_phantom_checks_summary`, `get_summary_hours`, `get_sheet_id_by_name`, `get_section_range` (+ приватная `_format_shift_value`). `ensure_user_in_current_month_hours` — частично (только простая ветка «Кухня»).

| Файл:строка | Функция | Риск |
|---|---|---|
| `google_sheets.py:651` | `write_shift(...)` — запись смены/часов, накопление выходных Раннера AM/AN. Везде замокана, реальная реализация не исполняется | **КРИТИЧНО** |
| `google_sheets.py:195` | `add_or_update_pending_user(...)` — запись заявок в Техлист | **КРИТИЧНО** |
| `google_sheets.py:1111` | `get_dismissed_rows(...)` — решает какие строки УДАЛИТЬ при смене месяца (распознавание цвета). Всегда заглушка `[]` | **КРИТИЧНО** |
| `google_sheets.py:1154` | `dismiss_employee(...)` — красит ячейку + удаляет строку из Техлиста (деструктивно) | **КРИТИЧНО** |
| `google_sheets.py:168` | `get_user_by_telegram_id(...)` — фундамент авторизации, только MagicMock | ВАЖНО |
| `google_sheets.py:258` | `is_user_approved(...)` — гейт доступа | ВАЖНО |
| `google_sheets.py:267` | `is_user_fully_authorized(...)` — гейт доступа | ВАЖНО |
| `google_sheets.py:300` | `mark_user_approved(...)` — запись статуса в Техлист | ВАЖНО |
| `google_sheets.py:320` | `user_exists_in_techlist(...)` — используется в switch_month | ВАЖНО |
| `google_sheets.py:1071` | `get_employees_by_dept(...)` — фильтр для увольнений | ВАЖНО |
| `google_sheets.py:314` | `get_user_from_techlist(...)` — тонкий алиас | МИНОРНО |

#### `models.py`
Покрыты: `get_user_rate`, `set_user_rate`, `set_user_rate_future`, `get_user_rate_future`, `delete_user_rate_future`, `get_all_future_rates`, `get_user_rate_history`, `snapshot_user_rates_history`.

| Файл:строка | Функция | Риск |
|---|---|---|
| `models.py:159` | `delete_user(...)` — каскадный DELETE по 4 таблицам; не импортируется ни одним тестом | **КРИТИЧНО** |
| `models.py:14` | `init_database()` — схема + миграции; тесты строят схему руками → дрейф не ловится | ВАЖНО |
| `models.py:89` | `save_user(...)` — основная персистенция пользователя | ВАЖНО |
| `models.py:111` | `get_user(...)` — используется везде, всегда патчится | ВАЖНО |
| `models.py:182` | `get_user_role(...)` — авторизация, всегда патчится | ВАЖНО |
| `models.py:213` | `get_all_users(...)` — список получателей рассылок | ВАЖНО |
| `models.py:390` | `get_users_rates_by_department(...)` — JOIN для set-rate | ВАЖНО |
| `models.py:441` | `get_admins_by_department(...)` — кто получает алерты | ВАЖНО |
| `models.py:138` | `get_users_by_role(...)` | МИНОРНО |
| `models.py:195` | `get_users_by_department(...)` | МИНОРНО |
| `models.py:415` | `get_all_users_rates(...)` (вдобавок — мёртвый код, см. Блок 2) | МИНОРНО |

#### `monthly_switch.py`
Покрыты: `apply_future_rates` (реальная БД), частично `switch_month` (только ветка форматирования).

| Файл:строка | Функция | Риск |
|---|---|---|
| `monthly_switch.py:576` | `notify_upcoming_switch(...)` — массовая рассылка, логика дедупликации/получателей не тестируется | ВАЖНО |
| `monthly_switch.py:605` | `notify_switch_done(...)` — массовая рассылка, не тестируется | ВАЖНО |
| `monthly_switch.py:29` | `get_next_sheet_name()` — хелпер дат | МИНОРНО |

#### `userreports.py`
Покрыты частично: `cmd_hours_first/second/last` — только ветка «ставка не задана»; `_build_hours_first/second_lines` — пути Официант/Раннер.

| Файл:строка | Функция | Риск |
|---|---|---|
| `userreports.py:326` | `cmd_schedule(...)` — генерация PDF-графика, гейтинг по роли — полностью без тестов | ВАЖНО |
| `userreports.py:387` | `cmd_sheet(...)` — статическая ссылка | МИНОРНО |

#### «Полое» покрытие (функция числится в тестах, но критичная логика не проверяется)

| Файл:строка | Что не покрыто | Риск |
|---|---|---|
| `monthly_switch.py:278` (`switch_month`) | Классификация уволенных/аномалий (`L470-499`), `batch_clear`+переустановка формул активных (`L503-517`), удаление строк снизу-вверх (`L532`) — единственный тест подаёт `get_all_values()==[]`, строки сотрудников не обрабатываются | **КРИТИЧНО** |
| `userreports.py:58` (`_build_runner_earnings_lines`) | Ветка `h_weekend > 0` (разбивка обычные/выходные часы — расчёт ЗП) никогда не исполняется (везде `h_weekend=0`) | **КРИТИЧНО** |

### 4.7 Тесты, проверяющие детали реализации вместо поведения (11)

| Файл:строка | Суть / почему хрупко | Приоритет |
|---|---|---|
| `test_fsm_states_new.py:15-26` | Интроспекция `ShiftStates.__dict__` и проверка **порядка объявления** атрибутов — чистая деталь реализации | **ВАЖНО** |
| `test_google_sheets_phantom.py:143,152,167` | `mock_ws.cell.assert_not_called()` — утверждает, что НЕ используется внутренний API `cell`; рефактор на `.cell()` сломает тест при том же результате | **ВАЖНО** |
| `test_plain_text_formatting.py:49-82` | Жёстко: `worksheets()` вызван ровно 3 раза (ordered `side_effect`) + разбор `batch_update.call_args_list` с точными `startRowIndex=4, sheetId=12345` | **ВАЖНО** |
| `test_google_sheets_methods/phantom/plain_text` (`:13-15/:16-18/:18-20`) | `object.__new__(GoogleSheetsClient)` + установка приватных `_spreadsheet`/`_client` — обход `__init__`, привязка к приватным атрибутам | Medium |
| `test_google_sheets_phantom.py:53,66-69,94,111-118` | Декодирование A1-адреса и проверка точных номеров колонок (4,18,20,35) + форма вызова `ws.update` | Medium |
| `test_plain_text_formatting.py:121-129` | `assert len(calls)==2` на `format` + точные диапазоны `"B4:B4"`, `"D4:AK4"` | Medium |
| `test_plain_text_formatting.py:146,164` | `assert position in _SIMPLE_H_POSITIONS` — обращение к приватному множеству модуля | Medium |
| `test_plain_text_formatting.py:150-173` | Проверка наличия токенов формул `ЛЕВСИМВ`/`ПСТР`/`СУММПРОИЗВ` в тексте формулы вместо результата | Medium |
| `test_phantom_transfer.py:112-124` | `assert_called_once` + точные диапазоны/`value_input_option=="USER_ENTERED"` | Medium |
| `test_approve_callbacks.py:36,58,...` | Чтение/запись приватных глобалей модуля `_pending_loyalty`/`_pending_filling` | Medium |
| `test_approve_callbacks.py:53-57`; `test_bar_ah_flow.py:249,273` | Проверка позиционных аргументов по индексу `write_shift.call_args[0][5]` — привязка к сигнатуре | МИНОРНО |

### 4.8 Дублирующиеся тесты (6 кластеров, все низкого приоритета)

| Кластер | Где | Суть |
|---|---|---|
| A | `test_google_sheets_methods.py:11-16`, `test_google_sheets_phantom.py:15-19`, `test_plain_text_formatting.py:16-21` | Фабрика `_make_client` (mock-клиент) скопирована 3 раза → вынести в `conftest.py` |
| B | `test_models_user_rates.py:13-52`, `test_apply_future_rates.py:17-56`, `test_user_rates_future.py:18-49`, `test_snapshot_user_rates.py:14-53` | Хелперы `_create_schema`/`_insert_user` скопированы 4 раза |
| C | `test_hours_without_rate.py:30,45,60` | Один и тот же сценарий «нет ставки → early-return» для трёх команд (можно параметризовать) |
| D | `test_google_sheets_phantom.py:43,57,86-118` | Маппинг день→колонка проверяется дважды |
| E | `test_user_rates_future.py:72,89` vs `test_apply_future_rates.py:77,105` | Создание будущей ставки + проверка персистентности дублируется |
| F | `test_google_sheets_phantom.py:71,169`, `test_phantom_transfer.py:127` | «фантом не найден → graceful no-op» в трёх местах |

---

## БЛОК 5: Порядок и стиль

### 5.9 Функции длиннее 60 строк (26 шт.) — кандидаты на декомпозицию

| Длина | Файл:строка | Функция | Как разбить |
|---|---|---|---|
| 296 | `monthly_switch.py:278` | `switch_month` | создание листа → перенос фантома → классификация строк (уволен/аномалия) → очистка+формулы активных → удаление уволенных → уведомления |
| 232 | `google_sheets.py:416` | `ensure_user_in_current_month_hours` | поиск секции/строки вставки → вставка строки → границы → TEXT-формат → построение+вставка формул S/AJ/AK |
| 142 | `auth.py:314` | `process_fio` | валидация ФИО → регистрация в Техлисте → уведомление админов |
| 136 | `google_sheets.py:651` | `write_shift` | поиск строки юзера → поиск колонки дня → запись ячейки → накопление выходных Раннера |
| 127 | `main.py:27` | `main` | init логов/Sentry → сборка Dispatcher+роутеры → регистрация планировщиков → запуск polling |
| 127 | `auth.py:682` | `approve_filling_callback` | парс+валидация callback → запись в Sheets → уведомления |
| 119 | `monthly_switch.py:156` | `_transfer_phantom_to_new_month` | поиск секции → вставка строки фантома → формулы → формат |
| 116 | `auth.py:563` | `approve_loyalty_callback` | парс → запись → уведомления |
| 104 | `google_sheets.py:788` | `write_check_filling_to_phantom` | резолв листа → поиск строки фантома → чтение+сумма → запись |
| 100 | `userhours.py:1215` | `_process_simple_h_shifts` | валидация → запись → отчёт+уведомление |
| 97 | `auth.py:462` | `approve_ah_callback` | парс → расчёт AH → запись → уведомления |
| 96 | `userhours.py:1113` | `_write_and_finish_bar` | сбор данных → запись смены → отчёт админам |
| 93 | `userhours.py:1321` | `_write_and_finish` | то же для Раннера |
| 91 | `google_sheets.py:976` | `get_summary_hours` | вынести `_parse_cell`/`_parse_simple` уже есть — извлечь чтение и сборку dict |
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

### 5.10 Нарушения соглашений об именовании

**В целом код следует `snake_case`; camelCase в собственном коде НЕ найден** (совпадения `maxBytes`/`backupCount`/`includeGridData` — параметры библиотек/REST, корректны).

| Файл:строка | Проблема | Приоритет |
|---|---|---|
| `auth.py:486`, `userhours.py:634,818,977` | Однобуквенная заглавная переменная `N` (кол-во фото) — неинформативно, против snake_case-стиля (лучше `photo_count`) | МИНОРНО |
| `superadmin.py:485` vs `models.py:441` | Один концепт «админы отдела» назван по-разному и с разной видимостью (`_get_admins_for_demote` private dict vs `get_admins_by_department` public list[int]) | МИНОРНО |
| `roles_cache.py:17` | `get_user_role` возвращает **dict** пользователя, а одноимённая `models.get_user_role` возвращает **str** роли — конфликт семантики при одинаковом имени | МИНОРНО |

Публичных функций с ошибочным `_`-префиксом не найдено (мёртвая `_format_rates_grouped` — см. Блок 2).

### 5.11 Несогласованность обработки ошибок

Доминирующий паттерн: `logger.exception(...)` (45 вызовов) либо `logger.error(..., exc_info=True)` (11) + `format_alert(...)` для операций с Sheets. Отклонения:

| Файл:строка | Проблема | Приоритет |
|---|---|---|
| `superadmin.py:216` | `logger.error("switch_month_confirm: ошибка ...: %s", e)` — **без** `exc_info` и без `format_alert` для критичной операции смены месяца (теряется трейсбек) | **ВАЖНО** |
| `google_sheets.py:1188,1213` | в `dismiss_employee` ошибки логируются `logger.error("...: %s", e)` **без** `exc_info` (деструктивная операция) | **ВАЖНО** |
| `monthly_switch.py:200-201, 350-351` | `except Exception: pass` — молчаливое проглатывание без лога | **ВАЖНО** |
| `auth.py:636-637, 752-753` | `except Exception: pass` — молчаливое проглатывание | МИНОРНО |
| `userhours.py:108-109` | `except Exception: pass` | МИНОРНО |
| `logging_config.py:93-94` | `except Exception: pass` (на этапе настройки логирования — условно допустимо) | МИНОРНО |
| Общая статистика | из 54 `logger.error` только 11 с `exc_info=True` → ~30+ мест в `except`-блоках теряют трейсбек; стоит унифицировать на `logger.exception` внутри `except` | **ВАЖНО** |

---

## Сводная таблица

| № | Пункт | Найдено | КРИТИЧНО | ВАЖНО | МИНОРНО |
|---|---|---|---|---|---|
| 3.1 | Дублирование admin/superadmin/auth | 11 | 0 | 7 | 4 |
| 3.2 | Магические числа/строки | 9 | 0 | 4 | 5 |
| 3.3 | Роль через SQLite vs config | 2 | 0 | 0 | 2 (нарушений нет) |
| 3.4 | PII (`full_name`) в логах | 8 | 0 | 7 | 1 |
| 3.5 | Паттерн уведомлений | 1 | 0 | 0 | 1 (нарушений нет) |
| 4.6 | Публичные функции без тестов | 26 (+2 «полых») | 6 | 13 | 9 |
| 4.7 | Тесты деталей реализации | 11 | 0 | 3 | 8 |
| 4.8 | Дублирующиеся тесты | 6 | 0 | 0 | 6 |
| 5.9 | Функции > 60 строк | 26 | 0 | 3 | 23 |
| 5.10 | Нарушения именования | 3 | 0 | 0 | 3 |
| 5.11 | Несогласованность обработки ошибок | 7 | 0 | 4 | 3 |

---

## Топ-5 проблем для исправления в первую очередь

1. **КРИТИЧНО — нет тестов на деструктивные/расчётные операции с реальной реализацией.** `write_shift`, `dismiss_employee`, `get_dismissed_rows`, `delete_user` всегда замоканы; ветка удаления/классификации внутри `switch_month` и расчёт выходных в `_build_runner_earnings_lines` не исполняются ни одним тестом. Это прямой риск молчаливой порчи часов/ЗП и ошибочного удаления сотрудников при смене месяца. (Блок 4.6)

2. **ВАЖНО — утечка PII (`full_name`) в логах вопреки документированному правилу** `TECH_REFERENCE.md:717`. 7 мест: `models.py:105`, `superadmin.py:387/437/571/616`, `auth.py:1171/1519`. Заменить `full_name` на `telegram_id` в логах. (Блок 3.4)

3. **ВАЖНО — потеря трейсбеков и молчаливые `except: pass`.** `superadmin.py:216` и `google_sheets.py:1188/1213` логируют критичные ошибки без `exc_info`; `monthly_switch.py:200/350`, `auth.py:636/752` глотают исключения без лога. Унифицировать на `logger.exception` в `except`-блоках. (Блок 5.11)

4. **ВАЖНО — массовое дублирование форматирования и справочников.** `_fmt`/`_fmt_money`/`_fmt_emp_rate` (3–5 копий), 4 копии маппинга отдел↔роль, 3 словаря отдел→позиции, 4 билдера клавиатур отделов, литерал `["Зал","Бар","Кухня","МОП"]` ~9 раз. Вынести в общий модуль + `config.py`. (Блоки 3.1, 3.2)

5. **ВАЖНО — переусложнённые функции в критичных путях.** `switch_month` (296 строк), `ensure_user_in_current_month_hours` (232), `write_shift` (136) тяжело тестировать и сопровождать; их декомпозиция (см. 5.9) напрямую облегчит закрытие пробелов из п.1. (Блок 5.9)
