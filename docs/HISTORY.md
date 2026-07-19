# История этапов разработки HorecaTime

Этот файл содержит детальную историю всех завершённых этапов разработки проекта. Актуальное состояние проекта см. в **CLAUDE.md**.

---

## chore/scheduler-switch-day-25 ✅ завершён (2026-06-29)

- APScheduler: дата автопереключения сдвинута с 1-го на **25-е** число
- `notify_upcoming_switch`: `CronTrigger(day=1, hour=12, ...)` → `CronTrigger(day=25, ...)`
- `switch_month`: `CronTrigger(day=1, hour=18, ...)` → `CronTrigger(day=25, ...)`
- Мотив: график следующего месяца готовится заранее; вывод переключения из окна 1-го числа
- Файл: `main.py` (строки 117, 123)
- Этап 9 (исходное описание шедулера) не изменён — это история

---

## refactor/switch-month-batch-writes ✅ завершён (2026-06-29)

Переработка `switch_month()` для устранения 429 Write quota и fail-loud.

### Диагностика (до фикса)
При N≈40 сотрудниках: C_w + 2·T + R + 3 ≈ 93 write-запроса построчно без батчинга → 429.
- `rows_to_clear` loop: 2 write/строка (`batch_clear` + `batch_update` формул)
- `rows_to_delete` loop: 1 write/строка (`delete_rows` по одной)
- Ошибки проглатывались в цикле: 40 алертов вместо 1
- Фантом искал "официант" в колонке A, а заголовок секции в колонке C → "не найдена"

### Шаг 1 — Фантом: правильный поиск секции
- `_transfer_phantom_to_new_month` теперь использует `GoogleSheetsClient._find_insert_row_for_section(all_data, "Официанты")` — ищет заголовок в колонке C (A/B пустые), как оно и есть в листе
- Секция не найдена → `raise RuntimeError` (propagates в switch_month → алерт)
- Убран внешний `try/except` из функции — ошибки вставки теперь не глотаются
- Тесты: +3 (finds by C, no false positive on A, raises on absent)

### Шаг 2 — Батч-очистка смен: 2·T → 2
- `rows_to_clear` loop заменён: собираем все диапазоны → один `batch_clear([все])` + один `batch_update([все формулы], USER_ENTERED)`
- Формулы `_make_formulas()` не тронуты (русские СУММПРОИЗВ, типы по позиции)
- Тесты: +6

### Шаг 3 — Батч-удаление строк: R → 1
- `rows_to_delete` loop с `delete_rows()` заменён одним `batch_update({"requests": [deleteDimension…]})`
- Запросы упорядочены по убыванию (сохранён инвариант `reverse=True`)
- `sheetId` из `new_ws.id`
- Тесты: +5

### Шаг 4 — 429 backoff + fail-loud
- `GoogleSheetsClient._call(fn, *args, **kwargs)`: централизованный wrapper
  - `APIError(429)` → `sleep(2s)`, `sleep(4s)`, raise после 3-й попытки; **reconnect не вызывается**
  - Другие ошибки → propagate немедленно
- Все batch-вызовы в switch_month через `sheets_client._call(...)`
- Провал батча → `RuntimeError("этап 'X' упал ... удалите вручную")` → один внятный алерт разработчику
- Тесты: +8

### Итог
**Было:** ~93 write-запроса, 429 при N≈40, 40 алертов на одну ошибку, фантом не находил секцию  
**Стало:** ~10 write-запросов (константа), 429-backoff без reconnect, fail-loud с одним алертом  
**Тесты:** 170 → 192 (22 новых теста, все зелёные)  
**Ветка:** refactor/switch-month-batch-writes → main

---

## Этап 0 ✅ завершён

- Полный approve-flow авторизации (FSM AuthStates)
- GoogleSheetsClient с _reconnect()
- RolesCacheService (SQLite)
- RoleMiddleware (импорт из config, circular import устранён)
- SQLiteStorage для FSM (состояния переживают рестарт)
- Клавиатуры выбора отдела и позиции (включая позицию «Менеджер»)
- Роль `developer` (DEVELOPER_ID из env, проверяется в middleware перед superadmin)
- `main_menu_keyboard(role)` с inline-кнопкой «Написать разработчику» для всех ролей кроме `developer`

---

## Этап 1 ✅ завершён

- `set_commands_for_role` — `setMyCommands` по ролям через `BotCommandScopeChat` (`app/bot/commands.py`)
- Вызовы `set_commands_for_role` в `auth.py`: при `/start` (авторизованный) и после approve
- Обработчик callback `contact_dev` + FSM `waiting_dev_message` (пересылка сообщения разработчику)

---

## Этап 2 ✅ завершён

- `timeparsing.py` — парсинг всех форматов даты и времени, расчёт H, пересечение полуночи, is_weekend
- 31 тест (pytest), все зелёные

---

## Этап 3 ✅ завершён

- `shift_states.py` — ShiftStates: waiting_shift_input / waiting_ah_input / waiting_ah_comment
- `userhours.py` — полный 4-шаговый FSM для Раннера: /shift → дата+время → AH → комментарий → запись
- `google_sheets.write_shift()` — запись смены в месячный лист (ячейка H/AH)
- `main.py` — подключён userhours_router
- Фиксы auth.py: resync SQLite с Техлистом при /start, сброс команд при регистрации и resync, `delete_user()` в models.py, `user_exists_in_techlist()` в google_sheets.py

---

## Этап 4A ✅ завершён

- FSM внесения смены для Кухни, Хостесс, Менеджера (только H, мультистрочный ввод)
- Константы KITCHEN_POSITIONS, HALL_SIMPLE_POSITIONS, SIMPLE_H_POSITIONS в userhours.py
- Уведомления: Кухня → ADMIN_KITCHEN_IDS + SUPERADMIN_IDS, Зал → ADMIN_HALL_IDS + SUPERADMIN_IDS

---

## Этап 4B ✅ завершён

- FSM внесения смены для Бармена/Барбэка (H + тусовочные AH, проверка нахлёста)
- `check_overlap()` в timeparsing.py — проверка пересечения временных диапазонов с учётом перехода через полночь
- 37 тестов (pytest), все зелёные

---

## Этап 4C ✅ завершён

- FSM внесения смены для Официанта (H + опциональные фото)
- Медиагруппа: буферизация через _mg_photos/_mg_context/_mg_scheduled + asyncio.sleep(1.0)
- Отчёт для ADMIN_HALL_IDS + SUPERADMIN_IDS: медиагруппа + сообщение с inline кнопками [0]..[N]
- approve_ah_callback в auth.py: запись H+AH, редактирование сообщения, уведомление официанту
- Фикс: approve_ah_callback зарегистрирован до generic approve_ хендлера

---

## Этап 5 ✅ завершён

- `/hours_first`, `/hours_second`, `/hours_last` в userreports.py
- `get_summary_hours()` в google_sheets.py — читает S/AJ/AK, парсит H/AH
- Формулы S/AJ/AK вставляются автоматически при добавлении сотрудника в месячный лист
- Название текущего листа определяется динамически: `_get_current_sheet_name()` → "Март 2026"
- Колонки D:AN месячного листа форматируются как "Обычный текст" (предотвращает интерпретацию как даты)

---

## Этап 6 ✅ завершён

- Таблица `rates` в SQLite с дефолтными ставками для всех позиций
- Поле `position` добавлено в таблицу `users`
- `/hours_first`, `/hours_second`, `/hours_last` показывают заработок в рублях
- `/rates` — показывает ставки отдела
- `/set_rate` — FSM изменения ставки позиции
- `/rates_all` — все ставки (superadmin + developer)
- `/set_rate_all` — изменение любой ставки (superadmin + developer)
- Проверка прав superadmin/developer через config.py (не через SQLite)

---

## Вне этапов ✅ завершено

- Рефакторинг регистрации: убран отдельный флоу admin, `/start` сразу ведёт к выбору отдела
- `/promote` — повышение user до admin своего подразделения (с запросом email после повышения)
- `/demote` — понижение admin обратно в user с уведомлениями
- `/dismiss` для admin — развилка "понизить/уволить"
- Суперадмины и developer пропускают регистрацию — сразу главное меню
- Функция увольнения /dismiss (superadmin + developer): inline-флоу, подтверждение, красит ячейку A в #FFCCCC, удаляет из Техлиста и SQLite, сбрасывает FSM/кеш/команды, уведомляет сотрудника
- Новые позиции: Грузчик/Закупщик (отдел «Доп.» / Кухня), Клининг/Котломой (отдел МОП / подчинение Залу)
- `custom_title` для Шеф/Су-шеф (вводится вручную) и для Доп. позиций (Грузчик/Закупщик)
- Кликабельные ники во всех уведомлениях (`make_mention` → HTML-ссылка на профиль)
- `LinkPreviewOptions(is_disabled=True)` во всех HTML-сообщениях с упоминаниями (userhours, auth, superadmin)
- Защита от двойного нажатия «Одобрить»/«Отклонить»: проверка ✅/❌ в тексте + имя обработавшего администратора
- `/sheet` — команда для всех ролей, отправляет ссылку на Google Sheets график
- Динамический пример тусовочных часов для Бармена/Барбэка в подсказке `/shift`
- Валидация email только `@gmail.com` при регистрации администратора (`_is_valid_gmail()`)
- Удаление сообщения «⏳ Генерирую график» после отправки PDF (`wait_msg.delete()`)

