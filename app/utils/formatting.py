def fmt_hours(v: float) -> str:
    """8.0 → '8', 8.5 → '8.5'"""
    return str(int(v)) if v == int(v) else str(v)


def fmt_money(v: float) -> str:
    """1500.0 → '1500', 1500.5 → '1500.50'"""
    return str(int(v)) if v == int(v) else f"{v:.2f}"


def fmt_emp_rate(emp: dict) -> str:
    """'250 р/ч', '200/300 р/ч' or 'не установлена'."""
    base = emp.get("base_rate")
    if base is None:
        return "не установлена"
    extra = emp.get("extra_rate")
    if extra is not None:
        return f"{fmt_money(base)}/{fmt_money(extra)} р/ч"
    return f"{fmt_money(base)} р/ч"
