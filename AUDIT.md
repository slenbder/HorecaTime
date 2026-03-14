# Аудит кода HorecaTime — 14.03.2026

Полный аудит перед переходом к Этапу 5. Проверены все файлы проекта.

---

## 🔴 КРИТИЧНО — исправить до следующего этапа

---

### 1. `dismiss_confirm_handler` — нет FSM-фильтра и нет проверки роли

**Файл:** `app/bot/handlers/auth.py`, строка 930

```python
@auth_router.callback_query(F.data.startswith("dismiss_confirm:"))
async def dismiss_confirm_handler(callback: CallbackQuery, state: FSMContext):
    target_id = int(callback.data.split(":")[1])
    ...
    sheets_client.dismiss_employee(target_id)
```

**Проблема:** Хендлер срабатывает для любого пользователя с правильным `callback_data`. Нет ни FSM-фильтра `AuthStates.waiting_dismiss_confirm`, ни проверки `tg_id in SUPERADMIN_IDS`. Предыдущий шаг `dismiss_select` (строка 899) защищён FSM-фильтром, а финальный — нет. Злоумышленник со знанием чужого Telegram ID может уволить любого сотрудника.

**Исправление:** добавить фильтр `AuthStates.waiting_dismiss_confirm` к декоратору:
```python
@auth_router.callback_query(AuthStates.waiting_dismiss_confirm, F.data.startswith("dismiss_confirm:"))
```

---

### 2. Дублирующийся `approve_ah_callback` — мёртвый код в userhours.py

**Файлы:**
- `app/bot/handlers/auth.py`, строка 522
- `app/bot/handlers/userhours.py`, строка 414

**Проблема:** Два хендлера зарегистрированы на `approve_ah:`. В `main.py` `auth_router` включён первым — хендлер из `userhours.py` **никогда не выполняется**. При этом в мёртвом коде (`userhours.py`, строка 435) отсутствует `try/except`:

```python
# userhours.py:435 — нет try/except, упадёт при некорректной дате
day_s, month_s, year_s = date_str.split(".")
day, month, year = int(day_s), int(month_s), 2000 + int(year_s)
```

Мёртвый код скрывает скрытый баг и вводит в заблуждение при отладке.

**Исправление:** удалить `approve_ah_callback` из `userhours.py` целиком (строки 414–479).

---

### 3. `check_overlap` — потенциальная бесконечная петля

**Файл:** `app/services/timeparsing.py`, строки 91–101

```python
def expand(s: float, e: float) -> set:
    t = s
    if s == e:
        return slots
    while True:
        slots.add(t)
        t = (t + 0.5) % 24
        if t == e % 24:   # ← может никогда не стать True
            break
```

**Проблема:** Если пользователь введёт время с минутами не кратными 30 (например `10:20-18:20`), то `t = 10.333...` (float). Дробь `1/3` не представима точно в IEEE 754 — накопление ошибок делает `t == e % 24` недостижимым. Бот зависнет на входящем сообщении. `_parse_time` принимает любые минуты 0–59, не только кратные 30.

**Исправление:** заменить точное сравнение на приближённое:
```python
if abs(t - e % 24) < 0.001:
    break
```
Или добавить счётчик итераций с лимитом ≤ 48.

---

### 4. Race condition медиагруппы — дублирование ошибок при неудачном парсинге

**Файл:** `app/bot/handlers/userhours.py`, строки 251–261

```python
if mgid not in _mg_photos:
    text = (message.caption or "").strip()
    result = parse_shift(text, "Официант")
    if result is None:
        await message.answer("❌ Не удалось распознать формат смены.")
        return   # ← _mg_photos[mgid] НЕ создаётся!

_mg_photos[mgid].append(photo_file_id)
```

**Проблема:** Если caption первого фото не парсится — `_mg_photos[mgid]` не создаётся. Каждое следующее фото из той же медиагруппы (2-е, 3-е...) снова попадает в ветку `if mgid not in _mg_photos`, парсит пустую caption → `None` → пользователь получает N сообщений об ошибке вместо одного.

