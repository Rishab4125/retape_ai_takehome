"""The one canonical SDA ledger simulator.

Every feasibility check — for a candidate schedule, or for a candidate
additional-funding amount — must go through :func:`simulate`, so there is
exactly one place that encodes "apply all credits before all debits on any
given date" and "balance must stay >= 0 at every date, not just the end".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class SimTransaction:
    date: date
    credit_cents: int = 0
    debit_cents: int = 0
    kind: str = ""  # "draft" | "creditor_payment" | "bank_fee" | "program_fee" | "ledger" | "extra_credit"


@dataclass(frozen=True)
class SimulationResult:
    feasible: bool
    balances: list[tuple[date, int]]  # (date, balance_after) for every date touched, sorted ascending
    final_balance_cents: int


def simulate(
    starting_balance_cents: int,
    transactions: list[SimTransaction],
) -> SimulationResult:
    """Group ``transactions`` by date, apply all credits then all debits per
    date (in date order), and track the running balance.

    ``feasible`` is False as soon as the balance would go negative on any
    date. Caller is responsible for excluding any transaction dated after
    the horizon before calling this (the horizon is a scheduling concern,
    not a simulation concern).
    """
    by_date: dict[date, list[SimTransaction]] = {}
    for t in transactions:
        by_date.setdefault(t.date, []).append(t)

    balance = starting_balance_cents
    feasible = True
    balances: list[tuple[date, int]] = []

    for d in sorted(by_date):
        entries = by_date[d]
        credit_total = sum(e.credit_cents for e in entries)
        debit_total = sum(e.debit_cents for e in entries)
        balance = balance + credit_total - debit_total
        if balance < 0:
            feasible = False
        balances.append((d, balance))

    return SimulationResult(feasible=feasible, balances=balances, final_balance_cents=balance)
