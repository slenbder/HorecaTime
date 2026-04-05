import html


def make_mention(username: str | None, full_name: str) -> str:
    """
    Создаёт HTML-упоминание пользователя с экранированием full_name.

    Args:
        username: Telegram username (без @) или None
        full_name: Полное имя пользователя

    Returns:
        HTML-ссылка вида <a href="https://t.me/username">ФИО</a>
        или просто экранированное ФИО если username отсутствует
    """
    safe_name = html.escape(full_name)
    if username:
        return f'<a href="https://t.me/{username}">{safe_name}</a>'
    return safe_name


def mask_email(email: str) -> str:
    """
    Маскирует email для безопасного логирования.

    Args:
        email: Email адрес

    Returns:
        Маскированный email вида p***r@gmail.com
    """
    if '@' not in email:
        return email
    local, domain = email.split('@', 1)
    if len(local) <= 2:
        masked = local[0] + '***'
    else:
        masked = local[0] + '***' + local[-1]
    return f"{masked}@{domain}"