---

## Этап 7 ✅ завершён

- `/message_dept` — рассылка по отделу (admin_* + superadmin/developer)
- `/message_all` — рассылка всем (superadmin/developer)
- Заголовок рассылки зависит от роли отправителя
- `get_users_by_department()` и `get_all_users()` в models.py

---

## Этап 8 ✅ завершён

- `PDFService` — экспорт через Google Sheets export API, альбомный A4
- `/schedule` — отправляет PDF файл в Telegram:
  - superadmin/developer → весь лист целиком
  - user/admin_* → только блок своего отдела (КУХНЯ/БАР/ЗАЛ)
- `get_section_range()` — поиск диапазона блока отдела, регистронезависимый
- `get_sheet_id_by_name()` — получение gid листа по названию

---

## Этап 9 ✅ завершён

- `switch_month()` — копирует текущий лист, очищает смены, переносит активных сотрудников
- Красные строки (уволенные) не переносятся — двойная проверка: цвет + Техлист
- Следующий месяц определяется по последнему существующему листу
- Новый лист вставляется в конец (правее всех)
- APScheduler: уведомление в 12:00 + переключение в 18:00 (1-е число, МСК)
- `/switch_month` — ручное переключение с подтверждением (superadmin/developer)
- Email в заявке администратора + ссылка на таблицу при апруве
- Авторизация admin_hall/bar/kitchen не требует Техлиста

---

## Этап 10 ✅ завершён

- Таблицы `user_rates` + `user_rates_history` в SQLite
- Миграция существующих данных (`migrate_user_rates_once.py`)
- При апруве нового сотрудника ставка копируется из `rates` в `user_rates` (auth.py)
- `/rates` и `/set_rate` переделаны на персональные ставки (admin.py)
- `/rates_all` и `/set_rate_all` переделаны на персональные ставки (superadmin.py)
- `/hours_first`, `/hours_second`, `/hours_last` считают зарплату через `user_rates`
- Снимок `user_rates_history` делается при `switch_month()` (monthly_switch.py)
- FSM ввода ставки разбит на два шага для позиций с повышенной ставкой (Раннер/Бармен/Барбэк)

---

## Этап 10+ ✅ расширение (персонализация ставок)

**Контекст:** В Этапе 10 ставки были персонализированы (таблица `user_rates`), но UI был базовым. Этап 10+ улучшил UX и добавил детали.

**Что сделано:**
- `/rates` — умная группировка по позициям:
  - Если у всех одинаковые ставки → схлопывание: "Официанты (3 чел.): 250 р/ч"
  - Если отличаются → раскрытие: "Иван (Официант): 270 р/ч"
- `/rates_all` — показывает ФИО в формате "ФИО (Позиция): ставка"
- `/set_rate` — двухшаговый ввод для позиций с повышенной ставкой:
  - Шаг 1: ввод базовой ставки
  - Шаг 2: ввод повышенной ставки (только для Раннер/Бармен/Барбэк)
- `/set_rate_all` — аналогично, с выбором отдела перед позицией
- Валидация на каждом шаге без сброса FSM при ошибке

---

## Audit Phase 1 ✅ завершена (10 багов)

**Дата:** 2026-04-05
**Ветка:** `fix/post-audit-clean`

### 5 критичных (из FINAL_AUDIT.md)

1. **_pending_custom_titles → _pending_admins**
   - Глобальный `_pending_custom_titles: dict[int, str]` удалён
   - Валидация custom_title: 2-50 символов в `process_kitchen_title` (FSM)
   - `custom_title` сохраняется в `_pending_admins[callback_key]` вместе с tg_id/row_index/full_name
   - `process_approve` читает `custom_title` из `_pending_admins` по callback_key
   - Файл: `auth.py` | Коммит: `a05074b`

2. **/message_dept + МОП**
   - admin_hall теперь выбирает отдел (Зал или МОП) перед вводом текста рассылки
   - Добавлена `_hall_dept_keyboard()` с кнопками Зал/МОП/Отмена
   - `cmd_message_dept`: проверка `admin_hall` до `_ROLE_TO_DEPT`, переходит в `waiting_broadcast_dept`
   - Файл: `admin.py` | Коммит: `013b5c3`

3. **Инъекция формул Google Sheets**
   - `value_input_option="USER_ENTERED"` → `"RAW"` для пользовательских данных
   - Защита от `=HYPERLINK()`, `=IMPORTXML()` и других формул через `custom_title`/ФИО
   - `google_sheets.py:526` (`=SUMPRODUCT`, `=S+AJ`) намеренно оставлена с `USER_ENTERED` — hardcoded формулы
   - Файлы: `google_sheets.py`, `auth.py` | Коммит: `67197ae`

4. **HTML-инъекция через user inputs в HTML-сообщениях**
   - Создан `app/utils/text_utils.py`: `make_mention()` с `html.escape(full_name)` + `mask_email()`
   - `html.escape()` применён к: `comment` Раннера, `text` в contact_dev, `full_name` в approve/reject
   - Файлы: `userhours.py`, `auth.py`, `app/utils/text_utils.py` (новый) | Коммиты: `5adcb11`, `c0ac67b`

5. **_delayed_process_waiter без try/except**
   - Тело функции обёрнуто в `try/except Exception`
   - `await state.clear()` при ошибке; очистка `_mg_photos`/`_mg_context`/`_mg_scheduled`
   - Логирование через `error_logger.exception()` (включает traceback)
   - Файл: `userhours.py` | Коммит: `9da295c`

### 5 дополнительных (из тестирования)

6. **Переименование "Шеф/Су-шеф" → "Руководящий состав"**
   - Legacy-названия `"Шеф/Су-шеф"` (UI) и `"Су-шеф"` (внутреннее) заменены во всём коде
   - Затронуто 7 файлов + SQL: `UPDATE rates SET position = 'Руководящий состав' WHERE position = 'Су-шеф'`
   - Константа `LEADERSHIP_POSITION = "Руководящий состав"` добавлена в `config.py`
   - Файлы: `auth.py`, `admin.py`, `superadmin.py`, `userhours.py`, `google_sheets.py`, `monthly_switch.py`, `common.py` | Коммит: `a04a29e`

7. **custom_title записывается в Техлист колонку E**
   - Для `"Руководящий состав"` в E Техлиста теперь идёт `custom_title` (напр. "Бренд-шеф"), а не строка позиции
   - Для всех остальных позиций поведение не изменилось — в E идёт `position`
   - Файл: `auth.py` | Коммит: `0b2de69`

8. **SQLite fallback для sender_role в msg_broadcast_text**
   - `_resolve_sender_role()` при возврате `None` теперь делает fallback на SQLite
   - `ROLE_TO_SENDER` заменено на `.get(sender_role, "администрации")` — защита от KeyError
   - Файл: `admin.py` | Коммит: `a0fe075`

9. **Admins могут вносить свои смены через /shift**
   - Проверка роли в `cmd_shift` изменена: `role != "user"` → `role not in ("user", "admin_hall", "admin_bar", "admin_kitchen")`
   - Администраторы теперь могут использовать `/shift` для собственных смен
   - Файл: `userhours.py` | Коммит: в docs-коммите этой ветки

10. **Поиск секции по базовой позиции при custom_title**
    - Введена переменная `section_position`: если `custom_title` задан → `"Руководящий состав"`, иначе `position`
    - `display_position = custom_title if custom_title else position` — для записи в колонку C
    - `section_position` передаётся в `POSITION_TO_SECTION` для поиска блока
    - Файл: `google_sheets.py` | Коммит: `e1a6285`

**Все 10 багов Phase 1 закрыты. 37/37 тестов зелёных.**

---

## Audit Phase 2 ✅ завершено 11/14 багов

**Дата:** 2026-03-28  
**Ветка:** `fix/post-audit-bugs`

### Завершённые баги (11):

1. **requests в requirements.txt**
   - Добавлена зависимость для корректной работы
   - Файл: `requirements.txt`

2. **.env.example создан**
   - Шаблон для всех environment переменных
   - Файл: `.env.example` (новый)

3. **Проверка роли в approve_ah_callback**
   - Проверка `caller_id in (ADMIN_HALL_IDS + SUPERADMIN_IDS + [DEVELOPER_ID])`
   - Защита от несанкционированного одобрения
   - Файл: `auth.py:478`

4. **Проверка роли в process_approve/reject**
   - Аналогичная проверка для основных approve callbacks
   - Файл: `auth.py:579`

5. **Email маскировка в логах**
   - Функция `mask_email()` в `app/utils/text_utils.py`
   - Применена везде где логируется email
   - Формат: `p***r@gmail.com`

