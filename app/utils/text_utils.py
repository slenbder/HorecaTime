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


def format_alert(
    operation: str,
    error: Exception | str | None = None,
    tg_id: int | None = None,
    position: str | None = None,
    department: str | None = None,
    date: str | None = None,
    extra: str | None = None,
) -> str:
    """Форматирует алёрт для Telegram с контекстом операции."""
    lines = [f"🔴 [{operation}]"]
    if tg_id:
        lines.append(f"👤 tg_id: {tg_id}")
    if position or department:
        parts = [p for p in (position, department) if p]
        lines.append(f"📋 {' | '.join(parts)}")
    if date:
        lines.append(f"📅 {date}")
    if error:
        if isinstance(error, Exception):
            lines.append(f"❌ {type(error).__name__}: {error}")
        else:
            lines.append(f"❌ {error}")
    if extra:
        lines.append(f"ℹ️ {extra}")
    return "\n".join(lines)
