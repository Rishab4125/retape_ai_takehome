from datetime import date

from feasibility.domain.simulation import SimTransaction, simulate


def test_same_day_credit_before_debit_ordering():
    # A debit-first ordering would go negative; credit-first must not.
    txns = [
        SimTransaction(date=date(2026, 1, 1), credit_cents=20000, kind="draft"),
        SimTransaction(date=date(2026, 1, 1), debit_cents=15000, kind="creditor_payment"),
    ]
    result = simulate(0, txns)
    assert result.feasible is True
    assert result.balances == [(date(2026, 1, 1), 5000)]


def test_exact_zero_balance():
    txns = [
        SimTransaction(date=date(2026, 1, 1), credit_cents=10000, kind="draft"),
        SimTransaction(date=date(2026, 1, 1), debit_cents=10000, kind="creditor_payment"),
    ]
    result = simulate(0, txns)
    assert result.feasible is True
    assert result.final_balance_cents == 0


def test_negative_balance_detected():
    txns = [
        SimTransaction(date=date(2026, 1, 1), debit_cents=100, kind="creditor_payment"),
    ]
    result = simulate(0, txns)
    assert result.feasible is False


def test_multiple_entries_same_date_merge():
    txns = [
        SimTransaction(date=date(2026, 1, 1), credit_cents=100, kind="draft"),
        SimTransaction(date=date(2026, 1, 1), credit_cents=50, kind="ledger"),
        SimTransaction(date=date(2026, 1, 1), debit_cents=30, kind="bank_fee"),
        SimTransaction(date=date(2026, 1, 1), debit_cents=20, kind="program_fee"),
    ]
    result = simulate(0, txns)
    assert result.final_balance_cents == 100


def test_committed_future_debit_respected():
    txns = [
        SimTransaction(date=date(2026, 1, 1), credit_cents=5000, kind="draft"),
        SimTransaction(date=date(2026, 1, 15), debit_cents=3000, kind="ledger"),
        SimTransaction(date=date(2026, 2, 1), credit_cents=5000, kind="draft"),
    ]
    result = simulate(0, txns)
    assert result.feasible is True
    assert result.balances[-1] == (date(2026, 2, 1), 7000)


def test_balance_stays_negative_flagged_even_if_it_recovers_later():
    txns = [
        SimTransaction(date=date(2026, 1, 1), debit_cents=100, kind="creditor_payment"),
        SimTransaction(date=date(2026, 2, 1), credit_cents=1000, kind="draft"),
    ]
    result = simulate(0, txns)
    assert result.feasible is False