**Исправление:** при ошибке парсинга сохранить sentinel-значение:
```python
if result is None:
    await message.answer("❌ Не удалось распознать формат смены.")
    _mg_photos[mgid] = None   # sentinel: группа помечена как ошибочная
    return

if _mg_photos.get(mgid) is None:
    return   # последующие фото ошибочной группы игнорируем
```

---

## 🟡 ВАЖНО — исправить до деплоя

---

### 5. `add_or_update_pending_user` — 6 отдельных API-вызовов вместо одного

**Файл:** `app/services/google_sheets.py`, строки 179–184

```python
ws.update_cell(row_idx, COL_NICKNAME, nickname)
ws.update_cell(row_idx, COL_TG_NAME, tg_name)
ws.update_cell(row_idx, COL_FIO_FROM_USER, fio_from_user)
ws.update_cell(row_idx, COL_LAST_SEEN_AT, str(now_unix))
ws.update_cell(row_idx, COL_DEPARTMENT, department)
ws.update_cell(row_idx, COL_POSITION, position)
```

**Проблема:** Повторная регистрация порождает 6 последовательных HTTP-запросов к Google Sheets API.

**Исправление:** заменить на один batch-запрос:
```python
ws.update(
    f"B{row_idx}:L{row_idx}",
    [[nickname, tg_name, "", fio_from_user, "", str(now_unix), "", department, position]],
    value_input_option="USER_ENTERED",
)
```

---

### 6. `process_approve_admin` — ФИО администратора не сохраняется в SQLite

**Файл:** `app/bot/handlers/auth.py`, строки 460–465

```python
RolesCacheService.update_user_role(
    telegram_id=user_tg_id,
    full_name="",   # ← ФИО теряется
    role=role,
    department=dept,
)
```

**Проблема:** При одобрении заявки администратора его `full_name` остаётся пустой строкой в SQLite. Начиная с Этапа 5, когда отчёты и уведомления будут использовать `full_name` из кеша, все администраторы будут безымянными.

**Исправление:** получить ФИО из Техлиста при approve:
```python
user_info = sheets_client.get_user_from_techlist(user_tg_id)
full_name = user_info.get("fio_from_user", "") if user_info else ""
RolesCacheService.update_user_role(..., full_name=full_name, ...)
```

---

### 7. `cmd_start` — авторизованный пользователь не получает главное меню

**Файл:** `app/bot/handlers/auth.py`, строки 138–147

```python
if is_approved:
    await message.answer(
        "Ты уже авторизован в системе ✅\n"
        "Скоро здесь появится главное меню..."
    )
    # ← нет reply_markup=main_menu_keyboard(role)
```

**Проблема:** При /start авторизованный пользователь не получает `main_menu_keyboard`. Кнопка «Написать разработчику» недоступна. Особенно критично после возвращения уволенного сотрудника — при /start получит пустой ответ без меню.

**Исправление:** добавить клавиатуру в ответ, используя роль из кеша.

---

### 8. `cmd_shift` — молчаливый `return` для не-user ролей

**Файл:** `app/bot/handlers/userhours.py`, строка 89

```python
if not user_data or user_data.get("role") != "user":
    return   # ← никакого ответа пользователю
```

**Проблема:** Если администратор (роль `admin_hall`) нажмёт `/shift` — команда проглатывается без ответа. По документации, администраторы тоже вносят смены. Пользователь не понимает, почему команда не работает.

**Исправление:** либо расширить список разрешённых ролей (если admin должны вносить смены), либо отвечать явным сообщением:
```python
await message.answer("❌ Команда недоступна для вашей роли.")
return
```

---

### 9. `approve_ah` — нет защиты от двойного нажатия

**Файл:** `app/bot/handlers/auth.py`, строки 565–614

**Проблема:** Отчёт отправляется всем `admin_hall + superadmin`. Если два администратора одновременно нажмут разные кнопки `[1]` и `[2]`, оба вызовут `write_shift()`. Последний запрос перезапишет результат первого. Сообщение отредактируется дважды. Официант получит два уведомления.

