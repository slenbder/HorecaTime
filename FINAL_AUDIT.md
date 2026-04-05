
# АУДИТ БЕЗОПАСНОСТИ — HorecaTime

Дата: 2026-03-28
Ветка: `fix/post-audit-bugs`

---

## БЛОК 1: БЕЗОПАСНОСТЬ

---

### [🔴] Инъекция формул Google Sheets через ФИО и должность

**Файл:** `app/services/google_sheets.py:414`

**Проблема:**
`insert_row` при добавлении сотрудника в месячный лист вызывается с `value_input_option="USER_ENTERED"`, из-за чего Google Sheets интерпретирует строки, начинающиеся с `=`, как формулы. Поля `full_name` (ФИО из пользовательского ввода) и `display_position` (`custom_title` для Шеф/Су-шеф, без какой-либо валидации) попадают в ячейки без экранирования.

**Текущий код:**
```python
month_ws.insert_row(
    [full_name, str(telegram_id), display_position],
    index=new_row,
    value_input_option="USER_ENTERED",   # ← интерпретирует формулы
)
```

**Пример атаки:**
Пользователь вводит ФИО: `=HYPERLINK("https://evil.com","Иванов Иван")` — в таблице отображается кликабельная ссылка на внешний сайт вместо имени. Более серьёзные векторы: `=IMPORTXML(...)`, `=IMPORTDATA(...)` — могут делать запросы к внешним URL с Google-аккаунта владельца таблицы.

Для `custom_title` (поле для Шеф/Су-шеф, `auth.py:293`): валидация отсутствует полностью — ни длины, ни символов.

**Предложение:**
```python
# Вариант 1: RAW режим (формулы игнорируются)
month_ws.insert_row(
    [full_name, str(telegram_id), display_position],
    index=new_row,
    value_input_option="RAW",
)

# Вариант 2: префикс-апостроф (Google Sheets не интерпретирует как формулу)
def _sanitize_cell(value: str) -> str:
    """Предотвращает интерпретацию как формулу."""
    if value.startswith(("=", "+", "-", "@")):
        return "'" + value
    return value
```

Также добавить валидацию `custom_title`: `len(custom_title) < 2 or len(custom_title) > 50`.

**Приоритет:** 🔴 Критично — позволяет делать внешние запросы от имени Google-аккаунта владельца таблицы, подменять данные в документе

---

### [🔴] HTML-инъекция в уведомлениях администраторам (комментарий Раннера)

**Файл:** `app/bot/handlers/userhours.py:798`

**Проблема:**
Комментарий к доп. часам (`comment`), введённый пользователем-Раннером без какой-либо валидации или экранирования, напрямую интерполируется в HTML-сообщение, которое отправляется администраторам с `parse_mode="HTML"`.

**Текущий код:**
```python
admin_text = (
    f"📋 Раннер внёс смену\n\n"
    f"👤 {mention}\n"
    f"📅 {date}\n"
    f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч{weekend_mark}\n"
    f"🔢 Доп. часы = {_fmt_h(ah)} ч\n"
    f"💬 {comment}"      # ← user input без экранирования
)
...
await message.bot.send_message(..., parse_mode="HTML", ...)
```

**Пример атаки:**
Раннер вводит комментарий:
```
<a href="tg://user?id=123456789">🚨 Нажмите для подтверждения</a>
```
Администратор получит сообщение с кликабельной ссылкой на произвольного пользователя Telegram — вектор фишинга/социальной инженерии. Через `tg://` ссылки возможны переходы в каналы, боты, инициирование звонков.

**Предложение:**
```python
import html

admin_text = (
    f"📋 Раннер внёс смену\n\n"
    f"👤 {mention}\n"
    f"📅 {date}\n"
    f"⏱ {time_range} → Часы смены = {_fmt_h(h)} ч{weekend_mark}\n"
    f"🔢 Доп. часы = {_fmt_h(ah)} ч\n"
    f"💬 {html.escape(comment)}"   # ← экранировать все user inputs
)
```

Аналогичная проверка нужна везде, где user-input попадает в `parse_mode="HTML"` сообщения (см. также `full_name` в `make_mention`).

**Приоритет:** 🔴 Критично — позволяет Раннеру внедрять произвольные Telegram-ссылки в сообщения администраторам

---

### [🟡] Отсутствие проверки роли в `approve_ah_callback`

**Файл:** `app/bot/handlers/auth.py:478`

**Проблема:**
Хендлер `approve_ah_callback` (одобрение доп. часов официанта) не проверяет, что нажавший кнопку является `admin_hall` или `superadmin`. Кнопки отправляются только администраторам, однако в боте нет защиты на стороне хендлера — любой пользователь, получивший доступ к сообщению с кнопками (например, если бот добавлен в группу), может одобрить чужие часы.

**Текущий код:**
```python
@auth_router.callback_query(F.data.startswith("approve_ah:"))
async def approve_ah_callback(callback: CallbackQuery) -> None:
    # Нет проверки роли вызывающего
    if "✅ Одобрено" in (callback.message.text or ""):
        await callback.answer("Уже обработано другим администратором.")
        return
    ...
    sheets_client.write_shift(telegram_id, day, month, year, h, ah)
```

**Предложение:**
```python
@auth_router.callback_query(F.data.startswith("approve_ah:"))
async def approve_ah_callback(callback: CallbackQuery) -> None:
    caller_id = callback.from_user.id
    if caller_id not in ADMIN_HALL_IDS and caller_id not in SUPERADMIN_IDS and caller_id != DEVELOPER_ID:
        await callback.answer("⛔️ Недостаточно прав.", show_alert=True)
        return
    ...
```

**Приоритет:** 🟡 Важно — в текущей конфигурации (приватные чаты) риск низкий, но нарушает принцип defence-in-depth

---

### [🟡] Отсутствие проверки роли в `process_approve` / `process_reject`

**Файл:** `app/bot/handlers/auth.py:579`

**Проблема:**
Хендлер одобрения/отклонения заявок новых сотрудников проверяет только наличие `✅`/`❌` в тексте сообщения (защита от повторного нажатия), но не проверяет роль нажавшего. При добавлении бота в группу любой участник мог бы нажать кнопку «Одобрить».

