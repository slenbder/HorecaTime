from app.services.timeparsing import is_weekend

_HALF_BOUNDARY_DAY = 15  # день <= 15 — первая половина (как AM/AN и get_check_filling_summary)


def summarize_shifts(rows: list[dict], year: int, month: int) -> dict[str, float]:
    """
    Сводка часов сотрудника за месяц по строкам shifts (контракт ключей: h_/ah_ first/second/total и h_weekend_*).

    rows — смены одного сотрудника за весь месяц, элементы с ключами
    shift_date ('YYYY-MM-DD'), hours, extra_hours (None трактуется как 0).
    year/month — период; смены других месяцев игнорируются.

    Выходные часы (пт/сб/вс по shift_date через is_weekend, все часы смены
    относятся к дате начала) считаются из hours, без extra_hours, и для любого
    сотрудника; потребляет их только ветка Раннера. h_weekend_total = first + second.
    Суммы округляются до 2 знаков, чтобы не оставлять хвосты float.
    """
    h = {"first": 0.0, "second": 0.0}
    ah = {"first": 0.0, "second": 0.0}
    weekend = {"first": 0.0, "second": 0.0}

    for row in rows:
        year_s, month_s, day_s = row["shift_date"].split("-")
        if int(year_s) != year or int(month_s) != month:
            continue
        day = int(day_s)
        half = "first" if day <= _HALF_BOUNDARY_DAY else "second"
        hours = float(row["hours"] or 0.0)
        h[half] += hours
        ah[half] += float(row["extra_hours"] or 0.0)
        if is_weekend(day, month, year):
            weekend[half] += hours

    return {
        "h_first": round(h["first"], 2),
        "ah_first": round(ah["first"], 2),
        "h_second": round(h["second"], 2),
        "ah_second": round(ah["second"], 2),
        "h_total": round(h["first"] + h["second"], 2),
        "ah_total": round(ah["first"] + ah["second"], 2),
        "h_weekend_first": round(weekend["first"], 2),
        "h_weekend_second": round(weekend["second"], 2),
        "h_weekend_total": round(weekend["first"] + weekend["second"], 2),
    }