**Исправление:** перед записью проверить, не была ли кнопка уже обработана:
```python
original_text = callback.message.text or ""
if "✅ Одобрено" in original_text:
    await callback.answer("Уже обработано другим администратором.")
    return
```

---

### 10. `config.py` — нет валидации обязательных переменных окружения

**Файл:** `config.py`, строки 7 и 16

```python
BOT_TOKEN = os.getenv("BOT_TOKEN")       # может быть None
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")  # может быть None
```

**Проблема:** При запуске без `.env` бот падает с неинформативным `TypeError: token must be a string` внутри aiogram, вместо понятного сообщения об ошибке конфигурации.

**Исправление:**
```python
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан в .env")

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
if not SPREADSHEET_ID:
    raise ValueError("SPREADSHEET_ID не задан в .env")
```

---

### 11. Локальные импорты приватных функций внутри `_process_bar_ah_input`

**Файл:** `app/bot/handlers/userhours.py`, строки 515 и 554

```python
from app.services.timeparsing import _parse_time   # приватная функция!
...
from app.services.timeparsing import round_to_half
```

**Проблема:** Импорт функции с `_`-prefix нарушает инкапсуляцию модуля. Оба импорта должны быть на уровне файла (строка 18 уже содержит импорт из timeparsing).

**Исправление:** добавить в строку 18:
```python
from app.services.timeparsing import parse_shift, check_overlap, _parse_time, round_to_half
```

---

### 12. `get_employees_by_dept` — нет фильтрации по статусу одобрения

**Файл:** `app/services/google_sheets.py`, строки 532–548

**Проблема:** Метод возвращает всех сотрудников отдела включая кандидатов в ожидании одобрения (у которых `in_staff_table != "ДА"`). В `auth.py` есть вторичный фильтр по SQLite, который пропускает неодобренных. Работает корректно, но семантика метода вводит в заблуждение.

**Исправление:** добавить фильтр в метод:
```python
approved = str(row[COL_IN_STAFF_TABLE - 1]).strip().upper() == "ДА"
if not approved:
    continue
```

---

### 13. `user_exists_in_techlist` vs `get_user_by_telegram_id` — несоответствие при обходе строк

**Файл:** `app/services/google_sheets.py`

- `user_exists_in_techlist` (строка 281): `for row in all_values[1:]` — пропускает заголовок
- `get_user_by_telegram_id` (строка 115): `for row_idx, row in enumerate(all_values, start=1)` — не пропускает

Если заголовок Техлиста содержит значение похожее на числовой ID (ошибка в таблице), методы дадут разные результаты. Стоит привести к единому стилю.

---

## 🟢 ЖЕЛАТЕЛЬНО — улучшение качества кода

---

### 14. Лишние алиасы `SUPERADMINS`, `ADMIN_HALL` и др.

**Файл:** `app/bot/handlers/auth.py`, строки 40–44

```python
SUPERADMINS = SUPERADMIN_IDS   # бесполезный алиас
ADMIN_HALL = ADMIN_HALL_IDS
...
```

В одном файле смешано: строки 91, 814 используют `SUPERADMIN_IDS`, строки 314–398 — `SUPERADMINS`. Удалить алиасы, везде использовать имена из `config.py`.

---

### 15. Смешение стилей именования логгера

- `app/bot/handlers/auth.py:38`: `logging.getLogger(__name__)` — правильно
- `app/bot/handlers/userhours.py:22`: `logging.getLogger("app")` — теряется контекст модуля

Привести к единому стилю: `logging.getLogger(__name__)` везде.

---

### 16. Логирование Telegram ID суперадминов в module scope

**Файл:** `app/bot/handlers/auth.py`, строки 59–62

```python
logger.info(f"Загружены SUPERADMINS: {SUPERADMINS}")
```

Выполняется при импорте модуля. В лог попадают Telegram ID (персональные данные). Понизить до `logger.debug(...)`.

---

### 17. Переменная `l` — визуальная путаница с `1`