**Текущий код:**
```python
@auth_router.callback_query(F.data.startswith("approve_"))
async def process_approve(callback: CallbackQuery):
    original_text = callback.message.text or ""
    if "✅" in original_text or "❌" in original_text:
        await callback.answer("Уже обработано другим администратором.")
        return
    # ← нет проверки роли callback.from_user.id
    ...
```

**Предложение:**
```python
caller_id = callback.from_user.id
allowed = set(ADMIN_HALL_IDS + ADMIN_BAR_IDS + ADMIN_KITCHEN_IDS + SUPERADMIN_IDS)
allowed.add(DEVELOPER_ID)
if caller_id not in allowed:
    await callback.answer("⛔️ Недостаточно прав.", show_alert=True)
    return
```

**Приоритет:** 🟡 Важно — риск повышается если бот когда-либо будет добавлен в группу

---

### [🟡] Email сотрудника логируется в открытом виде

**Файл:** `app/bot/handlers/auth.py:832`

**Проблема:**
Email адрес администратора, введённый при регистрации, записывается в `app.log` в открытом виде. При компрометации логов — утечка персональных данных.

**Текущий код:**
```python
logger.info(
    "process_promote_email: пользователь %s ввёл email %s, отдел %s",
    tg_id, email, dept   # ← email в plaintext
)
```

**Предложение:**
```python
logger.info(
    "process_promote_email: пользователь %s ввёл email (***@%s), отдел %s",
    tg_id, email.split("@")[-1], dept
)
```

**Приоритет:** 🟡 Важно — PII в логах, GDPR-риск

---

### [🟢] Ставки сотрудников логируются с привязкой к имени

**Файл:** `app/bot/handlers/admin.py:294,299`

**Проблема:**
Персональные ставки записываются в лог вместе с полным именем и telegram_id сотрудника. При получении доступа к `app.log` видны зарплатные данные конкретных людей.

**Текущий код:**
```python
logger.info("/set_rate: base=%s для %s, запрашиваю %s ставку", base_rate, full_name, extra_label)
logger.info("/set_rate: сохранено для %s (%s): base=%s", full_name, target_id, base_rate)
```

**Предложение:**
Логировать только `target_id` без `full_name`, либо перевести в уровень `DEBUG`.

**Приоритет:** 🟢 Желательно — утечка зарплатных данных при компрометации логов

---

### [🟢] callback_data — все размеры в пределах лимита

**Файл:** `app/bot/handlers/superadmin.py:421`

**Проверка пройдена.** Наиболее длинный callback_data в проекте — `promote_pos:{dept}:{pos}`:

```
"promote_pos:" = 12 байт
"Кухня"        = 10 байт (UTF-8, Кириллица 2 байта/символ)
":"            =  1 байт
"Заготовочный цех" = 31 байт
─────────────────────────────
Итого: 54 байта < 64 байт ✅
```

Все остальные callback_data значительно короче. Лимит Telegram не превышается нигде.

---

## БЛОК 1: БЕЗОПАСНОСТЬ — СВОДКА

Всего находок: 6
- 🔴 Критично: 2
- 🟡 Важно: 3
- 🟢 Желательно: 1

### Приоритет фиксов:
1. [🔴] Инъекция формул Google Sheets — `google_sheets.py:414`, `auth.py:293` (insert_row с USER_ENTERED + нет валидации custom_title)
2. [🔴] HTML-инъекция в admin-уведомлениях — `userhours.py:798` (comment без `html.escape`)
3. [🟡] Нет проверки роли в `approve_ah_callback` — `auth.py:478`
4. [🟡] Нет проверки роли в `process_approve`/`process_reject` — `auth.py:579`
5. [🟡] Email в логах plaintext — `auth.py:832`
6. [🟢] Зарплатные данные в логах с именем — `admin.py:294,299`

---

# БЛОК 2: НАДЁЖНОСТЬ

---

### [🔴] `_pending_custom_titles` теряется при перезапуске бота

**Файл:** `app/bot/handlers/auth.py:65–66, 471`

**Проблема:**
`custom_title` для позиции Шеф/Су-шеф хранится только в оперативной памяти (`dict`). При перезапуске бота все накопленные записи теряются. Если пользователь успел подать заявку до рестарта, а администратор одобряет её уже после — `_pending_custom_titles.pop(user_tg_id, None)` вернёт `None`, и сотрудник будет добавлен в месячный лист с позицией `"Шеф/Су-шеф"` вместо введённой должности (`"Су-шеф Горячев А.В."` и т.п.).

**Текущий код:**
```python
# auth.py:65-66
_pending_custom_titles: dict[int, str] = {}   # ← in-memory, не выживает рестарт

# auth.py:471 — сохранение при регистрации
if custom_title:
    _pending_custom_titles[tg_id] = custom_title
await state.clear()

# auth.py:625 — чтение при апруве (None если бот был перезапущен)
pending_custom_title = _pending_custom_titles.pop(user_tg_id, None)
sheets_client.ensure_user_in_current_month_hours(
    user_tg_id, custom_title=pending_custom_title  # ← будет None
)
```

**Предложение:**
Сохранять `custom_title` в FSM-данных до `state.clear()`, или в таблицу `users` (добавить колонку `custom_title`). При апруве читать из БД вместо in-memory dict.

**Приоритет:** 🔴 Критично — данные теряются при каждом перезапуске; сотрудники появляются в таблице с неверной должностью

---

### [🔴] `_delayed_process_waiter` запускается без обработки исключений

**Файл:** `app/bot/handlers/userhours.py:315, 386–417`

**Проблема:**
Функция `_delayed_process_waiter` запускается через `asyncio.create_task()` без `try/except`. При любой ошибке (сетевая ошибка Telegram, исключение в `_send_waiter_report`) исключение молча поглощается event loop — пользователь не получает ответа. В пути ошибки (`parse_shift` вернул `None`) FSM-состояние официанта не сбрасывается: `state.clear()` не вызывается, пользователь зависает в `waiting_shift_input`.

**Текущий код:**
```python
# userhours.py:315
asyncio.create_task(_delayed_process_waiter(mgid))   # нет try/except

# userhours.py:412-415 — ошибочный путь без очистки FSM:
result = parse_shift(caption, "Официант")
if result is None:
    await message.answer("❌ Не удалось распознать формат смены.")
    return   # ← state.clear() НЕ вызывается
```

