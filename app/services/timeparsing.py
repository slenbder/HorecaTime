import logging
import re
import datetime

logger = logging.getLogger(__name__)

# Паттерн даты: 1.1 / 01.01 / 1.01.25 / 01.01.25
_DATE_RE = re.compile(
    r'^(\d{1,2})\.(\d{1,2})(?:\.(\d{2}))?$'
)

# Паттерн времени: 1000-1800 / 10-18 / 10.00-18.00 / 10:00-18:00
# Группы: (часть_до_разделителя, минуты_опц) для start и end
_TIME_RE = re.compile(
    r'^(\d{1,4})(?:[.:](\d{2}))?-(\d{1,4})(?:[.:](\d{2}))?$'
)


def round_to_half(value: float) -> float:
    """Округление до ближайших 0.5."""
    return round(value * 2) / 2


def is_weekend(day: int, month: int, year: int) -> bool:
    """True если дата — пятница (4), суббота (5) или воскресенье (6)."""
    try:
        weekday = datetime.date(year, month, day).weekday()
        return weekday >= 4
    except ValueError:
        return False


def _parse_date(token: str) -> tuple[int, int, int] | None:
    """Возвращает (day, month, year) или None."""
    m = _DATE_RE.match(token)
    if not m:
        return None
    day, month = int(m.group(1)), int(m.group(2))
    year_short = m.group(3)
    if year_short is not None:
        year = 2000 + int(year_short)
    else:
        year = datetime.date.today().year
    try:
        datetime.date(year, month, day)  # валидация
    except ValueError:
        return None
    return day, month, year


def _split_hm(raw: str, minutes_str: str | None) -> tuple[int, int] | None:
    """
    Разбивает сырую часть времени на (hours, minutes).
    Если минуты переданы отдельно (через . или :) — используем их.
    Иначе, если raw — 4 цифры — трактуем как HHMM.
    Возвращает None при выходе за допустимые диапазоны.
    """
    if minutes_str is not None:
        h, m = int(raw), int(minutes_str)
    elif len(raw) == 4:
        h, m = int(raw[:2]), int(raw[2:])
    else:
        h, m = int(raw), 0
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return None
    return h, m


def parse_time(token: str) -> tuple[float, float] | None:
    """Возвращает (start_hours, end_hours) или None."""
    m = _TIME_RE.match(token)
    if not m:
        return None
    start_parts = _split_hm(m.group(1), m.group(2))
    end_parts   = _split_hm(m.group(3), m.group(4))
    if start_parts is None or end_parts is None:
        return None
    start_h, start_m = start_parts
    end_h,   end_m   = end_parts
    if not (0 <= start_h <= 23 and 0 <= start_m <= 59):
        return None
    if not (0 <= end_h <= 23 and 0 <= end_m <= 59):
        return None
    start = start_h + start_m / 60
    end   = end_h   + end_m   / 60
    return start, end


def check_overlap(start1: float, end1: float, start2: float, end2: float) -> bool:
    """
    Возвращает True если два временных диапазона пересекаются.
    Учитывает переход через полночь: если start > end — диапазон идёт через 00:00.
    Алгоритм: развернуть каждый диапазон в набор получасов [0.0, 0.5, ...23.5],
    проверить пересечение множеств.
    """
    def expand(s: float, e: float) -> set:
        slots: set[float] = set()
        t = s
        if s == e:
            return slots
        max_iter = 48  # максимум 48 получасов в сутках
        for _ in range(max_iter):
            slots.add(round(t, 6))
            t = (t + 0.5) % 24
            if abs(t - e % 24) < 0.001:
                break
        return slots

    return bool(expand(start1, end1) & expand(start2, end2))


def parse_shift(text: str, position: str) -> dict | None:
    """
    Разбирает строку вида "{дата} {время}" и возвращает словарь:
      day, month, year, start, end, h, is_weekend
    Возвращает None при невалидном формате.

    # Формат даты: DD.MM или DD.MM.YY (например 03.03 или 03.03.26)
    # Формат времени: HH:MM-HH:MM, HHMM-HHMM, HH-HH, HH.MM-HH.MM
    # Разделитель времени: любое тире (-, –, —) с пробелами или без
    """
    if not text:
        return None

    # Нормализация разделителя диапазона времени:
    # "10:00 - 20:00", "10:00–20:00", "10:00—20:00" → "10:00-20:00"
    text = re.sub(r'\s*[–—\-]\s*', '-', text.strip())

    parts = text.split()
    if len(parts) != 2:
        logger.debug("parse_shift: ожидалось 2 токена, получено %d: %r", len(parts), text)
        return None

    date_token, time_token = parts

    date_result = _parse_date(date_token)
    if date_result is None:
        logger.debug("parse_shift: не удалось разобрать дату: %r", date_token)
        return None

    time_result = parse_time(time_token)
    if time_result is None:
        logger.debug("parse_shift: не удалось разобрать время: %r", time_token)
        return None

    day, month, year = date_result
    start, end = time_result

    if start > end:
        raw_h = 24 - start + end
    else:
        raw_h = end - start

    h = round_to_half(raw_h)
    weekend = is_weekend(day, month, year)

    result = {
        "day": day,
        "month": month,
        "year": year,
        "start": start,
        "end": end,
        "h": h,
        "is_weekend": weekend,
    }
    logger.debug("parse_shift: %r → %s", text, result)
    return result
