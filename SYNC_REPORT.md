# Отчёт о синхронизации документации с кодом

**Дата:** 2026-04-02
**Коммит:** 0f0169c feat(superadmin): show full names in /rates_all
**Ветка:** fix/post-audit-clean

---

## КОНТЕКСТ

Код находится на коммите **0f0169c** — это состояние **до** audit-фиксов (Phase 1 и Phase 2).
Документация (HISTORY.md, CLAUDE.md) описывает эти фиксы как **завершённые**, что создаёт расхождения с кодом.
Все найденные расхождения — это ожидаемый backlog для фиксов, а не ошибки в документации.

---

## РАСХОЖДЕНИЯ НАЙДЕНЫ

### 1. `users` table: поле `hourly_rate` не удалено

**Документация:** TECH_REFERENCE.md строка 127 — «Поле `hourly_rate` удалено — ставки теперь в `user_rates`»
**Код:** [app/db/models.py:47](app/db/models.py#L47) — поле `hourly_rate REAL` присутствует в `CREATE TABLE`
**Проблема:** `save_user()` (строка 126) принимает и сохраняет `hourly_rate`, хотя по архитектуре все ставки должны быть только в `user_rates`
**Рекомендация:** Удалить поле из схемы и из `save_user()`. Это безопасно — `user_rates` уже используется для всех расчётов

---

### 2. `rates` table: лишнее поле `updated_at` в коде (vs docs)

**Документация:** TECH_REFERENCE.md строка 143-149 — схема `rates` без поля `updated_at`
**Код:** [app/db/models.py:73](app/db/models.py#L73) — `updated_at TEXT NOT NULL` присутствует
**Проблема:** Схема в документации неполная (не отражает реальную структуру)
**Рекомендация:** Добавить `updated_at` в схему TECH_REFERENCE.md — поле реально используется и нужно

---

### 3. `/message_dept` не включает МОП для admin_hall

**Документация:** CLAUDE.md строка 29 — «admin_hall управляет отделами: Зал + МОП»; HISTORY.md строки 188-192 — «Phase 1 Fix #2: admin_hall теперь отправляет рассылку в Зал + МОП»
**Код:** [app/bot/handlers/admin.py:395](app/bot/handlers/admin.py#L395)
```python
recipients = await get_users_by_department(DB_PATH, dept)
# dept = "Зал" — МОП НЕ включён
```
**Проблема:** `/rates` и `/set_rate` правильно включают МОП (строки 114-116, 160-162), но `/message_dept` — нет
**Рекомендация:** Добавить после строки 395:
```python
if dept == "Зал":
    recipients += await get_users_by_department(DB_PATH, "МОП")
```

---

### 4. `google_sheets.py`: две операции записи используют `USER_ENTERED`

**Документация:** CLAUDE.md строка 25 — «`value_input_option="RAW"` во всех операциях записи»; HISTORY.md строки 193-197 — «Phase 1 Fix #3: formula injection»
**Код:** [app/services/google_sheets.py:417](app/services/google_sheets.py#L417) и [строка 526](app/services/google_sheets.py#L526) — `value_input_option="USER_ENTERED"`
**Проблема:** Риск formula injection — пользователь может ввести `=HYPERLINK(...)` и оно выполнится
**Рекомендация:** Заменить оба вхождения на `value_input_option="RAW"`

---

### 5. `auth.py`: `_pending_custom_titles` — глобальный dict вместо FSM

**Документация:** HISTORY.md строки 182-186 — «Phase 1 Fix #1: `_pending_custom_titles` → FSM data, валидация 2-50 символов»
**Код:** [app/bot/handlers/auth.py:66](app/bot/handlers/auth.py#L66) — `_pending_custom_titles: dict[int, str] = {}`
**Проблема:** Данные теряются при перезапуске бота; нет валидации длины; риск гонки состояний
**Рекомендация:** Перенести в FSM data с валидацией длины строки

---

### 6. `_delayed_process_waiter` без try/except

**Документация:** HISTORY.md строки 203-206 — «Phase 1 Fix #5: обёрнут в try/except + state.clear() при ошибке»
**Код:** [app/bot/handlers/userhours.py:386-416](app/bot/handlers/userhours.py#L386-L416) — нет блока try/except
**Проблема:** Необработанное исключение в asyncio task молча «проглатывается» — пользователь не получит уведомление об ошибке
**Рекомендация:** Обернуть тело функции в try/except с уведомлением пользователю и `await state.clear()`

---

### 7. `html.escape()` не применяется к user inputs в userhours.py

**Документация:** HISTORY.md строки 198-201 — «Phase 1 Fix #4: html.escape() применён к user inputs в HTML-сообщениях»
**Код:** [app/bot/handlers/userhours.py](app/bot/handlers/userhours.py) — `html.escape()` не используется
**Проблема:** Риск HTML injection через комментарий к смене Раннера
**Рекомендация:** Применить `html.escape()` к комментарию и `full_name` перед вставкой в HTML-сообщения

---

### 8. `app/utils/text_utils.py` не существует

**Документация:** CLAUDE.md строка 41 — «`app/utils/text_utils.py` — `make_mention()`, `mask_email()`»; HISTORY.md строки 239-241 — «Phase 2 Fix #5, #6: извлечены в общий модуль»
**Код:** Файл [app/utils/text_utils.py](app/utils/text_utils.py) отсутствует. `make_mention()` определена в [app/bot/handlers/auth.py:43](app/bot/handlers/auth.py#L43). `mask_email()` нигде не найдена.
**Проблема:** Дублирование `make_mention()`, email в логах не маскируется
**Рекомендация:** Создать модуль, вынести обе функции, обновить импорты

---

### 9. Константы позиций не в `config.py`

**Документация:** TECH_REFERENCE.md строки 345-377 — «После Audit Phase 2 #8 все списки позиций консолидированы в константы в `config.py`»; перечислены `POSITIONS_WITH_EXTRA`, `DEPT_POSITIONS_ORDER`, `HALL_POSITIONS` и др.
**Код:** [config.py](config.py) — ни одной из этих констант нет. Они определены локально в [admin.py:39](app/bot/handlers/admin.py#L39) как `_POSITIONS_WITH_EXTRA` и в [superadmin.py:32](app/bot/handlers/superadmin.py#L32) — дублирование
**Рекомендация:** Перенести константы в `config.py`, убрать дублирование в хендлерах

---

### 10. Роли не проверяются в `approve_ah_callback` и `process_approve`

**Документация:** HISTORY.md строки 227-232 — «Phase 2 Fix #3, #4: проверки роли в callbacks»
**Код:** [app/bot/handlers/auth.py:479](app/bot/handlers/auth.py#L479) — `approve_ah_callback` не проверяет что вызывающий является admin_hall/superadmin/developer
**Проблема:** Любой зарегистрированный пользователь может нажать кнопку одобрения
**Рекомендация:** Добавить проверку `caller_id in (ADMIN_HALL_IDS + SUPERADMIN_IDS + [DEVELOPER_ID])`

---

## ДОКУМЕНТАЦИЯ АКТУАЛЬНА

✅ **Терминология** — отдел/позиция/должность используются правильно во всём коде. Путаницы в терминах не обнаружено.

✅ **Все 5 таблиц SQLite существуют** — `users`, `rates`, `user_rates`, `user_rates_history`, `rates_history` созданы в [models.py](app/db/models.py) и соответствуют документации (с учётом п.1 и п.2 выше)

✅ **admin_hall + МОП в `/rates` и `/set_rate`** — логика корректна: [admin.py:114-116](app/bot/handlers/admin.py#L114-L116) и [admin.py:160-162](app/bot/handlers/admin.py#L160-L162) правильно включают МОП для Зала

✅ **Позиции с повышенной ставкой** — `_POSITIONS_WITH_EXTRA = {"Бармен", "Барбэк", "Раннер"}` правильно определён в [admin.py:39](app/bot/handlers/admin.py#L39) и [superadmin.py:32](app/bot/handlers/superadmin.py#L32). Двухшаговый ввод ставки реализован (waiting_new_rate → waiting_extra_rate)

✅ **Ставки: расчёт через `user_rates`** — [userreports.py:201](app/bot/handlers/userreports.py#L201) использует `get_user_rate()`, `/hours_last` использует `get_user_rate_history()` с fallback на legacy `rates_history`. `get_rate()` для расчётов не используется.

✅ **Копирование ставки при апруве** — [auth.py:663](app/bot/handlers/auth.py#L663) вызывает `set_user_rate()` при одобрении нового сотрудника

✅ **Callback_data < 64 байт** — проверены все handlers. Самые длинные динамические: `dismiss_demote_only:{id}` (~30 байт), `approve_{tg_id}_{row}` (~22 байт). Все в норме.

✅ **Структура месячного листа** — MONTH_NAMES_RU, формат `"{Месяц} {Год}"`, колонки S/AJ/AK/AL/AM/AN соответствуют коду

✅ **APScheduler уведомления** — логика уведомлений admin_dept + superadmin через `set()` для дедупликации соответствует документации

✅ **`value_input_option="RAW"` частично** — [google_sheets.py:619](app/services/google_sheets.py#L619) использует RAW. Две строки с USER_ENTERED описаны в п.4.

---

## ИТОГ

⚠️ **Найдено 10 расхождений** — все являются известным backlog'ом для фиксов (Phase 1: пп. 3-7, Phase 2: пп. 8-10) плюс 2 расхождения docs↔код (пп. 1-2).

**Критичные для безопасности (фиксировать первыми):**
- П.4 — formula injection (USER_ENTERED → RAW)
- П.7 — HTML injection (нет html.escape)
- П.10 — авторизация в approve callbacks

**Критичные для надёжности:**
- П.3 — МОП не в рассылке admin_hall
- П.5 — _pending_custom_titles в глобальном dict
- П.6 — _delayed_process_waiter без try/except

**Документация требует правки:**
- П.2 — добавить `updated_at` в схему rates в TECH_REFERENCE.md

Код готов к применению фиксов из FINAL_AUDIT.md.

---

## СТАТУС (2026-04-05)

✅ **Все 10 расхождений устранены в ветке `fix/post-audit-clean`:**

- П.1 — `hourly_rate` удалено из схемы `users` (models.py)
- П.2 — `updated_at` добавлен в схему `rates` в TECH_REFERENCE.md
- П.3 — МОП включён в рассылку admin_hall (admin.py — `013b5c3`)
- П.4 — formula injection закрыт (`RAW` вместо `USER_ENTERED` — `67197ae`)
- П.5 — `_pending_custom_titles` → FSM data (`a05074b`)
- П.6 — `_delayed_process_waiter` обёрнут в try/except (`9da295c`)
- П.7 — `html.escape()` применён ко всем user inputs (`5adcb11`, `c0ac67b`)
- П.8 — `text_utils.py` создан, `make_mention()` и `mask_email()` вынесены (`5adcb11`)
- П.9 — константы позиций консолидированы в `config.py` (Phase 2 #8)
- П.10 — проверки ролей в `approve_ah_callback` и `process_approve` добавлены (Phase 2 #3,#4)