**Предложение:**
```python
async def _delayed_process_waiter(mgid: str) -> None:
    await asyncio.sleep(1.0)
    try:
        ...
        if result is None:
            await state.clear()   # ← добавить
            await message.answer("❌ Не удалось распознать формат смены.")
            return
        await _send_waiter_report(...)
    except Exception:
        error_logger.exception("_delayed_process_waiter: необработанное исключение mgid=%s", mgid)
        _mg_photos.pop(mgid, None)
        _mg_context.pop(mgid, None)
        _mg_scheduled.discard(mgid)
        try:
            await state.clear()
            await message.answer("❌ Внутренняя ошибка. Попробуйте позже.")
        except Exception:
            pass
```

**Приоритет:** 🔴 Критично — официант зависает в FSM при неверном формате + необработанные исключения уходят в никуда

---

### [🟡] Три метода Google Sheets без try/except и reconnect

**Файл:** `app/services/google_sheets.py:244, 897, 905`

**Проблема:**
Методы `mark_user_approved`, `get_sheet_id_by_name`, `get_section_range` выполняют прямые сетевые вызовы к Google Sheets API без обработки ошибок и без вызова `_reconnect()`. При истёкшем токене или сетевом сбое исключение уходит к вызывающему коду.

- `mark_user_approved` → вызывается при апруве пользователя; сбой = ячейка «ДА» не выставлена, пользователь попадает в таблицу как не утверждённый
- `get_sheet_id_by_name` → вызывается при PDF-экспорте (`/schedule`)
- `get_section_range` → вызывается при PDF-экспорте (`/schedule`)

**Текущий код (пример):**
```python
# google_sheets.py:897-903
def get_sheet_id_by_name(self, sheet_name: str) -> int | None:
    worksheets = self._spreadsheet.worksheets()  # ← сетевой вызов без try/except
    for ws in worksheets:
        if ws.title == sheet_name:
            return ws.id
    return None
```

**Предложение:**
```python
def get_sheet_id_by_name(self, sheet_name: str) -> int | None:
    try:
        worksheets = self._spreadsheet.worksheets()
    except Exception as e:
        logger.warning("get_sheet_id_by_name: ошибка, реконнект: %s", e)
        self._reconnect()
        worksheets = self._spreadsheet.worksheets()
    ...
```

**Приоритет:** 🟡 Важно — при сетевом сбое команды апрув, `/schedule` падают с необработанным исключением

---

### [🟡] FSM `waiting_shift_input` и `waiting_ah_input` — нет явного способа выйти

**Файл:** `app/bot/handlers/userhours.py:117–171, 215–250`

**Проблема:**
Ни одно FSM-состояние для внесения смены (`waiting_shift_input`, `waiting_ah_input`, `waiting_ah_comment`) не предоставляет явного способа выйти из флоу. При вводе некорректных данных бот отвечает ошибкой — пользователь не знает, что `/shift` перезапустит флоу. Нет ни кнопки «Отмена», ни `/cancel`. Особенно проблематично для `waiting_ah_input` (Раннер, Бармен/Барбэк): если пользователь ошибся с первым шагом, единственный выход нигде не описан.

**Текущий код:**
```python
# waiting_ah_input — ошибка ввода, FSM не сбрасывается, подсказки нет:
await message.answer(
    "❌ Не удалось распознать формат. "
    "Введите диапазон (например <code>22:00-02:00</code>) или 0:"
)
return   # ← пользователь не знает что можно ввести /shift
```

**Предложение:**
Добавить в сообщения об ошибке: `"\n\nДля отмены нажмите /shift"` — и/или зарегистрировать хендлер `/cancel` (или `CommandStart`) который делает `state.clear()` при любом активном состоянии.

**Приоритет:** 🟡 Важно — UX-ловушка, особенно для новых пользователей

---

### [🟢] Неполная очистка буфера в `_delayed_process_waiter` при пустом списке фото

**Файл:** `app/bot/handlers/userhours.py:396–397`

**Проблема:**
Ветка `if not photo_ids: return` (пустой список, не `None`) возвращается без очистки `_mg_context[mgid]` и записи `_mg_scheduled.discard(mgid)`. Если `mgid` попадёт в это состояние, запись в `_mg_scheduled` останется навсегда, не позволяя создать новый таймер для этой медиагруппы.

**Текущий код:**
```python
if not photo_ids:
    return   # ← _mg_context и _mg_scheduled не очищены
```

**Предложение:**
```python
if not photo_ids:
    _mg_context.pop(mgid, None)
    _mg_scheduled.discard(mgid)
    return
```

**Приоритет:** 🟢 Желательно — патологический кейс, на практике почти не достижим

---

## БЛОК 2: НАДЁЖНОСТЬ — СВОДКА

Всего находок: 5
- 🔴 Критично: 2
- 🟡 Важно: 2
- 🟢 Желательно: 1

### Приоритет фиксов:
1. [🔴] `_pending_custom_titles` теряется при рестарте — `auth.py:471` (персистить в SQLite/FSM)
2. [🔴] `_delayed_process_waiter` без try/except + FSM не сбрасывается при ошибке — `userhours.py:315, 413`
3. [🟡] Три метода Google Sheets без retry — `google_sheets.py:244, 897, 905`
4. [🟡] FSM без явного выхода — `userhours.py:117–250`
5. [🟢] Неполная очистка буфера при пустом списке фото — `userhours.py:396`

---

# БЛОК 3: КАЧЕСТВО КОДА

---

### [🟡] `make_mention()` определена в двух файлах независимо

**Файл:** `app/bot/handlers/auth.py:43`, `app/bot/handlers/userhours.py:40`

**Проблема:**
Функция `make_mention` (формирование HTML-ссылки на пользователя Telegram) определена в двух файлах с идентичной реализацией. Если потребуется добавить `html.escape(full_name)` (см. находку [🔴] в Блоке 1), придётся исправлять оба файла. Дублирование — прямой источник расхождений.

**Текущий код (оба файла идентичны):**
```python
def make_mention(username: str | None, full_name: str) -> str:
    """Возвращает кликабельный ник или ФИО если ника нет."""
    if username:
        return f'<a href="https://t.me/{username}">{full_name}</a>'
    return full_name
```