**Файл:** `app/bot/handlers/userhours.py`, строка 644

```python
lines = [l.strip() for l in (message.text or "").splitlines() if l.strip()]
```

`l` неотличима от `1` в большинстве шрифтов. Переименовать в `line`.

---

### 18. `_split_hm` — нет валидации на уровне функции

**Файл:** `app/services/timeparsing.py`, строки 59–60

```python
if len(raw) == 4:
    return int(raw[:2]), int(raw[2:])  # "2599" → (25, 99) без ошибки
```

Проверка диапазонов есть в `_parse_time` (строка 75–78), но функция `_split_hm` возвращает невалидный кортеж вместо `None`. Мелкая архитектурная несоответствие.

---

### 19. `save_user` — `datetime.now()` без таймзоны

**Файл:** `app/db/models.py`, строка 52

```python
datetime.now().isoformat()   # локальное время без timezone
```

`google_sheets.py` использует `ZoneInfo("Europe/Moscow")`. Несоответствие может привести к проблемам при сравнении дат в будущих этапах (отчёты, переключение месяца).

**Исправление:** `datetime.now(ZoneInfo("Europe/Moscow")).isoformat()`

---

### 20. `write_shift` — первое совпадение дня в строке 3

**Файл:** `app/services/google_sheets.py`, строки 496–502

```python
if int(str(cell).strip()) == day:
    day_col = j
    break
```

Ищет **первый** столбец со значением дня. Данные хранятся в двух диапазонах: D5:R60 и T5:AI60 (с пропуском колонки S). Если число встречается в обоих диапазонах, смена запишется в первый найденный столбец. Стоит ограничить диапазон поиска допустимыми колонками.

---

## Сводная таблица

| # | Файл | Строки | Приоритет | Краткое описание |
|---|------|--------|-----------|-----------------|
| 1 | auth.py | 930 | 🔴 | dismiss_confirm без FSM/роли — уязвимость |
| 2 | auth.py + userhours.py | 522, 414 | 🔴 | Дублирующийся approve_ah_callback |
| 3 | timeparsing.py | 91–101 | 🔴 | Бесконечная петля в check_overlap |
| 4 | userhours.py | 251–261 | 🔴 | Race condition медиагруппы при ошибке парсинга |
| 5 | google_sheets.py | 179–184 | 🟡 | 6 API-вызовов вместо одного batch |
| 6 | auth.py | 460–465 | 🟡 | Пустое ФИО при approve_admin |
| 7 | auth.py | 138–147 | 🟡 | Нет main_menu при /start для авторизованных |
| 8 | userhours.py | 89 | 🟡 | Молчаливый return для admin/superadmin при /shift |
| 9 | auth.py | 565–614 | 🟡 | Нет защиты от двойного нажатия approve_ah |
| 10 | config.py | 7, 16 | 🟡 | Нет валидации BOT_TOKEN / SPREADSHEET_ID |
| 11 | userhours.py | 515, 554 | 🟡 | Локальные импорты приватных функций |
| 12 | google_sheets.py | 532–548 | 🟡 | get_employees_by_dept без фильтра по статусу |
| 13 | google_sheets.py | 115, 281 | 🟡 | Несоответствие обхода строк в двух методах |
| 14 | auth.py | 40–44 | 🟢 | Лишние алиасы SUPERADMINS/ADMIN_HALL/etc |
| 15 | userhours.py | 22 | 🟢 | getLogger("app") вместо __name__ |
| 16 | auth.py | 59–62 | 🟢 | Логирование ID суперадминов в module scope |
| 17 | userhours.py | 644 | 🟢 | Переменная l — путаница с 1 |
| 18 | timeparsing.py | 59–60 | 🟢 | _split_hm без валидации диапазонов |
| 19 | db/models.py | 52 | 🟢 | datetime.now() без timezone |
| 20 | google_sheets.py | 496–502 | 🟢 | Поиск дня по первому совпадению в row 3 |

---

*Аудит проведён: 14.03.2026. Следующий этап: Этап 5 (отчёты по часам).*
