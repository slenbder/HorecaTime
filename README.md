<div align="center">

# 🕐 HorecaTime

**Telegram-бот для учёта рабочего времени в ресторане**

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![aiogram](https://img.shields.io/badge/aiogram-3.13-2CA5E0?style=flat-square&logo=telegram&logoColor=white)](https://aiogram.dev)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![Tests](https://img.shields.io/badge/Tests-122%20passing-22c55e?style=flat-square&logo=pytest&logoColor=white)](https://pytest.org)
[![Status](https://img.shields.io/badge/Status-Beta-f59e0b?style=flat-square)](https://github.com/slenbder/HorecaTime)

*Разработано для HoReCa-сектора. Находится в бета-тестировании.*

</div>

---

## О проекте

**HorecaTime** автоматизирует учёт рабочих смен, расчёт часов и начисление зарплаты для персонала ресторана прямо в Telegram. Никаких сторонних приложений — только бот и привычный Google Sheets как база данных.

Сотрудник вносит смену за 30 секунд. Администратор одобряет одной кнопкой. Бухгалтер смотрит итоги в таблице.

---

## Возможности

### Для сотрудников
- 📅 Внесение рабочих смен (дата + время) прямо в Telegram
- 📸 Отправка фото карт лояльности и наполняемости чеков
- 💰 Просмотр заработка за первую половину, вторую половину и весь месяц
- 📊 Ссылка на свой блок в графике Google Sheets

### Для администраторов
- ✅ Одобрение/отклонение смен с уведомлением сотрудника
- 👥 Управление составом отдела (приём, повышение, увольнение)
- 💳 Учёт карт лояльности и наполняемости чеков с накопительным пулом
- 📢 Рассылка сообщений по отделу
- 📄 Экспорт графика в PDF одной командой
- 💵 Установка персональных ставок сотрудникам

### Для суперадминов
- 🔄 Переключение месяца (ручное или автоматическое 1-го числа)
- 📋 Просмотр всех ставок по всем отделам
- 🛠 Ручное восстановление записей сотрудников
- 💬 Прямой контакт с разработчиком из интерфейса бота

---

## Архитектура

```
Telegram API
     │
     ▼
aiogram 3 (handlers / FSM)
     │
     ├── SQLite ──────── FSM-состояния, роли, персональные ставки
     │
     └── Google Sheets ─ Единственный источник данных сотрудников и смен
                         (Техлист + месячные листы)
```

**Google Sheets — source of truth.** SQLite хранит только то, чему не место в таблице: состояния FSM, кеш ролей и ставки.

### Структура отделов

| Отдел | Позиции |
|-------|---------|
| **Зал** | Менеджер, Официант, Раннер, Хостесс |
| **Бар** | Бармен, Барбэк |
| **Кухня** | Руководящий состав, Горячий/Холодный/Кондитерский/Заготовочный/Коренной цех, Грузчик, Закупщик |
| **МОП** | Клининг, Котломой |

---

## Стек технологий

| Компонент | Технология |
|-----------|-----------|
| Язык | Python 3.11+ |
| Telegram-фреймворк | aiogram 3.13.1 |
| Google Sheets | gspread 6.1.2 + oauth2client |
| База данных | aiosqlite 0.20.0 (SQLite) |
| Планировщик | APScheduler 3.10.4 |
| Контейнеризация | Docker + Docker Compose |
| Тестирование | pytest (122 тестов) |

---

## Быстрый старт

### Требования
- Docker и Docker Compose
- Google Cloud проект с сервисным аккаунтом и доступом к Sheets API
- Telegram Bot Token ([@BotFather](https://t.me/BotFather))

### Установка

```bash
git clone https://github.com/slenbder/HorecaTime.git
cd HorecaTime
cp .env.example .env
```

Заполни `.env`:

```env
BOT_TOKEN=your_telegram_bot_token
DEVELOPER_ID=your_telegram_id
SUPERADMIN_IDS=id1,id2
SPREADSHEET_ID=your_google_spreadsheet_id
GOOGLE_CREDENTIALS_PATH=credentials.json
DB_PATH=data/bot.db
```

Положи `credentials.json` (Google сервисный аккаунт) в корень проекта.

```bash
docker-compose up -d
```

### Деплой на VPS

```bash
./deploy.sh
```

Скрипт выполняет `git pull` на сервере, пересобирает и перезапускает контейнер.

---

## Структура проекта

```
HorecaTime/
├── app/
│   ├── bot/
│   │   ├── handlers/       # aiogram handlers (auth, userhours, admin, superadmin)
│   │   ├── fsm/            # FSM states
│   │   ├── keyboards/      # Inline и Reply клавиатуры
│   │   └── commands.py     # Команды бота по ролям
│   ├── db/
│   │   └── models.py       # SQLite CRUD операции
│   ├── services/
│   │   ├── google_sheets.py  # Работа с Google Sheets API
│   │   └── pdfservice.py     # Экспорт PDF
│   ├── scheduler/
│   │   └── monthly_switch.py # Автопереключение месяца
│   └── utils/
│       └── text_utils.py     # make_mention(), mask_email()
├── tests/                  # 122 pytest-теста
├── docs/                   # Внутренняя документация проекта
├── config.py               # Константы, списки позиций
├── main.py                 # Точка входа
├── Dockerfile
├── docker-compose.yml
└── .env.example
```

---

## Тестирование

```bash
pytest tests/ -v
```

```
122 passed in X.XXs
```

Покрыты: парсинг времени, расчёт зарплаты, CRUD ставок, переключение месяца, формулы Google Sheets, FSM-сценарии.

---

## Роли и права

```
developer      — полный доступ, разработчик
superadmin     — управление всем рестораном
admin_hall     — Зал + МОП
admin_bar      — Бар
admin_kitchen  — Кухня
user           — внесение своих смен, просмотр своих часов
```

Роли хранятся в SQLite. Суперадмины и разработчик определяются через `config.py` (не через БД).

---

## Особенности реализации

- **Персональные ставки** — у каждого сотрудника своя ставка, нет шаблонов по позициям
- **Позиции с повышенной ставкой** — Раннер (выходные), Бармен/Барбэк (мероприятия)
- **Фантомный сотрудник** — накопительный пул наполняемости чеков для официантов
- **Автопереключение месяца** — 1-го числа в 18:00 МСК, с предупреждением в 12:00

---

## Лицензия

Проект разрабатывается как частное коммерческое решение для HoReCa-сектора.  
© 2026 slenbder. All rights reserved.

---

<div align="center">

Разработано с ☕ для тех, кто работает пока все отдыхают

</div>