**Использование:**
- `auth.py`: 2 вызова (строки 616, 830)
- `userhours.py`: 4 вызова (строки 370, 451, 622, 682)

**Предложение:**
Вынести в `app/bot/utils.py` или `app/bot/helpers.py` и импортировать из обоих файлов.

**Приоритет:** 🟡 Важно — при фиксе HTML-инъекции из Блока 1 риск забыть второй файл

---

### [🟡] Списки позиций дублируются в 5 файлах

**Файлы:** `admin.py:31`, `superadmin.py:36`, `userhours.py:70–76`, `monthly_switch.py:15–18`, `google_sheets.py:POSITION_TO_SECTION`

**Проблема:**
Наборы позиций по отделам определены отдельно в каждом файле под разными именами:

| Имя константы | Файл | Строки |
|---|---|---|
| `_DEPT_POSITIONS` | `admin.py` | 31–38 |
| `_DEPT_POSITIONS_ORDER` | `superadmin.py` | 36–43 |
| `KITCHEN_POSITIONS`, `MOP_POSITIONS`, `SIMPLE_H_POSITIONS` | `userhours.py` | 70–76 |
| `_SIMPLE_H_POSITIONS` | `monthly_switch.py` | 15–18 |
| `POSITION_TO_SECTION` | `google_sheets.py` | 40–50 |

При добавлении новой позиции нужно обновить минимум 5 мест. Это уже происходило при вводе Грузчика/Закупщика/МОП — и все места действительно обновлены (что говорит о дисциплине), но риск пропустить одно место со временем растёт.

**Предложение:**
Создать `app/constants.py` (или `app/positions.py`) с каноническими наборами и импортировать отовсюду:
```python
# app/positions.py
KITCHEN_POSITIONS = frozenset({"Су-шеф", "Горячий цех", ...})
MOP_POSITIONS     = frozenset({"Клининг", "Котломой"})
BAR_POSITIONS     = frozenset({"Бармен", "Барбэк"})
POSITIONS_WITH_EXTRA = frozenset({"Раннер", "Бармен", "Барбэк"})
```

**Приоритет:** 🟡 Важно — каждая новая позиция требует обновления 5+ мест

---

### [🟡] Импорт приватной функции `_parse_time` в userhours.py

**Файл:** `app/bot/handlers/userhours.py:21`

**Проблема:**
`userhours.py` напрямую импортирует `_parse_time` из `timeparsing.py` — функцию с префиксом `_` (условно приватную). Это нарушает контракт: потребители модуля не должны использовать внутренние детали. Если реализация `_parse_time` изменится или функция будет переименована, тест-слой не предупредит.

**Текущий код:**
```python
from app.services.timeparsing import parse_shift, check_overlap, _parse_time, round_to_half
```

**Предложение:**
Либо переименовать `_parse_time` в `parse_time` (сделать публичной), либо реализовать нужную логику внутри `userhours.py` без импорта приватного символа.

**Приоритет:** 🟡 Важно — нарушает инкапсуляцию сервисного модуля

---

### [🟢] Три функции-«монолита» (>100 строк)

**Файлы:** `auth.py:580`, `google_sheets.py:354`, `scheduler/monthly_switch.py:100`

**Проблема:**
Три функции значительно превышают разумный предел для одной функции:

| Функция | Файл | Строки | Ответственностей |
|---|---|---|---|
| `process_approve()` | `auth.py:580` | ~136 | 7 (парсинг, Sheets, SQLite, ставки, кеш, команды, уведомления) |
| `ensure_user_in_current_month_hours()` | `google_sheets.py:354` | ~185 | 5 (поиск, вставка, форматирование, формулы, ресайз) |
| `switch_month()` | `monthly_switch.py:100` | ~240 | 8 (снимки ставок, дубль листа, перенос, очистка, уведомления и т.д.) |

Функции работают корректно, но сложно тестировать и отлаживать изолированно.

**Пример декомпозиции `process_approve()`:**
```python
# Из 136 строк можно выделить:
async def _add_user_to_monthly_sheet(...)   # ensure_user + custom_title
async def _assign_default_rate(...)         # копирование ставки из rates → user_rates
async def _notify_user_approved(...)        # уведомление + команды меню
async def process_approve(...)              # оркестратор ~30 строк
```

**Приоритет:** 🟢 Желательно — рефакторинг для читаемости и тестируемости, не влияет на работу

---

### [🟢] Хардкод списка позиций внутри `process_approve()`

**Файл:** `app/bot/handlers/auth.py:653–657`

**Проблема:**
Внутри функции `process_approve()` определён inline-список всех позиций для проверки принадлежности:

**Текущий код:**
```python
_KNOWN_POSITIONS = {
    "Официант", "Раннер", "Хостесс", "Менеджер", "Бармен", "Барбэк",
    "Горячий цех", "Холодный цех", "Кондитерский цех", "Заготовочный цех",
    "Коренной цех", "Грузчик", "Закупщик", "Клининг", "Котломой",
}
```

Это шестая копия аналогичного списка по проекту (см. находку выше). Определена прямо внутри тела функции, пересоздаётся при каждом вызове.

**Предложение:**
Заменить на импорт из `app/positions.py` или хотя бы вынести на уровень модуля.

**Приоритет:** 🟢 Желательно — часть более широкой проблемы дублирования позиций

---

### Чисто: TODO/FIXME, print()

- **TODO/FIXME/HACK:** не найдено ни одного — кодовая база чистая
- **print():** не найдено ни одного — весь вывод идёт через `logging` ✅

---

## БЛОК 3: КАЧЕСТВО КОДА — СВОДКА

Всего находок: 5
- 🔴 Критично: 0
- 🟡 Важно: 3
- 🟢 Желательно: 2

### Приоритет фиксов:
1. [🟡] `make_mention()` дублируется — `auth.py:43`, `userhours.py:40` (вынести в `utils.py`)
2. [🟡] Списки позиций в 5 файлах — `admin.py:31`, `superadmin.py:36`, `userhours.py:70`, `monthly_switch.py:15`, `google_sheets.py:40` (централизовать в `app/positions.py`)
3. [🟡] Импорт `_parse_time` (приватный символ) — `userhours.py:21`
4. [🟢] Три функции >100 строк — `auth.py:580`, `google_sheets.py:354`, `monthly_switch.py:100`
5. [🟢] Inline список позиций в `process_approve()` — `auth.py:653`

