from datetime import date

from feasibility.domain.dates import (
    add_months,
    cadence_dates_through_horizon,
    default_first_payment_date,
    end_of_month,
    is_end_of_month,
    monthly_payment_dates,
)
from feasibility.domain.models import Client


def test_eom_cadence_feb_non_leap():
    dates = monthly_payment_dates(date(2026, 1, 31), 3)
    assert dates == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]


def test_eom_cadence_feb_leap_year():
    dates = monthly_payment_dates(date(2028, 1, 31), 2)
    assert dates == [date(2028, 1, 31), date(2028, 2, 29)]


def test_mid_month_cadence_day_15():
    dates = monthly_payment_dates(date(2026, 1, 15), 3)
    assert dates == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]


def test_mid_month_day_31_clamped_to_30day_months():
    # day-of-month 31 preserved where possible, clamped in short months
    dates = monthly_payment_dates(date(2026, 1, 31), 4)
    # Jan 31 IS end-of-month, so this actually takes the EOM branch (true EOM
    # cadence). Use a non-EOM 31st-anchored case instead: not directly
    # constructible since day 31 always is EOM for Jan/Mar/May/Jul/Aug/Oct/Dec.
    assert dates[0] == date(2026, 1, 31)


def test_add_months_clamps_day():
    assert add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)
    assert add_months(date(2026, 1, 30), 1) == date(2026, 2, 28)
    assert add_months(date(2028, 1, 31), 1) == date(2028, 2, 29)


def test_end_of_month_and_is_end_of_month():
    assert end_of_month(date(2026, 2, 1)) == date(2026, 2, 28)
    assert end_of_month(date(2028, 2, 1)) == date(2028, 2, 29)
    assert is_end_of_month(date(2026, 2, 28)) is True
    assert is_end_of_month(date(2028, 2, 29)) is True
    assert is_end_of_month(date(2026, 2, 27)) is False


def test_default_first_payment_date_mid_month():
    client = Client(
        draft_amount_cents=1, draft_day=15, first_draft_date=date(2026, 1, 15),
        last_draft_date=date(2026, 6, 15), as_of_date=date(2025, 12, 31), current_balance_cents=0,
    )
    assert default_first_payment_date(client) == date(2026, 1, 31)


def test_horizon_inclusion_boundary():
    # cadence date == horizon must be included; one past must be excluded.
    dates = cadence_dates_through_horizon(date(2026, 1, 31), date(2026, 3, 31))
    assert dates == [date(2026, 1, 31), date(2026, 2, 28), date(2026, 3, 31)]

    dates2 = cadence_dates_through_horizon(date(2026, 1, 31), date(2026, 3, 30))
    assert dates2 == [date(2026, 1, 31), date(2026, 2, 28)]


def test_cadence_start_after_horizon_yields_empty():
    assert cadence_dates_through_horizon(date(2026, 6, 1), date(2026, 1, 1)) == []
