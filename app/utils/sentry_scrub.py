"""Очистка событий Sentry от персональных данных (ФИО, ввод пользователя, username).

Чистая функция без импорта sentry_sdk: подключается как before_send.
"""

_DROPPED_KEYS = ("user", "request", "extra", "breadcrumbs")


def scrub_event(event, hint=None):
    """
    Убирает из события Sentry всё, что может содержать данные пользователей:
      * logentry.params (аргументы лога); шаблон message остаётся;
      * vars (локальные переменные) во всех фреймах exception.values;
      * user, request, extra, breadcrumbs.
    Тип исключения, модуль, имена функций и номера строк остаются.
    Отсутствие любых ключей и пустой event не приводят к ошибке.
    """
    if not isinstance(event, dict):
        return event

    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        logentry.pop("params", None)

    exception = event.get("exception")
    values = exception.get("values") if isinstance(exception, dict) else None
    for value in values or []:
        stacktrace = value.get("stacktrace") if isinstance(value, dict) else None
        frames = stacktrace.get("frames") if isinstance(stacktrace, dict) else None
        for frame in frames or []:
            if isinstance(frame, dict):
                frame.pop("vars", None)

    for key in _DROPPED_KEYS:
        event.pop(key, None)

    return event
