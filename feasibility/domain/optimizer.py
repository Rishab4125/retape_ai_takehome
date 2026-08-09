"""Candidate schedule generation and selection.

For a fixed shape (even / balloon / staircase, chosen once from the
creditor flags — see ``schedules.py``), this module generates one candidate
per viable payment count ``k``, allocates the program fee as early as
possible on each candidate, simulates the full ledger, discards infeasible
candidates, and picks the best remaining one via a deterministic
lexicographic objective.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from functools import cmp_to_key

from feasibility.domain import schedules
from feasibility.domain.models import Client, CreditorRules, LedgerEntry, Offer
from feasibility.domain.simulation import SimTransaction, simulate


@dataclass
class Candidate:
    k: int
    shape: str
    payments: list[int]  # length k, one per cadence date used for creditor payments
    payment_dates: list[date]  # length k
    fee_dates: list[date]  # all dates that carry program fee (subset of payment_dates + tail dates)
    fee_alloc: dict[date, int]  # program fee collected on each fee date
    all_dates: list[date]  # union of payment_dates and fee_dates, sorted
    balances: dict[date, int]  # running SDA balance after each date in all_dates


def effective_max_k(rules: CreditorRules, cadence_len_available: int) -> int:
    return min(rules.max_payments, rules.max_terms, cadence_len_available)


def _future_ledger_transactions(client: Client) -> list[SimTransaction]:
    """Client ledger entries strictly after as_of_date (already-committed,
    must not be modified)."""
    out = []
    for e in client.ledger:
        if e.date <= client.as_of_date:
            continue
        if e.type == "credit":
            out.append(SimTransaction(date=e.date, credit_cents=e.amount_cents, kind="ledger"))
        else:
            out.append(SimTransaction(date=e.date, debit_cents=e.amount_cents, kind="ledger"))
    return out


def _build_shape(k: int, offer_total: int, rules: CreditorRules) -> tuple[list[int], str] | None:
    if rules.even_pays:
        payments = schedules.build_even(k, offer_total, rules)
        shape = "even"
    elif rules.is_ballooning_allowed:
        payments = schedules.build_balloon(k, offer_total, rules)
        shape = "balloon"
    else:
        payments = schedules.build_staircase(k, offer_total, rules, rules.max_segments)
        shape = "staircase"
    if payments is None:
        return None
    return payments, shape


def allocate_fee_earliest(
    starting_balance_cents: int,
    future_ledger: list[SimTransaction],
    payments: list[int],
    payment_dates: list[date],
    bank_fee_cents: int,
    program_fee_total: int,
    horizon: date,
    extra_cadence_dates: list[date],
) -> tuple[dict[date, int], list[date]] | None:
    """Greedily collect as much program fee as possible on the earliest
    eligible date, then the next, etc., until the total is collected or the
    horizon is exhausted.
    """
    if program_fee_total == 0:
        return {}, []

    # Fee-eligible dates: from the first creditor-payment date onward, any
    # cadence date up to and including horizon (payment dates plus any
    # trailing fee-only cadence dates).
    eligible_dates = sorted(set(payment_dates) | {d for d in extra_cadence_dates if d >= payment_dates[0]})
    eligible_dates = [d for d in eligible_dates if d <= horizon]

    debit_by_date: dict[date, int] = {}
    for p, d in zip(payments, payment_dates):
        debit_by_date[d] = debit_by_date.get(d, 0) + p + bank_fee_cents

    # Pass 1: simulate WITHOUT any fee to see the balance trajectory available
    # before fee is taken into account, date by date, in order.
    txns = list(future_ledger)
    for d, debit in debit_by_date.items():
        txns.append(SimTransaction(date=d, debit_cents=debit, kind="creditor_payment"))

    by_date: dict[date, list[SimTransaction]] = {}
    for t in txns:
        by_date.setdefault(t.date, []).append(t)

    remaining_fee = program_fee_total
    fee_alloc: dict[date, int] = {}
    balance = starting_balance_cents
    all_relevant_dates = sorted(set(by_date.keys()) | set(eligible_dates))

    for d in all_relevant_dates:
        if d > horizon:
            break
        entries = by_date.get(d, [])
        credit_total = sum(e.credit_cents for e in entries)
        debit_total = sum(e.debit_cents for e in entries)
        balance = balance + credit_total - debit_total
        if d in eligible_dates and remaining_fee > 0:
            take = min(remaining_fee, balance, remaining_fee)
            if take > 0:
                fee_alloc[d] = take
                balance -= take
                remaining_fee -= take
        if balance < 0:
            return None

    if remaining_fee > 0:
        return None  # could not collect the full fee by the horizon

    fee_dates = sorted(fee_alloc.keys())
    return fee_alloc, fee_dates


def _make_candidate(
    client: Client,
    offer: Offer,
    rules: CreditorRules,
    k: int,
    offer_total: int,
    program_fee: int,
    payment_dates_full: list[date],
    all_cadence_dates: list[date],
) -> Candidate | None:
    result = _build_shape(k, offer_total, rules)
    if result is None:
        return None
    payments, shape = result

    payment_dates = payment_dates_full[:k]
    future_ledger = _future_ledger_transactions(client)

    fee_result = allocate_fee_earliest(
        starting_balance_cents=client.current_balance_cents,
        future_ledger=future_ledger,
        payments=payments,
        payment_dates=payment_dates,
        bank_fee_cents=rules.bank_fee_cents,
        program_fee_total=program_fee,
        horizon=client.last_draft_date,
        extra_cadence_dates=all_cadence_dates,
    )
    if fee_result is None:
        return None
    fee_alloc, fee_dates = fee_result

    all_dates = sorted(set(payment_dates) | set(fee_dates))

    # Final full simulation (ledger + creditor payments + bank fees + program fee).
    txns = list(future_ledger)
    for p, d in zip(payments, payment_dates):
        txns.append(SimTransaction(date=d, debit_cents=p, kind="creditor_payment"))
        if rules.bank_fee_cents:
            txns.append(SimTransaction(date=d, debit_cents=rules.bank_fee_cents, kind="bank_fee"))
    for d, fee in fee_alloc.items():
        txns.append(SimTransaction(date=d, debit_cents=fee, kind="program_fee"))

    sim = simulate(client.current_balance_cents, txns)
    if not sim.feasible:
        return None

    balances = dict(sim.balances)
    for d in all_dates:
        if d not in balances:
            balances[d] = balances.get(d, 0)

    return Candidate(
        k=k,
        shape=shape,
        payments=payments,
        payment_dates=payment_dates,
        fee_dates=fee_dates,
        fee_alloc=fee_alloc,
        all_dates=all_dates,
        balances=balances,
    )


def generate_candidates(
    client: Client,
    offer: Offer,
    rules: CreditorRules,
    offer_total: int,
    program_fee: int,
    cadence_dates_full: list[date],
) -> list[Candidate]:
    if not cadence_dates_full:
        return []
    max_k = effective_max_k(rules, len(cadence_dates_full))
    candidates = []
    for k in range(1, max_k + 1):
        c = _make_candidate(
            client, offer, rules, k, offer_total, program_fee,
            cadence_dates_full, cadence_dates_full,
        )
        if c is not None:
            candidates.append(c)
    return candidates


def _fee_vector(c: Candidate) -> list[int]:
    """Cumulative fee collected as of each date in c.all_dates, in order."""
    cum = 0
    out = []
    for d in c.all_dates:
        cum += c.fee_alloc.get(d, 0)
        out.append(cum)
    return out


def compare_candidates(a: Candidate, b: Candidate) -> int:
    """Lexicographic comparison, returns negative if a is BETTER than b.

    Priority 1: larger cumulative fee collected, earliest date first (prefer
    the lexicographically largest early-fee vector).
    Priority 2: smaller creditor payments, earliest position first (prefer
    lexicographically smaller payments vector — defers larger payments).
    Priority 3: smaller k (deterministic tie-break).
    """
    fa, fb = _fee_vector(a), _fee_vector(b)
    n = max(len(fa), len(fb))
    for i in range(n):
        va = fa[i] if i < len(fa) else fa[-1] if fa else 0
        vb = fb[i] if i < len(fb) else fb[-1] if fb else 0
        if va != vb:
            return -1 if va > vb else 1  # larger fee vector wins -> "better" (negative)

    pa, pb = a.payments, b.payments
    m = max(len(pa), len(pb))
    for i in range(m):
        va = pa[i] if i < len(pa) else 0
        vb = pb[i] if i < len(pb) else 0
        if va != vb:
            return -1 if va < vb else 1  # smaller payment wins

    if a.k != b.k:
        return -1 if a.k < b.k else 1
    return 0


def select_best(candidates: list[Candidate]) -> Candidate | None:
    if not candidates:
        return None
    return min(candidates, key=cmp_to_key(compare_candidates))
