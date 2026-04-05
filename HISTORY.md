# История этапов разработки HorecaTime

Этот файл содержит детальную историю всех завершённых этапов разработки проекта. Актуальное состояние проекта см. в **CLAUDE.md**.

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

## Ключевые изменения терминологии

**До:**
- Путаница между "отдел", "позиция", "должность"
- "Шеф/Су-шеф" как позиция

**После:**
- **Отдел** (department) = Зал/Бар/Кухня/МОП
- **Позиция** (position) = Официант/Раннер/Бармен
- **Должность** (custom_title) = "Су-шеф Иванов" (только для Шеф/Су-шеф и Грузчик/Закупщик)
- "Шеф/Су-шеф" → "Руководящий состав" в коде

---

## Новые файлы и модули

- `app/utils/text_utils.py` — `make_mention()`, `mask_email()`
- `migrate_user_rates_once.py` — одноразовая миграция (оставлен как документация)
- `.env.example` — шаблон environment переменных
- `AUDIT.md` — живой roadmap багов
- `HISTORY.md` — этот файл
- `TECH_REFERENCE.md` — технические детали

---

## Что впереди

- **Phase 3** — улучшения из AUDIT.md (10 желательных)
- **Docker** setup и деплой
- **Apps Script миграция** (отложено до ревью файлов)
- **Лицензионная система** (license server + PyArmor)
- **Web-панель** для конфигурации
- **Универсализация** для сторонних клиентов