6. **make_mention() дублировалась**
   - Извлечена в общий модуль `app/utils/text_utils.py`
   - Импортируется в `auth.py` и `userhours.py`

7. **Три метода Google Sheets без retry**
   - Добавлен паттерн try/except + `_reconnect()` + повтор
   - Методы: `get_section_range`, `get_sheet_id_by_name`, `batch_update_values`
   - Файл: `google_sheets.py:244, 897, 905`

8. **Списки позиций в 5+ местах**
   - Консолидированы в 10 констант в `config.py`
   - `POSITIONS_WITH_EXTRA`, `DEPT_POSITIONS_ORDER` и т.д.
   - Импортируются в `admin.py`, `superadmin.py`, `userreports.py`

9. **Импорт приватного символа _parse_time**
   - Исправлен импорт в `userhours.py`
   - Использование публичного API

10. **Глобальный _mg_* state без asyncio.Lock**
    - Добавлен `asyncio.Lock` для защиты от race conditions
    - Файл: `userhours.py:106-110`

11. **FSM без явного выхода**
    - Добавлена кнопка "Отмена" на каждом шаге FSM
    - Таймаут для зависших состояний
    - Файлы: `userhours.py`, `admin.py`, `superadmin.py`

### Оставшиеся баги Phase 2 (3):

12. **Тесты для models.py** — не написаны
13. **Тесты для snapshot_user_rates_history** — не написаны
14. **Тесты для get_section_range/get_sheet_id_by_name** — не написаны

---

## Audit Phase 2 (продолжение) — ветка fix/phase-2-audit

**Дата:** 2026-04-05
**Ветка:** `fix/phase-2-audit`

### Завершённые баги:

- **Bug #9: Email маскировка в логах через mask_email()**
  - `process_promote_email` логировал email в plaintext (`auth.py:873`)
  - Добавлен импорт `mask_email` из `app/utils/text_utils`
  - Email теперь маскируется: формат `p***r@gmail.com`
  - Файл: `auth.py:30, 873`

- **Bug #14: Добавлен requests>=2.31.0 в requirements.txt**
  - `app/services/pdfservice.py` использует `import requests`, но пакет отсутствовал в `requirements.txt`
  - Добавлена строка `requests>=2.31.0` (после `python-dotenv`)

- **Bug #15: Создан .env.example с шаблоном переменных окружения**
  - Отсутствовал шаблон для деплоя — новый пользователь не знал какие переменные нужны
  - Создан `.env.example` в корне проекта со всеми переменными и комментариями
  - Реальные значения заменены на плейсхолдеры, файл добавляется в git (не в .gitignore)

- **Bug #19: Удалён Pillow из requirements.txt (не используется)**
  - `Pillow==10.4.0` присутствовал в `requirements.txt`, но нигде не импортируется (`from PIL` / `import PIL` — 0 совпадений по всему коду)
  - Удалена строка `Pillow==10.4.0` из `requirements.txt`
  - Уменьшен размер образа и время установки зависимостей

- **Bug #10: Добавлен retry-паттерн в 3 метода Google Sheets API**
  - Методы выполняли прямые сетевые вызовы без try/except и `_reconnect()`
  - `mark_user_approved`: обёрнут `ws.update_cell()` в try/except + reconnect
  - `get_sheet_id_by_name`: обёрнут `self._spreadsheet.worksheets()` в try/except + reconnect
  - `get_section_range`: обёрнуты `worksheet()` + `get_all_values()` в try/except + reconnect
  - Паттерн: `logger.warning(...) → self._reconnect() → повторный вызов`

- **Bug #12: _parse_time переименована в parse_time (публичный API)**
  - `app/services/timeparsing.py`: `def _parse_time` → `def parse_time` + внутренний вызов обновлён
  - `app/bot/handlers/userhours.py`: импорт + вызов обновлены на `parse_time`
  - Обновлено 2 файла, 4 вхождения

- **Bug #17: Добавлены 4 теста для snapshot_user_rates_history()**
  - Файл: `tests/test_snapshot_user_rates.py`
  - `test_snapshot_basic` — базовый снимок: 3 записи из user_rates → user_rates_history
  - `test_snapshot_idempotency` — повторный вызов не дублирует строки (INSERT OR IGNORE)
  - `test_snapshot_different_months` — снимки за март и апрель хранятся независимо
  - `test_snapshot_empty_user_rates` — пустая user_rates не вызывает ошибок
  - Итого тестов: было 37, стало 41

- **Bug #18: Добавлены 6 тестов для Google Sheets методов (get_section_range, get_sheet_id_by_name)**
  - Файл: `tests/test_google_sheets_methods.py`
  - `test_get_section_range_found` — заголовок отдела найден, диапазон начинается с правильной строки
  - `test_get_section_range_not_found` — отдел отсутствует → None
  - `test_get_section_range_multiple_sections` — два отдела: возвращает блок нужного отдела корректно
  - `test_get_sheet_id_found` — лист найден → возвращает id=123456
  - `test_get_sheet_id_not_found` — листа нет → None
  - `test_get_sheet_id_empty_list` — пустой список листов → None без исключения
  - Мокирование через `unittest.mock.MagicMock`, реальных запросов нет
  - Итого тестов: было 41, стало 47

- **Bug #16: Добавлены 8 тестов для user_rates CRUD операций (get/set/history)**
  - Файл: `tests/test_models_user_rates.py`
  - `test_get_user_rate_found` — ставка найдена → словарь с base_rate
  - `test_get_user_rate_not_found` — запись отсутствует → None
  - `test_get_user_rate_with_extra` — Раннер с extra_rate → оба поля корректны
  - `test_set_user_rate_create` — новая запись создаётся с правильными данными
  - `test_set_user_rate_update` — обновление ставки, запись не дублируется
  - `test_set_user_rate_no_extra` — extra_rate=None сохраняется как NULL в БД
  - `test_get_user_rate_history_found` — снимок за март 2026 найден
  - `test_get_user_rate_history_not_found` — снимок отсутствует → None
  - Итого тестов: было 47, стало 55

- **HOTFIX #2: Аудит value_input_option — второго места для Бармена не найдено (явный RAW для 2 вызовов)**
  - Проведён полный аудит всех update-вызовов в `google_sheets.py` и `monthly_switch.py`
  - Вывод: отдельного кода вставки формул для Бармена НЕТ — все позиции (включая Бармена) проходят через строку 545, исправленную в HOTFIX #1
  - Исправлено: строка 169 `ws.batch_update([...])` — добавлен явный `value_input_option="RAW"` (данные техлиста: ник, ФИО, отдел, позиция)
  - Исправлено: строка 193 `ws.update(...)` — добавлен явный `value_input_option="RAW"` (новая заявка в техлист)
  - Эти два вызова полагались на gspread default ('RAW'), теперь intent явный в коде
  - Итог: 4 update-вызова с данными пользователя — все явно RAW; 2 batch_update с формулами — оба USER_ENTERED ✅

- **HOTFIX: Исправлена запись формул S/AJ/AK при добавлении сотрудника (RAW для данных, USER_ENTERED для формул)**
  - Файл: `app/services/google_sheets.py`, строка 545
  - Причина: Phase 1 Bug #1 заменил `"USER_ENTERED"` → `"RAW"` глобально, включая `batch_update` формул
  - Следствие: `=SUMPRODUCT(...)` записывался как текст `'=SUMPRODUCT(...)` — суммирование не работало
  - Фикс: только `batch_update` с формулами S/AJ/AK/AL → `"USER_ENTERED"`
  - `insert_row` (данные ФИО/TG_ID/позиция) и `ws.update` (часы смены) — `"RAW"` оставлен ✅
  - Итог: user data injection защищена, системные формулы работают

- **Bug #11 Этап 2: Добавлена команда /cancel для выхода из FSM внесения смены**
  - Файл: `app/bot/handlers/userhours.py`
  - Handler `cmd_cancel` зарегистрирован перед `process_shift_input` (порядок критичен)
  - Работает из любого состояния: `waiting_shift_input`, `waiting_ah_input`, `waiting_ah_comment`
  - Edge case Официант: поиск mgid по `user_id` в `_mg_context` → флаг `ctx["cancelled"] = True`
  - `_delayed_process_waiter`: проверяет `ctx.get("cancelled")` перед записью → ранний выход
  - При `current_state is None` — сообщение «нет активных действий» без лишнего `state.clear()`
  - Обновлён `docs/FSM_STATES_MAP.md`: добавлена секция «Exit via /cancel»

- **Bug #11 Этап 1: Reconnaissance — составлена карта FSM состояний (3 states, 4 entry flows)**
  - Файл: `docs/FSM_STATES_MAP.md` (создан, папка docs/ создана)
  - Ветка: `fix/phase-2-bug11-fsm-cancel`
  - ShiftStates: `waiting_shift_input`, `waiting_ah_input`, `waiting_ah_comment`
  - 4 flow: Раннер (3 states), Официант (1 state), Бармен/Барбэк (2 states), Simple-H (1 state)
  - 7 вызовов `state.set_state()`, 16 вызовов `state.clear()` в 7 функциях
  - Все 3 состояния покрыты handlers ✅
  - Обнаружено: при отмене из Официант-потока нужна инвалидация `_mg_context[mgid]`