---

# БЛОК 4: АРХИТЕКТУРА

---

### [🟡] Глобальное изменяемое состояние в `userhours.py` без asyncio.Lock

**Файл:** `app/bot/handlers/userhours.py:106–110`

**Проблема:**
Три модульных переменных хранят общее состояние медиагрупп официантов:

```python
_mg_photos:    dict[str, list[str]] = {}
_mg_context:   dict[str, dict]      = {}
_mg_scheduled: set[str]             = set()
```

Формально, в asyncio race conditions возникают только на `await`-точках, и критические секции (проверка + запись в dict) не разделены `await` — поэтому реальных гонок в текущем коде нет. Однако архитектурно это антипаттерн: глобальный изменяемый state без явной защиты становится хрупким при любом рефакторинге (добавление `await`, введение ThreadPoolExecutor, переход на многопроцессорный деплой).

Конкретный риск сейчас: если в `_delayed_process_waiter` добавят `await` между `ctx = _mg_context.pop(mgid)` и `_mg_photos.pop(mgid)`, они немедленно станут race condition.

**Предложение:**
```python
_mg_lock = asyncio.Lock()

# При записи:
async with _mg_lock:
    if mgid not in _mg_photos:
        _mg_photos[mgid] = []
        ...

# При чтении/очистке в _delayed_process_waiter:
async with _mg_lock:
    photo_ids = _mg_photos.pop(mgid, None)
    ctx = _mg_context.pop(mgid, None)
    _mg_scheduled.discard(mgid)
```

**Приоритет:** 🟡 Важно — сейчас безопасно, но архитектурно хрупко; любой `await` в критической секции превращается в баг

---

### [🟢] Порядок регистрации роутеров в main.py — корректен

**Файл:** `main.py:54–58`

**Проверка пройдена.** Порядок:
```python
dp.include_router(auth_router)        # 1 — auth + approve flow
dp.include_router(userhours_router)   # 2 — /shift FSM
dp.include_router(reports_router)     # 3 — /hours_*, /schedule
dp.include_router(admin_router)       # 4 — /rates, /set_rate
dp.include_router(superadmin_router)  # 5 — /rates_all, /promote, /demote
```

Проверены потенциальные конфликты callback-хендлеров:
- `approve_ah:` (userhours_router) зарегистрирован **до** `approve_` (auth_router) — корректно (специфичный раньше общего)
- `setrate_pos:` используется в **разных FSM-состояниях** в admin_router и superadmin_router (`waiting_position` vs `waiting_set_rate_position`) — конфликта нет
- Все остальные паттерны уникальны

**Статус:** ✅ Конфликтов не обнаружено

---

### [🟢] Circular imports — отсутствуют

**Проверка пройдена.** Граф зависимостей строго однонаправленный:

```
stdlib / third-party
    ↓
config.py            (только os + dotenv)
    ↓
app/db/models.py     (config + aiosqlite)
app/services/*.py    (config + gspread)
    ↓
app/bot/handlers/*.py (db, services, config)
    ↓
main.py              (все вышеперечисленные)
```

Ни один нижний слой не импортирует верхний. **Статус:** ✅ Чисто

---

### [🟢] Новые позиции (МОП, Грузчик, Закупщик) — покрытие полное

**Проверка пройдена.** Все позиции присутствуют в:

| Место | Файл | Статус |
|---|---|---|
| `VALID_POSITIONS` | `auth.py:50–58` | ✅ |
| `POSITION_TO_SECTION` | `auth.py:68–83` + `google_sheets.py:40–50` | ✅ |
| `_DEPT_POSITIONS` | `admin.py:31–38` | ✅ |
| `_DEPT_POSITIONS_ORDER` | `superadmin.py:36–43` | ✅ |
| `SIMPLE_H_POSITIONS` / `_SIMPLE_H_POSITIONS` | `userhours.py:76` + `monthly_switch.py:15–18` | ✅ |
| Дефолтные ставки | `models.py` | ✅ |
| `department_keyboard` | `keyboards/common.py` | ✅ |

Единственное замечание: позиции определены **повторно** в каждом из этих мест (см. Блок 3, находка о дублировании).

**Статус:** ✅ Пропусков не обнаружено

---

## БЛОК 4: АРХИТЕКТУРА — СВОДКА

Всего находок: 4
- 🔴 Критично: 0
- 🟡 Важно: 1
- 🟢 Желательно: 3

### Приоритет фиксов:
1. [🟡] Глобальный мутабельный state `_mg_*` без asyncio.Lock — `userhours.py:106–110`
2. [🟢] Порядок роутеров — корректен, изменений не требует
3. [🟢] Circular imports — отсутствуют, изменений не требует
4. [🟢] Покрытие новых позиций — полное, изменений не требует

---

# БЛОК 5: ДЕПЛОЙ

---

### [🟡] `requests` используется, но отсутствует в requirements.txt

**Файл:** `app/services/pdfservice.py:3`

**Проблема:**
`pdfservice.py` импортирует `requests` напрямую, однако эта библиотека не указана в `requirements.txt`. На чистом окружении (деплой, CI/CD, новый разработчик) установка зависимостей через `pip install -r requirements.txt` не установит `requests`, и при первом вызове `/schedule` бот упадёт с `ImportError`.

Сейчас `requests` работает как транзитивная зависимость `gspread` или `oauth2client`, но это ненадёжно — транзитивные зависимости могут быть удалены в любой момент при обновлении.

**Текущий импорт:**
```python
# pdfservice.py:3
import requests   # ← нет в requirements.txt
```

**Предложение:**
Добавить в `requirements.txt`:
```
requests==2.31.0
```

**Приоритет:** 🟡 Важно — проект неустановим без `requests` в чистом окружении; скрытый сбой при деплое

---

### [🟡] Отсутствует `.env.example`

**Проблема:**
Файл `.env.example` не существует в репозитории. Все обязательные переменные окружения документированы только в `CLAUDE.md` (который выведен из отслеживания по духу — хотя фактически закоммичен). На практике новый разработчик или деплой-скрипт не имеет шаблона для создания `.env`.

