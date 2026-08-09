"""Date/cadence helpers."""

from __future__ import annotations

from calendar import monthrange
from datetime import date

from feasibility.domain.models import Client


def end_of_month(d: date) -> date:
    return date(d.year, d.month, monthrange(d.year, d.month)[1])


def is_end_of_month(d: date) -> bool:
    return d.day == monthrange(d.year, d.month)[1]


def add_months(d: date, n: int) -> date:
    """Shift a date by ``n`` whole months, clamping the day to month length."""
    total = (d.year * 12 + (d.month - 1)) + n
    year, month = divmod(total, 12)
    month += 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def default_first_payment_date(client: Client) -> date:
    """Default creditor first-payment date: end of the first draft's month (EOM)."""
    return end_of_month(client.first_draft_date)


def monthly_payment_dates(start: date, count: int) -> list[date]:
    """Generate ``count`` monthly dates from ``start``.

    If ``start`` is the last day of its month, every generated date is the last
    day of its month (true EOM cadence). Otherwise the day-of-month is preserved
    (clamped to month length).
    """
    if count <= 0:
        return []
    eom = is_end_of_month(start)
    out: list[date] = []
    for i in range(count):
        d = add_months(start, i)
        out.append(end_of_month(d) if eom else d)
    return out


def cadence_dates_through_horizon(start: date, horizon: date) -> list[date]:
    """Generate the full monthly cadence starting at ``start`` up to and including
    ``horizon``. Independent of any fixed count."""
    if start > horizon:
        return []
    out: list[date] = []
    eom = is_end_of_month(start)
    i = 0
    while True:
        d = add_months(start, i)
        d = end_of_month(d) if eom else d
        if d > horizon:
            break
        out.append(d)
        i += 1
    return out