- **Bug #13: Добавлен asyncio.Lock per mgid для защиты глобального _mg_* state**
  - Файл: `app/bot/handlers/userhours.py`
  - Добавлена `_mg_locks: dict[str, asyncio.Lock] = {}` рядом с остальными `_mg_*` буферами
  - `_process_waiter_shift_input`: весь блок записи в `_mg_photos`/`_mg_context`/`_mg_scheduled` обёрнут в `async with lock`
  - `_delayed_process_waiter`: секция чтения + pop данных обёрнута в `async with lock`; в блоке except — тоже защита через lock; при очистке данных lock удаляется из `_mg_locks`
  - Lock создаётся через `setdefault()` при первом обращении, удаляется после pop данных
  - Sleep (1 сек накопления фото) остаётся вне lock — параллельная доставка фото не блокируется
  - Обновлено 2 функции

---

## Этап 12: Docker деплой (PR #55, 2026-04-05)

**Ветка:** `deploy/docker-setup`
**Тесты:** 55/55 ✅

- `Dockerfile` — multi-stage build (builder + runtime, минимальный образ)
- `docker-compose.yml` — сервис bot + volume для SQLite (`data/`)
- `.dockerignore` — исключены credentials, .env, __pycache__, .venv, документация
- `DB_PATH = "data/bot.db"` — SQLite в Docker volume (переживает перезапуск контейнера)
- `GOOGLE_CREDENTIALS_PATH` — поддержка относительных путей (авто-конвертация в абсолютный от корня)
- `docs/DEPLOYMENT.md` — гайд по деплою на VPS

**Хотфиксы при деплое:**
- Hotfix Bug #6 — замена legacy `"Су-шеф"` → `"Руководящий состав"` в auth.py (коммит `218385e`)
- Fix Bug #10 — `pending_custom_title` передаётся в `ensure_user_in_current_month_hours` (коммит `34f0d13`)
- Fix `/shift` — position читается из SQLite, а не из Техлиста (коммит `e6a163c`)
- Fix SQLite locked — добавлен timeout и WAL mode в `aiosqlite.connect()` (коммит `1f3a1df`)

---

## Этап 13: Рефакторинг custom_title → custom_position + колонка H (PR #56, 2026-04-10)

**Ветка:** `refactor/clean-custom-position`
**Тесты:** 55/55 ✅

### Часть 1 — Переименование + новая колонка H Техлиста

- Добавлен `COL_CUSTOM_POSITION = 8  # H — Должность` в `google_sheets.py`
- `get_user_by_telegram_id` — возвращает `"custom_position"` из колонки H (`row[7]`)
- `add_or_update_pending_user` — новый параметр `custom_position`, пишет в H
  - Новые строки: диапазон `A:H` (был `A:F`)
  - Обновление существующих: `batch_update` включает `H{row_idx}`
- `ensure_user_in_current_month_hours` — `custom_title` → `custom_position` в сигнатуре
- `auth.py` — все вхождения `custom_title` → `custom_position`

### Часть 2 — Разделение position и custom_position

- Убран хак `position_for_sheet`: раньше для Руководящего состава в E Техлиста писался `custom_title`
- Теперь: E = всегда базовая позиция ("Руководящий состав"), H = `custom_position` ("Шеф ЗЦ")

### Часть 3 — Линейный approve flow

- Удалён reverse mapping (`_CANONICAL_POSITIONS`, `_KNOWN_POSITIONS`, `normalized_position`)
- Удалена FSM-ветка в `process_approve` — ранее при отсутствии custom_title предлагалось ввести повторно
- `position` и `custom_position` читаются напрямую из E и H Техлиста
- `process_approve`: ~120 строк → ~55 строк, один путь для всех позиций

### Часть 4 — Фиксы, выявленные при рефакторинге

- `fix(auth)`: не запрашивать custom_title повторно при approve (коммит `4397a24`)
- `fix(auth)`: reverse mapping Техлиста E для SQLite позиции (коммит `e1ec506`)
- `fix(auth)`: canonical position из `pending_data`, не из Техлиста (коммит `dcba6ec`)
- `refactor(auth)`: убран reverse mapping, линейный approve flow (коммит `1c18c6b`)

---

## Этап 14: Phase 3 — Улучшения (PR #57, 2026-04-10)

**Ветка:** `fix/phase-3-improvements`
**Тесты:** 56/56 ✅ (+1 тест)

- **fix(userhours):** cleanup буферов `_mg_photos`/`_mg_context`/`_mg_scheduled` при пустом `photo_ids`
  - Официант присылал фото без капшена → `photo_ids` оставался в памяти → утечка
- **fix(admin):** убран `full_name` из логов ставок (`/set_rate`, `/set_rate_all`) — PII protection
  - Только `telegram_id` остаётся в логе
- **test(timeparsing):** добавлен тест mixed midnight case для `check_overlap`
  - Сценарий: смена 23:00–01:00 пересекается со сменой 00:30–02:00

---

## Этап 15: Phase 4 — Декомпозиция монолитов auth.py (2026-04-10, в процессе)

**Ветка:** `refactor/phase-4-monoliths`
**Тесты:** 56/56 ✅

### Декомпозиция `process_approve` (6 шагов)

Исходная функция: ~200+ строк, 6 отвечала за всё сразу.  
После рефакторинга: оркестратор + 5 приватных функций.

| Шаг | Функция | Ответственность |
|-----|---------|-----------------|
| 1 | `_parse_approve_callback(callback_data)` | Парсинг callback_data → `(admin_tg_id, user_tg_id) \| None` |
| 2 | `_fetch_user_info(sheets_client, user_tg_id)` | Читает данные из Техлиста → dict \| None |
| 3 | `_register_user_in_sheets(...)` | Регистрация в месячном листе + approve в Техлисте |
| 4 | `_setup_user_access(...)` | SQLite + кеш ролей + команды + уведомление пользователю |
| 5 | `_notify_approval(...)` | Уведомление администратору |
| 6 | `process_approve` | Оркестратор — вызывает 1–5 последовательно |

### Hotfix из той же ветки

- **fix(dismiss)** (коммит `49248ee`) — admins видны в списке сотрудников при увольнении
  - Баг: в `dismiss_dept_selected` стоял фильтр `role == 'user'`, из-за чего admin_kitchen и другие admins не показывались
  - Фикс: убран фильтр по роли в ветке "Сотрудник"; admin-специфичный fork (demote/fire) уже обрабатывается в `dismiss_select`

---

## Ключевые изменения терминологии

**До (Phase 1):**
- Путаница между "отдел", "позиция", "должность"
- "Шеф/Су-шеф" как позиция
- `custom_title` — хранился только в Техлисте E (вместо позиции)

**После (Phase 1–Phase 4):**
- **Отдел** (department) = Зал/Бар/Кухня/МОП
- **Позиция** (position) = Официант/Раннер/Бармен (всегда каноническая, в E)
- **Должность** (custom_position, ранее `custom_title`) = "Шеф ЗЦ", "Бренд-шеф" (только для РС и Грузчик/Закупщик, в H)
- "Шеф/Су-шеф" → "Руководящий состав" в коде

---

## Новые файлы и модули

