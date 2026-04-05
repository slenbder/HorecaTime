# FSM States Map — userhours.py

Файл: `app/bot/handlers/userhours.py`  
FSM-классы: `app/bot/fsm/shift_states.py` → `ShiftStates`

---

## Определённые состояния (ShiftStates)

| State | Описание |
|-------|----------|
| `ShiftStates.waiting_shift_input` | Ожидание ввода смены (дата + время) — общий для всех позиций |
| `ShiftStates.waiting_ah_input` | Ожидание ввода доп. часов / тусовочных (Раннер + Бармен/Барбэк) |
| `ShiftStates.waiting_ah_comment` | Ожидание комментария к доп. часам (только Раннер) |

---

## Раннер Flow

- **Точка входа:** `/shift` command, `position == "Раннер"`
- **States:**
  1. `waiting_shift_input` — ожидание строки `ДД.ММ ЧЧ:ММ-ЧЧ:ММ` (строка 146)
  2. `waiting_ah_input` — ожидание числа доп. часов (0 или float) (строка 214)
  3. `waiting_ah_comment` — ожидание текста комментария к AH (строка 248) — только если AH > 0
- **Граф переходов:**
  ```
  /shift → waiting_shift_input
         → (parse OK) → waiting_ah_input
                       → (ah == 0) → _write_and_finish → state.clear()
                       → (ah > 0)  → waiting_ah_comment
                                   → _write_and_finish → state.clear()
         → (parse fail) → остаётся в waiting_shift_input (повтор)
  ```
- **Точки выхода (`state.clear()`):**
  - Строка 169 — неизвестная позиция (ранний выход из `cmd_shift`)
  - Строка 788 — `_write_and_finish`: `sheets_client is None`
  - Строка 796 — `_write_and_finish`: ошибка записи в таблицу
  - Строка 845 — `_write_and_finish`: успешная запись

---

## Официант Flow

- **Точка входа:** `/shift` command, `position == "Официант"`
- **States:**
  1. `waiting_shift_input` — ожидание текста/фото смены (строка 166)
  *(Официант не имеет дополнительных состояний — вся логика внутри шага 2)*
- **Граф переходов:**
  ```
  /shift → waiting_shift_input
         → (текст без фото) → _write_waiter_no_photo → state.clear()
         → (одиночное фото) → _send_waiter_report → state.clear()
         → (медиагруппа)    → _delayed_process_waiter (async task)
                              → (parse OK)   → _send_waiter_report → state.clear()
                              → (parse fail) → state.clear()
                              → (exception)  → state.clear()
  ```
- **Точки выхода (`state.clear()`):**
  - Строка 346 — `_write_waiter_no_photo`: `sheets_client is None`
  - Строка 355 — `_write_waiter_no_photo`: ошибка записи
  - Строка 362 — `_write_waiter_no_photo`: успешная запись (без фото)
  - Строка 420 — `_delayed_process_waiter`: ошибка парсинга caption
  - Строка 435 — `_delayed_process_waiter`: необработанное исключение
  - Строка 469 — `_send_waiter_report`: успешная запись (с фото)

---

## Бармен / Барбэк Flow

- **Точка входа:** `/shift` command, `position in {"Бармен", "Барбэк"}`
- **States:**
  1. `waiting_shift_input` — ожидание основной смены (строка 158)
  2. `waiting_ah_input` — ожидание тусовочных часов (диапазон или 0) (строка 550)
- **Граф переходов:**
  ```
  /shift → waiting_shift_input
         → (parse OK) → waiting_ah_input
                       → (0) → _write_and_finish_bar → state.clear()
                       → (диапазон OK, нет нахлёста) → _write_and_finish_bar → state.clear()
                       → (нахлёст / parse fail) → остаётся в waiting_ah_input (повтор)
         → (parse fail) → остаётся в waiting_shift_input (повтор)
  ```
- **Точки выхода (`state.clear()`):**
  - Строка 622 — `_write_and_finish_bar`: `sheets_client is None`
  - Строка 630 — `_write_and_finish_bar`: ошибка записи
  - Строка 677 — `_write_and_finish_bar`: успешная запись

---

## Simple-H Flow (Кухня, Хостесс, Менеджер, МОП)

Позиции: `KITCHEN_POSITIONS | HALL_SIMPLE_POSITIONS | MOP_POSITIONS`  
(Руководящий состав, Горячий цех, Холодный цех, Кондитерский цех, Заготовочный цех,  
Коренной цех, Грузчик, Закупщик, Хостесс, Менеджер, Клининг, Котломой)

- **Точка входа:** `/shift` command, `position in SIMPLE_H_POSITIONS`
- **States:**
  1. `waiting_shift_input` — ожидание одной или нескольких смен (строка 152)
  *(нет дополнительных состояний — запись происходит сразу)*
