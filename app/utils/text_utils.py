import html


def make_mention(username: str | None, full_name: str) -> str:
    """Возвращает кликабельный HTML-тег упоминания пользователя.

    Args:
        username: Telegram-ник без @, или None если ника нет.
        full_name: Полное имя пользователя (будет экранировано для HTML).

    Returns:
        HTML-ссылка на профиль если есть ник, иначе экранированное ФИО.
    """
    escaped = html.escape(full_name)
    if username:
        return f'<a href="https://t.me/{username}">{escaped}</a>'
    return escaped