Список переменных из `config.py`:
- `BOT_TOKEN` — обязательная, без неё бот не запустится (выброс ValueError)
- `SPREADSHEET_ID` — обязательная, без неё бот не запустится (выброс ValueError)
- `GOOGLE_CREDENTIALS_PATH` — с дефолтом `credentials.json`, но файл нужно создать
- `ADMIN_HALL_IDS`, `ADMIN_BAR_IDS`, `ADMIN_KITCHEN_IDS` — без них роли не работают
- `SUPERADMIN_IDS`, `DEVELOPER_ID` — без них суперадмины не распознаются
- `SHEET_URL` — без неё кнопка «Открыть график» отдаёт пустую ссылку

**Предложение:**
Создать `.env.example`:
```dotenv
# Telegram Bot
BOT_TOKEN=your_bot_token_here

# Google Sheets
GOOGLE_CREDENTIALS_PATH=credentials.json
SPREADSHEET_ID=your_spreadsheet_id_here
SHEET_URL=https://docs.google.com/spreadsheets/d/...

# Role IDs (comma-separated Telegram IDs)
ADMIN_HALL_IDS=123456789,987654321
ADMIN_BAR_IDS=
ADMIN_KITCHEN_IDS=
SUPERADMIN_IDS=123456789
DEVELOPER_ID=123456789
```

**Приоритет:** 🟡 Важно — без шаблона первый деплой требует ручного изучения кода

---

### [🟢] `Pillow==10.4.0` в requirements.txt — не используется

**Файл:** `requirements.txt`

**Проблема:**
`Pillow` перечислена в зависимостях, однако нигде в коде (`app/`, `main.py`, `config.py`) нет импорта `PIL` или `pillow`. Библиотека устанавливается без необходимости, добавляет ~30 MB к образу.

**Предложение:**
Удалить строку `Pillow==10.4.0` из `requirements.txt`, если нет планов её использовать.

**Приоритет:** 🟢 Желательно — лишний вес образа, но не функциональная проблема

---

### [🟢] `.gitignore` — отсутствует `.pytest_cache/`, `CLAUDE.md` задвоен

**Файл:** `.gitignore`

**Проблема:**
Два замечания:

1. `.pytest_cache/` не указан в `.gitignore`. Случайно папка не закоммичена (проверено через `git ls-files`), но явная запись — защита от будущих ошибок.

2. `CLAUDE.md` добавлен в `.gitignore`, но при этом уже отслеживается Git (`git ls-files | grep CLAUDE`). Для отслеживаемых файлов `.gitignore` не действует, поэтому правило никого не защищает, но создаёт ложное ощущение исключения.

**Предложение:**
```gitignore
# Добавить:
.pytest_cache/
```
Для `CLAUDE.md` — либо убрать из `.gitignore` (раз он отслеживается), либо выполнить `git rm --cached CLAUDE.md`.

**Приоритет:** 🟢 Желательно — порядок в инфраструктуре

---

### Чисто: ротация логов, graceful shutdown

**Ротация логов** (`app/logging_config.py`):
Все три хендлера (`app.log`, `errors.log`, `google_api.log`) настроены с `RotatingFileHandler`, `maxBytes=5_000_000`, `backupCount=7`. **Статус:** ✅ Настроено корректно

**Graceful shutdown** (`main.py:79–85`):
Планировщик и сессия бота завершаются в `finally`-блоке:
```python
try:
    await dp.start_polling(bot)
finally:
    scheduler.shutdown()
    await bot.session.close()
```
`dp.start_polling()` перехватывает SIGINT/SIGTERM нативно в aiogram 3.x. **Статус:** ✅ Корректно

**Секреты в git** (`git ls-files`):
Проверка не нашла `.env`, `bot.db`, `credentials*.json` в отслеживаемых файлах. **Статус:** ✅ Чисто

---

## БЛОК 5: ДЕПЛОЙ — СВОДКА

Всего находок: 4
- 🔴 Критично: 0
- 🟡 Важно: 2
- 🟢 Желательно: 2

### Приоритет фиксов:
1. [🟡] `requests` не в requirements.txt — `requirements.txt` (добавить пакет)
2. [🟡] Отсутствует `.env.example` — создать шаблон переменных
3. [🟢] `Pillow` в requirements но не используется — удалить
4. [🟢] `.pytest_cache/` и `CLAUDE.md` в `.gitignore` — навести порядок

---

# БЛОК 6: ТЕСТЫ

---

### [🟡] Нет тестов для `models.py` — критичные DB-операции непокрыты

**Файл:** `app/db/models.py`

**Проблема:**
В `tests/` существует только `test_timeparsing.py`. Ни одна функция `models.py` не покрыта тестами. Это наиболее критичная область — ошибка в функциях работы с БД ведёт к молчаливому повреждению данных (неверные ставки, потеря снимков).

Функции без тестов:
| Функция | Риск |
|---|---|
| `get_user_rate(db_path, telegram_id)` | Возвращает неверные данные — зарплата считается неправильно |
| `set_user_rate(db_path, telegram_id, base, extra)` | Ставка не сохраняется / перезаписывает чужую |
| `snapshot_user_rates_history(db_path, month, year)` | Снимок при `switch_month()` не создаётся — `/hours_last` даёт неверный расчёт |
| `get_user_rate_history(db_path, telegram_id, month, year)` | Fallback на историю ломается |
| `init_db(db_path)` | Таблицы не создаются или создаются с неверной схемой |

**Предложение:**
Добавить `tests/test_models.py` с тестами на реальной SQLite in-memory БД:
```python
import pytest, aiosqlite
from app.db.models import init_db, set_user_rate, get_user_rate

@pytest.mark.asyncio
async def test_set_and_get_user_rate(tmp_path):
    db_path = str(tmp_path / "test.db")
    await init_db(db_path)
    await set_user_rate(db_path, 12345, base_rate=350.0, extra_rate=500.0)
    rate = await get_user_rate(db_path, 12345)
    assert rate["base_rate"] == 350.0
    assert rate["extra_rate"] == 500.0
```

**Приоритет:** 🟡 Важно — ошибка в `snapshot_user_rates_history` или `set_user_rate` не обнаруживается без тестов; `switch_month()` вызывается раз в месяц и баг может быть незамечен

---

### [🟡] Нет тестов для `get_section_range()` и `get_sheet_id_by_name()`