- `app/utils/text_utils.py` — `make_mention()`, `mask_email()`
- `migrate_user_rates_once.py` — одноразовая миграция (оставлен как документация)
- `.env.example` — шаблон environment переменных
- `docs/FINAL_AUDIT.md` — живой roadmap багов
- `docs/DEPLOYMENT.md` — гайд по деплою на VPS
- `docs/FSM_STATES_MAP.md` — карта FSM состояний (Bug #11)
- `HISTORY.md` — этот файл (**НИКОГДА НЕ УДАЛЯТЬ**)
- `TECH_REFERENCE.md` — технические детали (**НИКОГДА НЕ УДАЛЯТЬ**)

---

## Этап 13: Phase 4.1 — Рефакторинг process_approve() ✅ завершён

**Дата:** 2026-04-10
**Ветка:** `refactor/phase-4-monoliths` → `main` (PR #58)
**Статус:** 1/3 монолитов декомпозирован

### Декомпозиция process_approve():

**Было:** 109 строк монолит с 7 ответственностями
**Стало:** 71 строка оркестратор + 5 вспомогательных функций

**Добавленные функции:**
1. `_parse_approve_callback()` (строки 589–607) — парсинг callback_data
2. `_fetch_user_info()` (строки 610–639) — получение данных из Техлиста
3. `_register_user_in_sheets()` (строки 642–678) — одобрение + добавление в график
4. `_setup_user_access()` (строки 681–724) — ставка + кеш + команды меню
5. `_notify_approval()` (строки 727–766) — уведомления пользователю и админу

**Результат:**
- Улучшена читаемость кода
- Каждая функция отвечает за одну задачу
- Функции можно тестировать изолированно
- Транзакционная логика явно задокументирована (risk в docstring)

**Коммиты (9 шт):**
- `bd1b3f6` — step 1/6: `_parse_approve_callback`
- `39a4e3f` — step 2/6: `_fetch_user_info`
- `ad393a7` — step 3/6: `_register_user_in_sheets`
- `56b2c15` — step 4/6: `_setup_user_access`
- `cb0a5db` — step 5/6: `_notify_approval`
- `3259c4d` — step 6/6: финальная проверка
- `49248ee` — fix: dismiss показывает админов в списке сотрудников
- `c1a8f9d` — fix: custom_position маппинг и секции
- `8f2e5a1` — fix: kitchen departments display mapping

### Критичные баги исправлены:

1. **Bug dismiss** — админы отдела не показывались в списке при выборе "Сотрудник"
   - Причина: фильтр `role == "user"` отсекал админов
   - Фикс: убран жёсткий фильтр, fork demote/fire работает в dismiss_select

2. **Bug custom_position mapping** — цеха Кухни попадали в "Руководящий состав"
   - Причина: `custom_position="Повар"` захардкожен для всех позиций Кухни
   - Фикс: убран хардкод, `section_position = position` напрямую

3. **Bug kitchen display** — в месячном листе колонка C показывала "Холодный цех" вместо "Повар"
   - Фикс: добавлен `KITCHEN_DEPARTMENTS_TO_DISPLAY` маппинг

### Docker IPv6 фикс:

**Проблема:** После деплоя бот не отвечал — сервер имеет доступ к Telegram API только через IPv6, но Docker создавал изолированную IPv4-сеть.

**Фикс:** `docker-compose.yml` → `network_mode: "host"`

### Production deployment:

- **Сервер:** 5.129.215.239
- **Статус:** ✅ Работает
- **Тесты:** 56/56 ✅

### Осталось (Phase 4.2-4.3):

2. ⏸️ `ensure_user_in_current_month_hours()` — google_sheets.py (~185 строк)
3. ⏸️ `switch_month()` — monthly_switch.py (~240 строк)
- `CLAUDE.md` — контекст проекта (**НИКОГДА НЕ УДАЛЯТЬ**)

---

## Что впереди

- **Monitoring** — алерты при ошибках записи в таблицу
- **Apps Script миграция** (отложено до ревью файлов)
- **Лицензионная система** (license server + PyArmor)
- **Web-панель** для конфигурации
- **Универсализация** для сторонних клиентов

---

## Этап 14 ✅ завершён (22 апреля 2026)

**Ветка:** `main`  
**Цель:** Динамические уведомления админам + фикс формул Google Sheets

### Фикс формул S/AJ/AK (Bug #23)

**Проблема:**
- Юзеры, зарегистрированные до commit "fix: replace English formulas", имели английские формулы SUMPRODUCT
- Каримов Мухаммад (строка 11): S11 = 138480 вместо 129.5
- Google Sheets в русской локали неправильно интерпретировала английские функции

**Решение:**
- Заменены все формулы в коде: SUMPRODUCT→СУММПРОИЗВ, IF→ЕСЛИ, IFERROR→ЕСЛИОШИБКА, VALUE→ЗНАЧЕН
- Создан скрипт `fix_all_formulas_april.py` для массового обновления всех строк в листе "Апрель 2026"
- Перезаписаны формулы S/AJ/AK для всех существующих юзеров

**Файлы:** `app/services/google_sheets.py` (строки 530-552)

---

### Рефакторинг: Динамические уведомления админам (7 этапов)

**Проблема:**
- `ADMIN_HALL_IDS`, `ADMIN_BAR_IDS`, `ADMIN_KITCHEN_IDS` хранились в `.env` статично
- При `/promote` и `/demote` админы не добавлялись/удалялись из уведомлений автоматически
- Требовалась ручная правка `.env` + перезапуск бота

**Решение:**

**Этап 1-2:** Добавлены функции в `models.py`
- `get_admins_by_department(db_path, department)` — возвращает список telegram_id админов отдела из SQLite
- `get_user_role(db_path, telegram_id)` — возвращает роль юзера из SQLite

**Этап 3:** `userhours.py` — 6 мест заменены на динамическое чтение
- Официант, Раннер → `get_admins_by_department(DB_PATH, "Зал")`
- Бармен/Барбэк → `get_admins_by_department(DB_PATH, "Бар")`
- Кухня → `get_admins_by_department(DB_PATH, "Кухня")`
- МОП → `get_admins_by_department(DB_PATH, "МОП")` (маппится на admin_hall)

**Этап 4:** `roles.py` (middleware)
- Определение роли через `get_user_role()` вместо проверки `user_id in ADMIN_*_IDS`

**Этап 5:** `auth.py`
- Уведомления при регистрации через `get_admins_by_department()`
- Удалены 3 `logger.debug` для устаревших констант

**Этап 6:** `admin.py`
- `_resolve_sender_role()` стала async
- Проверка роли через `get_user_role()` вместо `if tg_id in ADMIN_*_IDS`

**Этап 7:** Удалены из `config.py` и `.env.example`
- `ADMIN_HALL_IDS`, `ADMIN_BAR_IDS`, `ADMIN_KITCHEN_IDS` полностью удалены
- Оставлены только `SUPERADMIN_IDS` и `DEVELOPER_ID` (статичны)

**Результат:**
- ✅ `/promote` юзера → сразу начинает получать уведомления
- ✅ `/demote` админа → сразу перестаёт получать уведомления
- ✅ Никакой ручной правки `.env` и перезапусков
- ✅ Один источник правды — SQLite для ролей

**Затронуто файлов:** 6 (models.py, userhours.py, roles.py, auth.py, admin.py, config.py)  
**Тесты:** 56/56 ✅

---

### Деплой + хотфиксы

- IPv6 connector hotfix откачен (ломал `AiohttpSession.__init__`)
- Docker DNS починен (добавлен Google DNS 8.8.8.8 в `/etc/docker/daemon.json`)
- Production сервер переведён на git clone вместо ручного копирования файлов
- Все данные сохранены (SQLite `data/bot.db`, `credentials.json`, `.env`)
- Старые админы автоматически работают с новой системой (роли в SQLite)

**Статус:** ✅ Production deployed, бот работает стабильно

---

## Stage 15 ✅ завершён — Рефакторинг системы ставок

**Дата:** 2026-04-26 – 2026-04-29
**Ветка:** `main` (14 коммитов)
**Тесты:** 55 → 73 (+18 новых тестов)

### Цель этапа:
Упростить систему ставок — убрать концепцию "шаблонов по позициям", оставить только персональные ставки для каждого сотрудника.

### Что сделано:

#### 1. Удалена таблица `rates` (шаблоны)
- Таблица `rates` (позиция → ставка) полностью удалена из кода
- При апруве нового сотрудника ставка **НЕ копируется** автоматически
- Администратор устанавливает ставку вручную через `/set_rate`

#### 2. Команды изменены:
- **`/set_rate`** — выбор отдела → позиция → сотрудник → ставка
- **`/set_rate_all`** — удалена (больше не нужна)
- **`/rates`** — показывает персональные ставки сотрудников отдела
- **`/rates_all`** — удалена (дублировала функционал)

#### 3. Таблица `user_rates_future` (новая)
```sql
CREATE TABLE user_rates_future (
    telegram_id INTEGER PRIMARY KEY,
    base_rate   REAL NOT NULL,
    extra_rate  REAL,
    effective_date TEXT NOT NULL  -- дата применения (YYYY-MM-DD)
)
```
- Позволяет планировать изменение ставки "со следующего месяца"
- Применяется автоматически при `switch_month()` через `apply_future_rates()`

#### 4. Фикс `delete_user()` — удаление ставок при увольнении
**Проблема:** При увольнении сотрудника записи в `user_rates`, `user_rates_future` и `user_rates_history` оставались в БД. При повторной регистрации того же `telegram_id` старая ставка "воскресала".

**Решение:** Добавлены три `DELETE` в `models.py:delete_user()`:
```python
cursor.execute('DELETE FROM user_rates_history WHERE telegram_id = ?', (telegram_id,))
cursor.execute('DELETE FROM user_rates_future WHERE telegram_id = ?', (telegram_id,))
cursor.execute('DELETE FROM user_rates WHERE telegram_id = ?', (telegram_id,))
cursor.execute('DELETE FROM users WHERE telegram_id = ?', (telegram_id,))
```

#### 5. Тесты (+18 новых)
- `test_set_rate_flow.py` — FSM установки ставки (8 тестов)
- `test_user_rates_future.py` — планирование будущих ставок (6 тестов)
- `test_apply_future_rates.py` — применение при switch_month (4 теста)
- Итого: 73/73 passing ✅

### Production деплой:

**Дата деплоя:** 2026-04-26
**Сервер:** `root@5.129.215.239:/opt/horecatime`

#### Проблемы при деплое:
1. **Telegram API timeout** — ISP блокировал IP `149.154.166.110`
   - Решение: `/etc/hosts` override на альтернативный IP `149.154.167.220`
2. **Старые таблицы `rates` и `rates_history` остались в SQLite**
   - Решение: удалены вручную `DROP TABLE rates; DROP TABLE rates_history;`
3. **Ставки не удалялись при увольнении**
   - Решение: фикс `delete_user()`, задеплоен hotfix

#### Упрощение `deploy.sh`:
Убрана логика коммитов и проверок — теперь скрипт только:
1. SSH на сервер
2. `git pull origin main`
3. `docker-compose down`
4. `docker-compose build --no-cache`
5. `docker-compose up -d --force-recreate`

### Технические детали:

**SQLite таблицы (актуальные):**
- `users` — основная таблица сотрудников
- `user_rates` — персональные ставки
- `user_rates_future` — запланированные изменения
- `user_rates_history` — снимки для `/hours_last`
- `fsm_storage` — FSM состояния

**Удалены:**
- ❌ `rates` (шаблоны по позициям)
- ❌ `rates_history` (снимки шаблонов)

### Известные баги (на момент завершения этапа):
1. ⚠️ `/hours_first` показывает зарплату даже если ставка не установлена — нужно добавить проверку
2. ⚠️ `/set_rate_all` остался в меню команд Telegram — нужна чистка через BotFather

---

## Stage 15+ ✅ завершён (2026-05-01)

**Ветка:** main
**Коммиты:** 3c52d9a, d6a7ce2, d1d15c2
**Тесты:** 73/73 ✅

### Критичные фиксы:

1. **LEFT JOIN в get_users_rates_by_department (d6a7ce2)**
   - INNER JOIN исключал сотрудников без ставок → невозможно назначить ставку новому сотруднику
   - Фикс: JOIN → LEFT JOIN
   - Теперь все новые сотрудники видны в `/set_rate` автоматически
   - `app/db/models.py` в `.gitignore` → требует `git add -f` при изменении

2. **Список команд обновлён (3c52d9a)**
   - Удалена `/set_rate_all` из superadmin (handler не существует)
   - Добавлена `/set_rate` в superadmin (работает для всех ролей)
   - Все команды упорядочены по приоритету использования
   - Упрощена структура: `_ADMIN_COMMANDS` теперь самостоятельный список

3. **Фикс delete_user() — удаление ставок при увольнении (d1d15c2)**
   - Ставки не удалялись при увольнении сотрудника
   - Фикс уже был в Stage 15, но коммит d1d15c2 закрепляет это поведение

4. **Production deployment**
   - Все изменения задеплоены на 5.129.215.239
   - Бот работает стабильно
   - Проблема с рассинхроном SQLite/Sheets решена

### Известные баги (pending):
- ⚠️ Менеджер не уведомляет суперадмина о записи смен
- ⚠️ Двойное нажатие "Одобрить" → ошибка "message is not modified"

---

## fix/manual-user-recovery ✅ завершён (2026-05-03)

**Ветка:** `fix/manual-user-recovery`  
**Тесты:** 73/73 passing

### Изменения:

1. **Команда `/restore_user` — ручное восстановление юзера в месячном листе**
   - Проблема: если суперадмин вручную удалил строку юзера из месячного листа, юзер не может записать смену (`ValueError: пользователь не найден`)
   - Решение: команда для superadmin/developer — ввести Telegram ID → юзер восстанавливается через `ensure_user_in_current_month_hours()`
   - Файлы: `app/bot/handlers/superadmin.py`, `app/bot/fsm/auth_states.py`, `app/bot/commands.py`

2. **Новый FSM state `waiting_restore_user`**
   - Добавлен в `AuthStates` (`app/bot/fsm/auth_states.py`)
   - 2-шаговый flow: команда → ввод telegram_id → восстановление → `state.clear()`

3. **Валидация и обработка ошибок**
   - Невалидный input (не число) → повторный запрос без сброса состояния
   - Юзер не найден в Техлисте → `❌` сообщение + `state.clear()`
   - Ошибка Sheets → `⚠️` сообщение + логирование + `state.clear()`

4. **Логирование с префиксом `MANUAL_RESTORE`**
   - `logger.info("MANUAL_RESTORE: User %s restored by admin %s", ...)`
   - Исключения логируются через `logger.exception()`

---

## fix/formulas-switch-month ✅ завершён

**Дата:** 2026-05-03
**Ветка:** `fix/formulas-switch-month`

### Проблема

Коммит Stage 14 (973d44b) исправил формулы S/AJ/AK в `google_sheets.py`, но не затронул `monthly_switch.py`. Функция `_make_formulas()` продолжала генерировать английские формулы (`SUMPRODUCT`, `IF`, `VALUE`, etc.). При каждом запуске `switch_month()` (1-е число месяца, 18:00) формулы перезаписывались в английском варианте → `#NAME?` в Google Sheets с русской локалью.

Дополнительно: в ветке `_SIMPLE_H_POSITIONS` отсутствовал `ПОДСТАВИТЬ(".";"," )` — защита от интерпретации "12.5" как даты.

### Исправление

- `app/scheduler/monthly_switch.py` — функция `_make_formulas()` (строки 77–109)
- Все английские функции заменены на русские: `SUMPRODUCT→СУММПРОИЗВ`, `IF→ЕСЛИ`, `IFERROR→ЕСЛИОШИБКА`, `VALUE→ЗНАЧЕН`, `ISNUMBER→ЕЧИСЛО`, `FIND→НАЙТИ`, `LEFT→ЛЕВСИМВ`, `MID→ПСТР`
- Добавлен `ПОДСТАВИТЬ(...;".";"," )` в обе ветки формул S и AJ
- Логика приведена в точное соответствие с эталоном из `google_sheets.py:532–561`

---

## На горизонте

### Ближайшие задачи:
- Фикс проверки ставки в `/hours_*` (добавить сообщение "Ставка не установлена")
- Cleanup команд через BotFather
- Тестирование `apply_future_rates()` при реальном `switch_month()`
- Phase 3 улучшений из FINAL_AUDIT.md

### Долгосрочные планы:
- Лицензионная система (license server + PyArmor)
- Web-панель для конфигурации
- Модель подписки
- Универсализация для сторонних клиентов

---

## Emergency May 2026 Fixes ✅ завершено (2026-05-04)

**Дата:** 2026-05-04
**Проблема:** После переключения на "Май 2026" формулы S/AJ/AK показывали serial numbers вместо часов (46150/0 вместо 8.5)
**Тесты:** 73 → 77 (+4)

### Корневые причины (4 проблемы):

1. **Telegram ID рассинхрон** — админ вручную переставил строки в Sheets UI, колонка B (telegram_id) не двигалась
   - Следствие: write_shift() писал в чужие строки
   - Решение: скрипт `fix_telegram_ids.py` — читает Техлист как source of truth

2. **English формулы при switch_month()** — `monthly_switch.py` использовал SUMPRODUCT вместо СУММПРОИЗВ
   - Следствие: `#NAME?` ошибки в русской локали
   - Решение: замена всех функций на русские (коммит 973d44b Stage 14)

3. **Формат ячеек "Automatic"** — Google Sheets интерпретировал "8.5" как дату 08.05.2026
   - Следствие: формулы считали serial number 46150 вместо 8.5
   - Решение: Plain text формат для D-AK

4. **Неправильный тип формулы** — Повара получали сложную формулу (со "/" логикой) вместо простой
   - Следствие: парсинг несуществующих "/" в данных
   - Решение: скрипт `fix_kitchen_formulas_now.py`

---

### Исправления:

#### Фикс текущего "Май 2026":
- `fix_telegram_ids.py` — исправил 1 критичный рассинхрон (строка 17 Синько)
- `fix_current_formulas.py` — обновил 73 ячейки на русские формулы
- `fix_kitchen_formulas_now.py` — исправил формулы для строк 6-33 (Кухня)

#### Защита на будущее:
- `monthly_switch.py` — добавлена установка Plain text для D-AK при создании нового месяца (коммит acbd47a)
- `google_sheets.py` — Plain text для новой строки при добавлении сотрудника (уже был, коммит 973d44b)
- `/restore_user` команда — ручное восстановление юзера в текущем месяце

#### Тесты (4 новых):
- `test_switch_month_sets_plain_text_format` — проверка форматирования при переключении месяца
- `test_ensure_user_sets_plain_text_for_new_row` — проверка форматирования при добавлении юзера
- `test_kitchen_positions_use_simple_formula` — все 12 позиций Кухни используют простые формулы
- `test_hall_bar_positions_use_complex_formula` — Официант/Раннер/Бармен/Барбэк используют сложные формулы

---

### Скрипты созданы (инструментарий):

| Скрипт | Назначение |
|--------|-----------|
| `fix_telegram_ids.py` | Исправление telegram_id рассинхрона между Техлистом и месячным листом |
| `fix_current_formulas.py` | Обновление формул S/AJ/AK на русские с правильным типом (простая/сложная) |
| `fix_kitchen_formulas_now.py` | Массовое исправление формул для секции Кухня (строки 6-33) |
| `fix_date_cells.py` | Конвертация serial numbers в часы (не понадобился) |
| `set_plain_text_format.py` | Установка Plain text формата для D-AK (заменён на код в switch_month) |
| `fix_formula_types.py` | Проверка соответствия типа формулы позиции из Техлиста |

---

### Файлы изменены:

- `app/scheduler/monthly_switch.py` — добавлено форматирование D-AK при создании месяца
- `app/bot/handlers/superadmin.py` — добавлена команда `/restore_user`
- `app/bot/handlers/auth_states.py` — добавлено FSM состояние `waiting_restore_user`
- `app/bot/commands.py` — `/restore_user` в список superadmin команд
- `tests/test_plain_text_formatting.py` — 4 новых теста
- `docs/CLAUDE.md` — обновлён контекст
- `docs/HISTORY.md` — эта секция

---

### Защита от повторения:

**✅ Переключение месяца (Июнь 2026):**
- Plain text устанавливается автоматически
- Формулы вставляются на русском с правильным типом

**✅ Новый сотрудник:**
- Plain text устанавливается для новой строки
- Формула соответствует позиции

**✅ Покрыто тестами:**
- 4 новых теста проверяют форматирование и типы формул
- 77/77 passing

---

### Production деплой:

**Дата:** 2026-05-04
**PR:** #61
**Статус:** ✅ Deployed
**Сервер:** 5.129.215.239:/opt/horecatime
**Docker:** horecatime-bot Up

---

## Stage 16 ✅ завершён — Система карт лояльности и наполняемости чеков

**Дата:** 2026-05-12
**Ветка:** feature/loyalty-and-checks → main
**Тесты:** 77 → 112 (+35 новых)

### Цель этапа:
Разделить механику допчасов официантов на два независимых потока:
1. Карты лояльности (+0.5 ч × ставка офику)
2. Наполняемость чеков (накопление в фантоме для ручного распределения менеджером)

### Что сделано:

#### 1. Hotfix: AH Официанта теперь влияют на зарплату
- Исправлена формула расчёта: `earnings = (h + ah) * base`
- До этого AH показывались, но не участвовали в расчёте

#### 2. Константы и FSM states
- Добавлены константы фантома: PHANTOM_CHECK_FILLING_ID, NAME, HOURLY_RATE
- Новые states: waiting_loyalty_cards, waiting_check_filling

#### 3. FSM Flow — разделение потока официанта
- Официант теперь проходит три этапа: дата/время → карты → чеки
- Отдельные буферы медиагрупп: _mg_loyalty_* и _mg_filling_*
- 8 новых функций + 4 callback handler'а

#### 4. Апрув админом
- approve_loyalty_callback — апрувит карты, записывает AH офику
- approve_filling_callback — апрувит чеки, записывает в фантома
- Уведомления офику (два типа)
- Уведомление админу с балансом пула чеков

#### 5. Google Sheets — работа с фантомом
- write_check_filling_to_phantom() — запись с суммированием
- get_phantom_checks_summary() — чтение пула (first/second/last)
- Фантом ищется по TG_ID = 1984002026

#### 6. Расчёт зарплаты — показ пула
- В /hours_* для Официанта добавлена строка: "💳 Общий пул чеков: N шт (M р)"
- Пул показывается даже если равен 0
- Формат без пояснения про распределение

#### 7. Switch Month — перенос фантома
- Функция _transfer_phantom_to_new_month()
- Фантом вставляется первым в секцию Официантов
- H/AH обнулены, формулы S/AJ/AK вставлены
- Если не найден → warning, но switch_month не падает

#### 8. Тесты
- 35 новых тестов в 6 файлах
- Покрыты: константы, FSM, Google Sheets, апрув, расчёт, switch_month
- Итого: 112/112 ✅

### Технические детали:

**Фантом:**
- ID: 1984002026 (отсылка к роману "1984" + текущий год)
- Имя: "Наполняемость чека"
- Не в Техлисте, не в SQLite users
- Только строка в месячном листе

**Запись чеков:**
- Формат: только число (например "5")
- Суммирование в пределах дня
- value_input_option="RAW"

**Пул чеков:**
- S (col 19) — первая половина месяца (1-15)
- AJ (col 36) — вторая половина (16-конец)
- AK (col 37) — весь месяц

### Известные ограничения:

- Распределение чеков между официантами — вручную (пока нет UI)
- Фантом создаётся вручную (не через approve flow)
- Ставка фантома хардкодится в коде (не в БД)

### На горизонте:

- UI для распределения чеков менеджером
- Дополнение смен (добавить карты/чеки позже)
- Персональная статистика по чекам

---

## Post-Stage 16 Fixes ✅ (2026-05-13–14)

**Ветка:** main
**Тесты:** 122/122

### Баги исправлены:

1. **fix(google_sheets): ws.update_cell → ws.update в write_check_filling_to_phantom**
   - update_cell не принимает value_input_option как аргумент
   - Коммит: 51d5a28

2. **fix(google_sheets): .replace(",",".") перед float() в _parse_cell и _parse_simple**
   - Русская локаль Google Sheets возвращает "1,5" вместо "1.5"
   - ah_first всегда возвращал 0.0 из-за ValueError при парсинге
   - Коммит: 790133b

3. **fix(google_sheets): get_phantom_checks_summary падал на формате "2/0"**
   - Использовал ws.cell() — отдельный API-запрос вместо уже загруженных данных
   - int(float("2/0")) → ValueError → возвращал 0
   - Фикс: split("/")[0] + данные из all_values
   - Коммит: 30c9650

4. **fix(google_sheets): write_check_filling_to_phantom писал str(n) вместо n**
   - Текстовое "2" не суммируется формулой =СУММ()
   - Фикс: [[new_checks]] вместо [[str(new_checks)]]
   - Коммит: a6b1451

5. **fix(monthly_switch): логирование пропущенных строк в switch_month()**
   - Строки без TG_ID и с нечисловым TG_ID пропускались молча
   - Добавлены logger.warning для трёх случаев пропуска
   - Коммит: после a6b1451

6. **fix(google_sheets): Plain text формат для колонки B при добавлении сотрудника**
   - Автоматический формат → научная нотация → рассинхрон при switch_month
   - format("B{row}:B{row}", TEXT) добавлен рядом с format("D:AK")
   - Коммит: ddb3d23

### Корневая причина бага с Региной (switch_month пропустил сотрудника):

- Колонка B в месячном листе имела формат "Автоматический"
- Google Sheets отображал TG_ID в научной нотации
- switch_month не мог сматчить ID с Техлистом → аномалия → удаление строки
- Решение: явная установка Plain text для колонки B при добавлении сотрудника
  и рекомендация выставлять Plain text для всей колонки B вручную

---

## fix/pre-launch-audit ✅ завершён (2026-05-15)

**Ветка:** `fix/pre-launch-audit` → main (merge 4592d6d)  
**Тесты:** 122/122 ✅

### Фиксы (17 коммитов):

1. **fix(google_sheets):** retry для критичных `ws.update` в `write_shift` и `write_check_filling_to_phantom`
2. **fix(google_sheets):** `all_values` вместо отдельного `ws.cell()` в phantom read; `.replace(",",".")` для float в накоплении Раннера
3. **fix(google_sheets):** устранено двойное чтение `get_all_values` в `add_or_update_pending_user`
4. **fix(auth):** `user_info` передаётся в `ensure_user` из `process_approve` — исключена повторная запись в Техлист
5. **fix(auth):** `VALID_DOP_POSITIONS` из config вместо локального списка в `DOP_POSITIONS`
6. **fix(auth):** подавление `TelegramBadRequest` в `notify_approval`; `pop` вместо `del` в loyalty/filling callbacks
7. **fix(auth):** уведомление официанта при ошибке записи в loyalty/filling approve
8. **fix(auth):** отклонение `approved_count=0` в filling callback
9. **fix(userhours):** удалён `full_name` из логов смен (PII)
10. **fix(userhours):** сохранён `ctx` reference при обработке ошибок в delayed processors (loyalty/filling)
11. **fix(userhours):** добавлена подсказка `/cancel` в запросах фото карт/чеков
12. **fix(userreports):** warning при отсутствии `extra_rate` для Раннера/Бармена/Барбэка
13. **fix(monthly_switch):** уведомление суперадминов при критичных ошибках `switch_month()`
14. **fix(monthly_switch):** установка TEXT-формата для колонки B фантома после вставки
15. **fix(migration):** hardstop в `migrate_user_rates_once.py` для защиты от случайного перезапуска
16. **refactor(userhours):** `_cleanup_mg_buffers()` — выделен общий хелпер из except-блоков loyalty/filling
17. **feat(monitoring):** Sentry opt-in через `SENTRY_DSN` env var (`app/logging_config.py`)

### Мониторинг (коммиты db6cf26, d972259, 7ec6af0, 77b21d0):

**`app/logging_config.py` — TelegramHandler:**
- `TelegramHandler` — отправляет `ERROR`-логи разработчику через Telegram Bot API
- `IGNORED_ERRORS` — фильтр шума: `TelegramBadRequest`, `TelegramNetworkError`, `TelegramConnectionError`
- Подключён в `setup_logging()` через `_init_telegram_handler()`
- Усечение до 4000 символов (лимит Telegram)

**`app/utils/text_utils.py` — `format_alert()`:**
- Форматирует структурированный алёрт с контекстом: operation / tg_id / position / department / date / error / extra
- Используется в `google_sheets.py`, `auth.py`, `monthly_switch.py` для обогащённых error-логов

**Обогащённое логирование:**
- `google_sheets.py` — все критичные операции (write_shift, write_check_filling) логируют контекст через `format_alert`
- `auth.py` — ошибки в approve flow с указанием tg_id и позиции
- `monthly_switch.py` — ошибки переключения месяца с датой и статусом

---

## fix(userhours): Информативная ошибка при отсутствии сотрудника в листе ✅ (2026-05-19)

**Ветка:** main  
**Коммиты:** `89b2bd2`, `e157100`  
**Тесты:** 122/122 ✅

### Проблема

`write_shift()` бросает `ValueError: "Пользователь {tg_id} не найден в листе '{sheet_name}'"` когда сотрудник вводит смену за прошлый месяц (его строки в листе ещё не было). Все 5 вызовов `write_shift` ловили только `except Exception` → пользователь получал общее "❌ Ошибка записи."

### Что сделано

**Коммит 1 (89b2bd2):** Аудит `_write_and_finish_*` + фикс:
- `_write_and_finish` (Раннер)
- `_write_and_finish_bar` (Бармен/Барбэк)

**Коммит 2 (e157100):** Расширение на все оставшиеся вызовы:
- `process_shift_input` (Официант, ввод текстом)
- `_write_waiter_no_photo` (Официант без фото)
- `_process_simple_h_shifts` (Менеджер, Хостесс, Кухня, МОП)

**Паттерн во всех 5 местах:**

```python
except ValueError as e:
    if "не найден в листе" in str(e):
        await state.clear()
        await message.answer(
            "❌ Вы не числитесь в графике за указанный месяц.\n\n"
            "Смены можно вносить только за текущий месяц.\n"
            "Если вы уверены, что ошибки нет — обратитесь к администратору или разработчику."
        )
        logger.warning("write_shift: user %s not found in sheet: %s", tg_id, e)
        return
    raise  # неизвестный ValueError → except Exception
```

**Логика:** `state.clear()` → `answer()` → `logger.warning` (не error, это действие пользователя) → `return`. Неизвестный `ValueError` уходит в `except Exception` выше.

---

## На горизонте

- ⏸️ **Этап 2:** Auto-recovery wrapper для write_shift()
- ⏸️ **Этап 3:** Fix "message is not modified" при двойном approve
- 🧹 **Cleanup:** Решить судьбу временных скриптов fix_*.py

---

## Post-Audit Refactoring ✅ (2026-05-29)

**Ветка:** refactor/post-audit-fixes → main
**Тесты:** 122 → 158 (+36)

10 этапов рефакторинга по результатам полного аудита кодовой базы:

- **Этап 1:** удалён мёртвый код — 5 неиспользуемых импортов,
  4 мёртвые функции, 2 мёртвые переменные
- **Этап 2:** убран full_name из всех логов (PII protection) — 3 места
- **Этап 3:** устранены молчаливые except: pass, унифицировано
  логирование на logger.exception() — 17 мест в 4 файлах
- **Этап 4:** добавлен state.clear() при сетевой ошибке в dismiss_select
- **Этап 5:** все ws.update_cell() заменены на ws.update(RAW) — 5 вызовов
- **Этап 6:** централизованы константы и справочники в config.py —
  DEPARTMENTS, DEPT_TO_ADMIN_ROLE, AH_PHOTO_COEFFICIENT,
  COL_S/AJ/AK/AL/AM/AN, COLS_DATA_FIRST/SECOND, MONTH_NAMES_SHORT
- **Этап 7:** создан app/utils/formatting.py — fmt_hours, fmt_money,
  fmt_emp_rate; устранены 5 дублирующихся реализаций
- **Этап 8:** добавлен reconnect-retry для 5 критичных методов
  GoogleSheetsClient без защиты от сетевых сбоев
- **Этап 9:** рефакторинг тестов — общие fixtures в conftest.py,
  параметризация test_hours_without_rate
- **Этап 10:** новые тесты для критичных функций без покрытия —
  delete_user, _build_runner_earnings_lines, switch_month логика,
  dismiss_employee (19 новых тестов)
- **Хотфикс:** NameError в cb_switch_month_confirm (security review)

---

## fix(switch_month): batch techlist read — устранён N+1 → 429 ✅ (2026-06-28)

**Ветка:** main  
**Тесты:** 158 → 170 (+12)

### Проблема

`switch_month` вызывал `user_exists_in_techlist(tg_id)` внутри цикла переноса сотрудников. Каждый вызов выполнял `ws.get_all_values()` (полное чтение Техлиста). При N≈55 сотрудниках = ~63 read-запроса подряд → превышение квоты Google Sheets API (60 reads/min/user) → `APIError: [429] Quota exceeded`.

**Усугубляющий фактор:** `_reconnect()` не различал 429 от обрыва соединения. При 429 он вызывал `open_by_key()` → `fetch_sheet_metadata()` = ещё один read. Второй 429 прерывал операцию без retry.

**Формула до фикса:** `C(≈7 const reads) + N(reads в цикле) + 2(фантом)` — линейный рост с числом сотрудников.

### Решение

1. **`app/services/google_sheets.py`** — добавлен `get_techlist_ids() → set[str]`: читает Техлист **один раз**, возвращает нормализованный `set` ID (`str(value).strip()` для каждой ячейки колонки A).

2. **`app/scheduler/monthly_switch.py`** — до цикла:
   ```python
   techlist_ids = sheets_client.get_techlist_ids()   # 1 read
   ```
   в цикле:
   ```python
   in_techlist = str(tg_id).strip() in techlist_ids  # O(1), 0 API
   ```

3. `user_exists_in_techlist()` **не удалена** — используется в auth flow.

**Формула после фикса:** `C(≈7 const reads) + 1(techlist batch) + 2(фантом)` = константа, не зависит от N.

### Тесты (+12)

**`tests/test_switch_month_techlist_batch.py`:**
- `get_techlist_ids` возвращает `set` нормализованных строк (заголовок пропускается, пробелы обрезаются, пустые ID исключаются)
- Сетевая ошибка при чтении Техлиста → пустой `set` (safe default)
- `switch_month` вызывает `get_techlist_ids` ровно 1 раз
- `user_exists_in_techlist` в цикле НЕ вызывается
- В Техлисте → transferred; не в Техлисте → anomaly/removed
- Красная строка + не в Техлисте → removed (нормальное увольнение)
- Смешанный кейс: 2 активных + 1 уволенный
- Нормализация int и str-с-пробелами (кейс Регины)

## TODO (Фаза 2c, 2026-07-11)
- **2026-08-11**: удалить legacy-обработчики старого формата callback_data
  (`approve_ah_callback`, `approve_loyalty_callback`, `approve_filling_callback`
  в `app/bot/handlers/auth.py`) и in-memory `_pending_loyalty` / `_pending_filling`
  в `userhours.py` — оставлены на переходный месяц для кнопок, отправленных до
  деплоя Фазы 2c (новый формат: `apprv:{id}:{n}` / `rejct:{id}`, данные в
  таблице `pending_approvals`).

## В скоуп Фазы 5 (найдено при ревью Фазы 2c, 2026-07-14)
- **Напоминание о непроверенных заявках `pending_approvals`.** Для
  `approval_type='ah_photos'` смена официанта не пишется НИКУДА (ни в
  `shifts`, ни в Sheets) до решения админа — часы живут только в
  неразрешённой заявке. Если админ забыл нажать кнопку, официант думает,
  что смена принята, а по факту она нигде не зафиксирована — тихая
  потеря часов. Раньше это было тем же поведением через callback_data,
  просто теперь видно и измеримо через таблицу. Джоб: выборка
  `SELECT * FROM pending_approvals WHERE resolved_at IS NULL AND
  created_at < datetime('now', '-24 hours')`, пинг ответственным админам
  отдела (Зал) по каждой найденной заявке.

## В скоуп Фазы 3 (найдено при дифф-ревью перед деплоем, 2026-07-14)
- **Мигрировать `_fetch_user_info` на `employees`** — снимает блокировку
  апрува при упавшем зеркале регистрации. Сейчас `process_approve` читает
  данные заявки из Техлиста Sheets (`_fetch_user_info` → `get_user_from_techlist`),
  а не из SQLite. Если `add_or_update_pending_user` в `process_fio` упал
  (строка не попала в Техлист), заявка корректно лежит в `employees`
  (status='pending'), но админ никогда не сможет её одобрить через бота —
  `_fetch_user_info` всегда вернёт None, пока кто-то вручную не восстановит
  строку в Sheets. Известное ограничение до Фазы 3 (миграции чтений).
