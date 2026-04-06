# HorecaTime — Руководство по деплою на VPS

## 1. Предварительные требования

### Локальная машина
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- Аккаунт на [Docker Hub](https://hub.docker.com/) (username: `slenbder`)
- Git

### VPS (Ubuntu 22.04)
- Docker Engine
- Docker Compose v2

---

## 2. Сборка и публикация образа (локально)

```bash
# Авторизация в Docker Hub
docker login

# Сборка образа из корня проекта
docker build -t slenbder/horecatime:latest .

# Публикация образа
docker push slenbder/horecatime:latest
```

Ожидаемый вывод после push:
```
The push refers to repository [docker.io/slenbder/horecatime]
latest: digest: sha256:... size: 1234
```

---

## 3. Подготовка VPS

### Установка Docker

```bash
# Обновление пакетов
sudo apt update && sudo apt upgrade -y

# Установка зависимостей
sudo apt install -y ca-certificates curl gnupg

# Добавление GPG ключа Docker
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | \
    sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg

# Добавление репозитория Docker
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
    https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | \
    sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Установка Docker
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin

# Добавление текущего пользователя в группу docker
sudo usermod -aG docker $USER
newgrp docker
```

### Создание структуры директорий

```bash
sudo mkdir -p /opt/horecatime/data
sudo mkdir -p /opt/horecatime/logs
sudo chown -R $USER:$USER /opt/horecatime
```

### Установка прав доступа на конфигурационные файлы

```bash
chmod 600 /opt/horecatime/.env
chmod 600 /opt/horecatime/credentials.json
```

---

## 4. Копирование конфигурационных файлов на VPS

Выполняется с локальной машины (замените `user` и `your-vps-ip`):

```bash
# docker-compose.yml
scp docker/docker-compose.yml user@your-vps-ip:/opt/horecatime/docker-compose.yml

# Файл с секретами
scp .env user@your-vps-ip:/opt/horecatime/.env

# Credentials Google
scp credentials.json user@your-vps-ip:/opt/horecatime/credentials.json
```

---

## 5. Запуск бота

```bash
# Перейти в рабочую директорию на VPS
cd /opt/horecatime

# Загрузить актуальный образ
docker compose pull

# Запустить в фоновом режиме
docker compose up -d
```

Проверка запуска:

```bash
# Список запущенных контейнеров
docker ps

# Ожидаемый вывод:
# CONTAINER ID   IMAGE                        STATUS          PORTS
# abc123...      slenbder/horecatime:latest   Up 2 minutes

# Логи запуска
docker logs horecatime-bot
```

---

## 6. Обновление бота

```bash
cd /opt/horecatime

# Остановить контейнер
docker compose down

# Загрузить новый образ
docker compose pull

# Запустить снова
docker compose up -d
```

---

## 7. Мониторинг

```bash
# Логи контейнера (последние 100 строк)
docker logs horecatime-bot --tail 100

# Логи в реальном времени
docker logs horecatime-bot -f

# Логи приложения
tail -f /opt/horecatime/logs/app.log

# Статус контейнера
docker ps

# Статус healthcheck
docker inspect --format='{{.State.Health.Status}}' horecatime-bot
```

---

## 8. Бэкапы

### Создание бэкапа базы данных

```bash
# Создать директорию для бэкапов
mkdir -p /opt/horecatime/backups

# Бэкап с временной меткой
cp /opt/horecatime/data/bot.db \
   /opt/horecatime/backups/bot_$(date +%Y%m%d_%H%M%S).db
```

### Восстановление из бэкапа

```bash
# Остановить бота
docker compose down

# Восстановить базу данных (замените имя файла)
cp /opt/horecatime/backups/bot_20260101_120000.db \
   /opt/horecatime/data/bot.db

# Запустить снова
docker compose up -d
```

---

## 9. Troubleshooting

### Бот не запускается

```bash
# Смотреть логи
docker logs horecatime-bot

# Проверить статус контейнера
docker ps -a
```

Частые причины: неверный токен в `.env`, отсутствует переменная окружения.

### Ошибка Google Sheets

```bash
# Проверить наличие файла
ls -la /opt/horecatime/credentials.json

# Проверить права доступа (должен быть 600)
stat /opt/horecatime/credentials.json
```

Частые причины: файл не скопирован, истёк срок действия токена, неверный service account.

### Контейнер постоянно перезапускается

```bash
# Посмотреть историю перезапусков
docker inspect horecatime-bot | grep -A5 RestartCount

# Детальные логи
docker logs horecatime-bot --tail 50
```

Частые причины: ошибка в коде при старте, healthcheck не проходит, нет доступа к интернету.

---

## 10. Структура файлов на VPS

```
/opt/horecatime/
├── .env                  # Переменные окружения (токены, ключи)
├── credentials.json      # Google service account credentials
├── docker-compose.yml    # Конфигурация контейнера
├── data/
│   └── bot.db            # База данных SQLite
├── logs/
│   └── app.log           # Логи приложения
└── backups/              # Бэкапы базы данных
```