**Файл:** `app/services/google_sheets.py`

**Проблема:**
`get_section_range()` отвечает за поиск блока отдела в месячном листе для PDF-экспорта. Функция использует регистронезависимый поиск (`lower()`), однако логика поиска границ секции нетривиальна. Отсутствие тестов означает, что регрессия при рефакторинге не будет поймана.

Аналогично `get_sheet_id_by_name()` — используется в каждом вызове `/schedule`.

Эти функции можно тестировать с мок-объектом листа, без реального API.

**Предложение:**
Добавить `tests/test_google_sheets.py`:
```python
from app.services.google_sheets import GoogleSheetsClient

def test_get_section_range_finds_block():
    """Тест с мок-листом, содержащим секцию КУХНЯ."""
    mock_ws = ...  # список ячеек с known структурой
    result = GoogleSheetsClient._find_section_range(mock_ws, "кухня")
    assert result == (start_row, end_row)
```

**Приоритет:** 🟡 Важно — `/schedule` ломается при регрессии без теста; логика нетривиальна

---

### [🟡] `snapshot_user_rates_history()` не покрыта тестом

**Файл:** `app/db/models.py` / `app/scheduler/monthly_switch.py`

**Проблема:**
Функция `snapshot_user_rates_history()` вызывается один раз в месяц при `switch_month()` и записывает исторический снимок ставок. Если произойдёт ошибка (дублирующий снимок, неверный месяц), это выяснится только через месяц при `/hours_last` — когда исправить уже сложно.

Конкретные риски:
- `INSERT OR IGNORE` не обновит снимок при повторном вызове (тест проверил бы поведение)
- При ручном вызове `/switch_month` дважды в одном месяце второй снимок молча игнорируется (потенциально некорректное поведение)

**Предложение:**
Тест с SQLite in-memory, подтверждающий идемпотентность снимка и корректный `(month, year)`.

**Приоритет:** 🟡 Важно — критичный для финансового расчёта процесс; ошибка видна только через месяц

---

### [🟢] `check_overlap` — покрыт, но отсутствует граничный кейс

**Файл:** `tests/test_timeparsing.py:202–220`

**Проверка почти пройдена.** Четыре теста покрывают основные сценарии:
- `test_no_overlap_sequential` — нет пересечения ✅
- `test_overlap_crossing` — пересечение ✅
- `test_both_midnight_overlap` — оба диапазона через полночь ✅
- `test_boundary_no_overlap` — граничный случай без пересечения ✅

**Непокрытый кейс:**
Один диапазон НЕ пересекает полночь, второй — пересекает. Например: основная смена `20:00–23:00`, тусовка `22:00–02:00` — пересечение должно быть обнаружено. Текущие тесты проверяют оба-через-полночь, но не смешанный случай.

**Приоритет:** 🟢 Желательно — вероятный сценарий в реальном использовании

---

## БЛОК 6: ТЕСТЫ — СВОДКА

Всего находок: 4
- 🔴 Критично: 0
- 🟡 Важно: 3
- 🟢 Желательно: 1

### Приоритет фиксов:
1. [🟡] Нет тестов для `models.py` — `tests/test_models.py` (написать)
2. [🟡] Нет тестов для `snapshot_user_rates_history()` — `tests/test_models.py` (написать)
3. [🟡] Нет тестов для `get_section_range()` / `get_sheet_id_by_name()` — `tests/test_google_sheets.py` (написать)
4. [🟢] `check_overlap` — добавить смешанный кейс `test_timeparsing.py`

---

# БЛОК 7: КОНСИСТЕНТНОСТЬ ДАННЫХ

---

### [🔴] `/message_dept` не отправляет МОП-сотрудникам при рассылке `admin_hall`

**Файл:** `app/bot/handlers/admin.py:349–354`, `app/db/models.py:211`

**Проблема:**
Когда `admin_hall` вызывает `/message_dept`, команда автоматически определяет отдел через `_ROLE_TO_DEPT["admin_hall"] = "Зал"`. Затем вызывается `get_users_by_department(DB_PATH, "Зал")`, которая возвращает **только** пользователей с `department = "Зал"`.

МОП-сотрудники (Клининг, Котломой) имеют `department = "МОП"` в SQLite. Они **не попадают** в рассылку, хотя по логике системы `admin_hall` управляет МОП-отделом.

Несоответствие с остальными функциями `admin_hall`:
- `/rates` — включает МОП ✅ (`admin.py:114–116`)
- `/set_rate` — включает МОП ✅ (`admin.py:161–162`)
- Уведомления о заявках МОП → `ADMIN_HALL_IDS` ✅ (`auth.py:432`)
- `/message_dept` — МОП **не включён** ❌ (`admin.py:349–354`)

**Текущий код:**
```python
# admin.py:349
if user_role in _ROLE_TO_DEPT:
    dept = _ROLE_TO_DEPT[user_role]  # "Зал"
    await state.update_data(broadcast_type="dept", broadcast_dept=dept)

# models.py:211 — только department == "Зал"
async def get_users_by_department(db_path: str, department: str) -> list[dict]:
    async with db.execute(
        'SELECT ... FROM users WHERE department = ?',
        (department,)
    ) as cursor:
```

**Предложение:**
```python
# admin.py — при рассылке для Зала добавить МОП
if user_role in _ROLE_TO_DEPT:
    dept = _ROLE_TO_DEPT[user_role]  # "Зал"
    recipients = await get_users_by_department(DB_PATH, dept)
    if dept == "Зал":
        mop_users = await get_users_by_department(DB_PATH, "МОП")
        seen = {u["telegram_id"] for u in recipients}
        recipients += [u for u in mop_users if u["telegram_id"] not in seen]
```

**Приоритет:** 🔴 Критично — рассылка от `admin_hall` не доходит до МОП-сотрудников; нарушение задокументированной ролевой модели (МОП подчиняется admin_hall)

---

### Чисто: POSITION_TO_SECTION, POSITIONS_WITH_EXTRA, DEPARTMENT_TO_HEADER