- **Граф переходов:**
  ```
  /shift → waiting_shift_input
         → (все строки parse OK) → _process_simple_h_shifts → state.clear()
         → (любая строка fail)   → остаётся в waiting_shift_input (повтор)
  ```
- **Точки выхода (`state.clear()`):**
  - Строка 707 — `_process_simple_h_shifts`: `sheets_client is None`
  - Строка 733 — `_process_simple_h_shifts`: ошибка записи одной из смен
  - Строка 763 — `_process_simple_h_shifts`: успешная запись всех смен

---

## Все вызовы `state.set_state()` (точки входа в состояния)

| Строка | State | Позиция / контекст |
|--------|-------|--------------------|
| 146 | `ShiftStates.waiting_shift_input` | Раннер |
| 152 | `ShiftStates.waiting_shift_input` | SIMPLE_H_POSITIONS |
| 158 | `ShiftStates.waiting_shift_input` | BAR_POSITIONS (Бармен/Барбэк) |
| 166 | `ShiftStates.waiting_shift_input` | Официант |
| 214 | `ShiftStates.waiting_ah_input` | Раннер → после парсинга основной смены |
| 248 | `ShiftStates.waiting_ah_comment` | Раннер → если AH > 0 |
| 550 | `ShiftStates.waiting_ah_input` | Бармен/Барбэк → после парсинга основной смены |

---

## Все вызовы `state.clear()` (точки выхода из FSM)

| Строка | Функция | Причина |
|--------|---------|---------|
| 169 | `cmd_shift` | Неизвестная позиция |
| 346 | `_write_waiter_no_photo` | `sheets_client is None` |
| 355 | `_write_waiter_no_photo` | Ошибка записи |
| 362 | `_write_waiter_no_photo` | Успех (без фото) |
| 420 | `_delayed_process_waiter` | Ошибка парсинга caption медиагруппы |
| 435 | `_delayed_process_waiter` | Необработанное исключение |
| 469 | `_send_waiter_report` | Успех (с фото) |
| 622 | `_write_and_finish_bar` | `sheets_client is None` |
| 630 | `_write_and_finish_bar` | Ошибка записи |
| 677 | `_write_and_finish_bar` | Успех |
| 707 | `_process_simple_h_shifts` | `sheets_client is None` |
| 733 | `_process_simple_h_shifts` | Ошибка записи одной смены |
| 763 | `_process_simple_h_shifts` | Успех |
| 788 | `_write_and_finish` | `sheets_client is None` |
| 796 | `_write_and_finish` | Ошибка записи |
| 845 | `_write_and_finish` | Успех (Раннер) |

---

## Handler ↔ State соответствие

| Handler | State-фильтр | Охватывает позиции |
|---------|--------------|--------------------|
| `cmd_shift` (строка 114) | `Command("shift")` (без state) | Точка входа для всех |
| `process_shift_input` (строка 176) | `ShiftStates.waiting_shift_input` | Раннер, Официант, Бармен, Барбэк, Simple-H |
| `process_ah_input` (строка 221) | `ShiftStates.waiting_ah_input` | Раннер, Бармен, Барбэк |
| `process_ah_comment` (строка 255) | `ShiftStates.waiting_ah_comment` | Раннер (только) |

Все определённые состояния (`waiting_shift_input`, `waiting_ah_input`, `waiting_ah_comment`) покрыты соответствующими handlers. ✅

---

## Общая статистика

| Метрика | Значение |
|---------|----------|
| Всего уникальных состояний в `ShiftStates` | **3** |
| Всего вызовов `state.set_state()` | **7** |
| Всего вызовов `state.clear()` | **16** |
| Всего FSM-flows | **4** (Раннер, Официант, Бармен/Барбэк, Simple-H) |
| Состояния без handler | **0** — все покрыты |

---

## Наблюдения для Bug #11 (FSM /cancel + таймаут)

1. **Все потоки начинаются с `waiting_shift_input`** — `/cancel` должен работать из любого состояния.
2. **Официант не имеет промежуточных состояний** — если пользователь в `waiting_shift_input` и медиагруппа уже в обработке (`_delayed_process_waiter`), `/cancel` должен также инвалидировать `_mg_context[mgid]`.
3. **`waiting_ah_comment` эксклюзивен для Раннера** — если пользователь отменяет в этом состоянии, нужно очищать и данные смены.
4. **16 вызовов `state.clear()` разбросаны по 7 функциям** — после добавления `/cancel` нужно убедиться, что двойной вызов `state.clear()` безопасен (он безопасен в aiogram 3).
5. **Нет timeout-защиты** — пользователь может зависнуть в любом из 3 состояний навсегда.
