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

## Audit Phase 1 ✅ завершена (5 критичных багов)

**Дата:** 2026-03-28  
**Ветка:** `fix/post-audit-bugs`

1. **_pending_custom_titles → _pending_admins**
   - Глобальный `_pending_custom_titles: dict[int, str]` удалён
   - Валидация custom_title: 2-50 символов в `process_kitchen_title` (FSM)
   - `custom_title` сохраняется в `_pending_admins[callback_key]` вместе с tg_id/row_index/full_name
   - `process_approve` читает `custom_title` из `_pending_admins` по callback_key
   - Очистка `_pending_custom_titles` в `process_reject` удалена
   - Файл: `auth.py`
   - Ветка: `fix/post-audit-clean` (2026-04-02)

2. **/message_dept + МОП**
   - admin_hall теперь выбирает отдел (Зал или МОП) перед вводом текста рассылки
   - Добавлена `_hall_dept_keyboard()` с кнопками Зал/МОП/Отмена
   - `cmd_message_dept`: проверка `admin_hall` до `_ROLE_TO_DEPT`, переходит в `waiting_broadcast_dept`
   - Существующий `cb_broadcast_dept` обрабатывает выбор без изменений
   - Файл: `admin.py`
   - Ветка: `fix/post-audit-clean` (2026-04-02)

3. **Инъекция формул Google Sheets**
   - `value_input_option="USER_ENTERED"` → `"RAW"` для пользовательских данных
   - Защита от `=HYPERLINK()`, `=IMPORTXML()` и других формул через `custom_title`/ФИО
   - Файлы: `google_sheets.py:417` (`insert_row` с `[full_name, telegram_id, display_position]`), `auth.py:293`
   - Строка `google_sheets.py:526` (`batch_update` с `=SUMPRODUCT`, `=S+AJ` и др.) намеренно оставлена с `USER_ENTERED` — там записываются hardcoded формулы из кода
   - Ветка: `fix/post-audit-clean` (2026-04-02)

4. **HTML-инъекция через user inputs в HTML-сообщениях**
   - `html.escape()` применён ко всем user inputs в parse_mode="HTML" сообщениях
   - Защита от `<a href="tg://...">` и других HTML-инъекций
   - `make_mention()` дублировалась в `userhours.py` и `auth.py` без экранирования `full_name`
   - Создан `app/utils/text_utils.py`: `make_mention()` с `html.escape(full_name)` + `mask_email()`
   - Локальные копии `make_mention()` удалены из обоих файлов, добавлен импорт из `text_utils`
   - `comment` (FSM input Раннера) → `html.escape(comment)` в `userhours.py`
   - `text` (сообщение пользователя разработчику) → `html.escape(text)` в `contact_dev_send`
   - `callback.from_user.full_name` → `html.escape(...)` в `process_approve` и `process_reject`
   - Все user inputs в HTML-сообщениях теперь экранируются
   - Файлы: `userhours.py`, `auth.py`, `app/utils/text_utils.py` (новый)
   - Ветка: `fix/post-audit-clean` (2026-04-02)

5. **_delayed_process_waiter без try/except**
   - Обработка исключений + `await state.clear()` при ошибке
   - Уведомление пользователю "Произошла ошибка, попробуйте снова"
   - Файл: `userhours.py:315, 413`

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