**POSITION_TO_SECTION vs VALID_POSITIONS:**
Все реальные позиции корректно маппируются:
- `"Шеф/Су-шеф"` (UI) → `custom_title` → `"Су-шеф"` → `"Руководящий состав"` ✅
- `"Доп."` (UI) → `"Грузчик"` / `"Закупщик"` → `"Дополнительные сотрудники"` ✅
- `"Клининг"`, `"Котломой"` → `"Клининг"`, `"Котломой"` ✅
- Все 16 реальных позиций покрыты. **Статус:** ✅ Чисто

**POSITIONS_WITH_EXTRA:**
`{"Бармен", "Барбэк", "Раннер"}` — идентично в `admin.py:39` и `superadmin.py:32`. `userreports.py` и `userhours.py` используют отдельные переменные, но охватывают тот же набор. **Статус:** ✅ Чисто

**DEPARTMENT_TO_HEADER:**
Все 4 отдела (`Зал`, `Бар`, `Кухня`, `МОП`) присутствуют: `"ЗАЛ"`, `"БАР"`, `"КУХНЯ"`, `"Моп"`. **Статус:** ✅ Чисто

**Роли admin_hall + МОП (кроме /message_dept выше):**
- `/rates` + `/set_rate` → include МОП ✅
- Approve-flow → МОП → `ADMIN_HALL_IDS` ✅
- `/message_dept` → МОП не включён ❌ (см. находку выше)

---

## БЛОК 7: КОНСИСТЕНТНОСТЬ — СВОДКА

Всего находок: 1
- 🔴 Критично: 1
- 🟡 Важно: 0
- 🟢 Желательно: 0

### Приоритет фиксов:
1. [🔴] `/message_dept` не отправляет МОП при рассылке `admin_hall` — `admin.py:349–354`

---

# ИТОГОВАЯ СВОДКА АУДИТА

## Статистика по блокам

| Блок | 🔴 Критично | 🟡 Важно | 🟢 Желательно | Всего |
|------|-------------|----------|---------------|-------|
| 1. Безопасность | 2 | 3 | 1 | 6 |
| 2. Надёжность | 2 | 2 | 1 | 5 |
| 3. Качество кода | 0 | 3 | 2 | 5 |
| 4. Архитектура | 0 | 1 | 3 | 4 |
| 5. Деплой | 0 | 2 | 2 | 4 |
| 6. Тесты | 0 | 3 | 1 | 4 |
| 7. Консистентность | 1 | 0 | 0 | 1 |
| **ИТОГО** | **5** | **14** | **10** | **29** |

---

## Roadmap фиксов (приоритетный порядок)

### Фаза 1: Критичные 🔴 (блокируют деплой)
1. [Блок 1] Инъекция формул Google Sheets через ФИО / custom_title (`google_sheets.py:414`, `auth.py:293`)
2. [Блок 1] HTML-инъекция в admin-уведомлениях через комментарий Раннера (`userhours.py:798`)
3. [Блок 2] `_pending_custom_titles` теряется при рестарте → Шеф/Су-шеф в таблице без должности (`auth.py:471`)
4. [Блок 2] `_delayed_process_waiter` без try/except + официант зависает в FSM при ошибке (`userhours.py:315, 413`)
5. [Блок 7] `/message_dept` не отправляет МОП при рассылке `admin_hall` (`admin.py:349–354`)

### Фаза 2: Важные 🟡 (желательно до деплоя)
1. [Блок 1] Нет проверки роли в `approve_ah_callback` (`auth.py:478`)
2. [Блок 1] Нет проверки роли в `process_approve`/`process_reject` (`auth.py:579`)
3. [Блок 1] Email логируется в plaintext (`auth.py:832`)
4. [Блок 2] Три метода Google Sheets без retry (`google_sheets.py:244, 897, 905`)
5. [Блок 2] FSM без явного выхода — пользователь зависает (`userhours.py:117–250`)
6. [Блок 3] `make_mention()` дублируется в двух файлах (`auth.py:43`, `userhours.py:40`)
7. [Блок 3] Списки позиций в 5+ местах — риск рассинхронизации (`admin.py:31`, `superadmin.py:36` и др.)
8. [Блок 3] Импорт приватного символа `_parse_time` (`userhours.py:21`)
9. [Блок 4] Глобальный `_mg_*` state без asyncio.Lock (`userhours.py:106–110`)
10. [Блок 5] `requests` не в requirements.txt → `ImportError` на чистом окружении (`requirements.txt`)
11. [Блок 5] Отсутствует `.env.example` — нет шаблона для деплоя
12. [Блок 6] Нет тестов для `models.py` (get/set user_rate, snapshot) (`tests/test_models.py`)
13. [Блок 6] Нет тестов для `snapshot_user_rates_history()` (`tests/test_models.py`)
14. [Блок 6] Нет тестов для `get_section_range()` / `get_sheet_id_by_name()` (`tests/test_google_sheets.py`)

### Фаза 3: Улучшения 🟢 (можно после деплоя)
1. [Блок 1] Зарплатные данные в логах с именем (`admin.py:294`)
2. [Блок 2] Неполная очистка буфера при пустом списке фото (`userhours.py:396`)
3. [Блок 3] Три функции-монолита >100 строк (`auth.py:580`, `google_sheets.py:354`, `monthly_switch.py:100`)
4. [Блок 3] Inline список позиций внутри `process_approve()` (`auth.py:653`)
5. [Блок 4] Порядок роутеров — корректен, изменений не требует
6. [Блок 4] Circular imports — отсутствуют, изменений не требует
7. [Блок 4] Покрытие новых позиций — полное, изменений не требует
8. [Блок 5] `Pillow` в requirements не используется — удалить
9. [Блок 5] `.gitignore` — добавить `.pytest_cache/`, разобраться с `CLAUDE.md`
10. [Блок 6] `check_overlap` — добавить смешанный кейс (один диапазон через полночь, другой нет)

---

## Рекомендации

- Начать фиксы с Фазы 1 (критичные). Особое внимание: `_pending_custom_titles` (3) и `message_dept МОП` (5) — легко фиксируются за 5–10 минут
- После каждого фикса прогонять `pytest tests/`
- Коммитить пофиксово, не все сразу
- Перед деплоем добавить хотя бы тест `test_models.py` — снимок ставок (`snapshot_user_rates_history`) критичен для финансового расчёта
- Блок 5 (деплой): добавить `requests` в requirements и создать `.env.example` — занимает 5 минут, но предотвращает сбой при деплое
