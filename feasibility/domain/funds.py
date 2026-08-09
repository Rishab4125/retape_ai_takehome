"""Minimum additional-funding search: lump sum and monthly increment, each
independent, using binary search over the monotonic feasibility relation,
plus guardrail evaluation.

Functions here return plain tuples (never the engine's ``FundsOption``
dataclass) to avoid a circular import between ``engine.py`` (which owns the
output dataclasses) and this module (which is pure domain logic).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Callable

from feasibility.domain.dates import cadence_dates_through_horizon, default_first_payment_date
from feasibility.domain.models import Client
from feasibility.domain.money import round_half_up


def _candidate_placement_dates(client: Client) -> list[date]:
    """Deterministic, tractable set of lump-sum placement dates: every future
    draft date and every cadence date, in chronological order. Placing a
    lump sum on a date with no intervening balance-affecting event is never
    strictly better than placing it on the earlier of the two, so this
    restricted set loses no generality in practice (documented assumption).
    """
    dates = {e.date for e in client.ledger if e.date > client.as_of_date and e.date <= client.last_draft_date}
    start = default_first_payment_date(client)
    dates |= set(cadence_dates_through_horizon(start, client.last_draft_date))
    if not dates:
        dates = {client.as_of_date}
    return sorted(dates)


def _binary_search_min(
    feasible_at: Callable[[int], bool],
    upper_bound: int,
) -> int | None:
    """Smallest non-negative integer L in [0, upper_bound] such that
    feasible_at(L) is True, assuming feasibility is monotonic non-decreasing
    in L. Returns None if even upper_bound is infeasible."""
    if not feasible_at(upper_bound):
        return None
    if feasible_at(0):
        return 0
    lo, hi = 0, upper_bound
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if feasible_at(mid):
            hi = mid
        else:
            lo = mid
    return hi


def find_min_lump_sum(
    client: Client,
    offer_total: int,
    feasibility_check: Callable[[int, date], bool],
) -> tuple[int | None, date | None]:
    """Search chronologically over candidate placement dates; for each, binary
    search the minimal L. Track the global minimum, earliest date on ties.
    """
    placement_dates = _candidate_placement_dates(client)
    upper_bound = max(offer_total, client.draft_amount_cents, 1) * 4 + 1

    best_amount: int | None = None
    best_date: date | None = None
    for d in placement_dates:
        amount = _binary_search_min(lambda L, d=d: feasibility_check(L, d), upper_bound)
        if amount is None:
            continue
        if best_amount is None or amount < best_amount:
            best_amount, best_date = amount, d
    return best_amount, best_date


def find_min_monthly_increment(
    client: Client,
    feasibility_check: Callable[[int], bool],
) -> tuple[int | None, int]:
    """N = number of future drafts. Binary search minimal integer X such that
    bumping every future draft by X makes a feasible schedule exist."""
    n = sum(1 for e in client.ledger if e.type == "credit" and e.date > client.as_of_date and e.date <= client.last_draft_date)
    if n == 0:
        return None, 0

    upper_bound = max(client.draft_amount_cents, 1) * 4 + 1
    while not feasibility_check(upper_bound):
        upper_bound *= 2
        if upper_bound > 10**12:
            return None, n

    amount = _binary_search_min(feasibility_check, upper_bound)
    return amount, n


def increment_guardrail(x_cents: int, draft_amount_cents: int) -> tuple[bool, str]:
    limit = max(10000, round_half_up(Decimal("0.40") * Decimal(draft_amount_cents)))
    if x_cents > limit:
        return False, f"Required monthly increment of {x_cents} cents exceeds the guardrail of {limit} cents."
    return True, ""


def lump_sum_guardrail(l_cents: int, offer_total: int) -> tuple[bool, str]:
    limit = round_half_up(Decimal("0.65") * Decimal(offer_total))
    if l_cents > limit:
        return False, f"Required lump sum of {l_cents} cents exceeds the guardrail of {limit} cents."
    return True, ""
