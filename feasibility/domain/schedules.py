"""Creditor payment schedule construction: floors, token-pay rule, tiers,
and the three payment shapes (even / balloon / staircase).

Each ``build_*`` function returns ``None`` (never raises) when no valid
payment sequence exists for the given ``k`` under that shape — the caller
(optimizer) treats that as "this k is not viable for this shape" and moves
on to another k.
"""

from __future__ import annotations

from feasibility.domain.models import CreditorRules


def tier_floor(pos_1based: int, rules: CreditorRules) -> int:
    """The strictest applicable ``min_payment_tiers`` floor at this position,
    or ``min_payment_cents`` if no tier applies yet."""
    floor = rules.min_payment_cents
    for from_pn, min_cents in rules.min_payment_tiers:
        if pos_1based >= from_pn:
            floor = max(floor, min_cents)
    return floor


def floor_for_position(pos_1based: int, k: int, rules: CreditorRules) -> int:
    """The floor a payment at this position must be >= , combining the base
    minimum, tier step-ups, and the token-pay rule.

    Token pays: at most ``max_token_pays`` payments in the whole sequence may
    sit exactly at ``min_payment_cents``. Because payments are non-decreasing
    and tier floors only ever step up with position, the base-min-eligible
    slots are necessarily the earliest ones — so positions
    ``1..max_token_pays`` may sit at the base minimum (subject to any tier
    floor that already applies there), and positions beyond that must
    strictly exceed ``min_payment_cents`` (still subject to whichever floor
    — base or tier — is stricter).
    """
    tf = tier_floor(pos_1based, rules)
    if pos_1based <= rules.max_token_pays:
        return tf
    # Beyond the token-pay allowance: must exceed the base minimum, but the
    # tier floor may already be stricter than "base + 1 cent".
    return max(tf, rules.min_payment_cents + 1) if tf == rules.min_payment_cents else tf


def sum_of_floors(k: int, rules: CreditorRules) -> int:
    return sum(floor_for_position(i, k, rules) for i in range(1, k + 1))


def is_non_decreasing(payments: list[int]) -> bool:
    return all(payments[i] >= payments[i - 1] for i in range(1, len(payments)))


def _validate_common(payments: list[int], k: int, offer_total: int, rules: CreditorRules) -> bool:
    if len(payments) != k:
        return False
    if sum(payments) != offer_total:
        return False
    if not is_non_decreasing(payments):
        return False
    for i, p in enumerate(payments, start=1):
        if p < floor_for_position(i, k, rules):
            return False
    return True


def build_even(k: int, offer_total: int, rules: CreditorRules) -> list[int] | None:
    """Equal payments; when not evenly divisible, remainder cents go onto the
    LAST payments so the sequence stays non-decreasing."""
    if k <= 0 or offer_total < 0:
        return None
    base, remainder = divmod(offer_total, k)
    payments = [base] * k
    for i in range(k - remainder, k):
        payments[i] += 1
    if not _validate_common(payments, k, offer_total, rules):
        return None
    return payments


def build_balloon(k: int, offer_total: int, rules: CreditorRules) -> list[int] | None:
    """Prefix payments as small as legally allowed; final payment absorbs the
    remainder. Reject if the final payment would violate non-decreasing or
    its own floor, or go negative."""
    if k <= 0 or offer_total < 0:
        return None
    if k == 1:
        payments = [offer_total]
        return payments if _validate_common(payments, k, offer_total, rules) else None

    prefix = [floor_for_position(i, k, rules) for i in range(1, k)]
    final = offer_total - sum(prefix)
    payments = prefix + [final]
    if final < 0:
        return None
    if not _validate_common(payments, k, offer_total, rules):
        return None
    return payments


def build_staircase(k: int, offer_total: int, rules: CreditorRules, max_segments: int) -> list[int] | None:
    """Staircase construction: keep the first ``k - L`` positions at their own individual
    natural floor (never forced level — tiers already group these naturally),
    and elevate only a trailing suffix of length ``L`` to one uniform level
    that absorbs the excess cash. Try the SMALLEST ``L`` (fewest elevated
    late positions) that satisfies ``max_segments``, since minimizing how
    many late positions get bumped keeps as many early payments as possible
    at their true floor — directly serving the objective (minimize early
    creditor outflow / maximize room for early fee collection). This also
    naturally reproduces a balloon-like final payment when ``max_segments``
    allows it, without requiring ``is_ballooning_allowed``.
    """
    if k <= 0 or offer_total < 0:
        return None

    for suffix_len in range(1, k + 1):
        payments = _try_staircase_suffix(k, offer_total, rules, suffix_len, max_segments)
        if payments is not None:
            return payments
    return None


def _try_staircase_suffix(k: int, offer_total: int, rules: CreditorRules, suffix_len: int, max_segments: int) -> list[int] | None:
    prefix_len = k - suffix_len
    prefix = [floor_for_position(i, k, rules) for i in range(1, prefix_len + 1)]
    suffix_floor = max(floor_for_position(i, k, rules) for i in range(prefix_len + 1, k + 1))

    minimal_total = sum(prefix) + suffix_floor * suffix_len
    excess = offer_total - minimal_total
    if excess < 0:
        return None

    base_add, remainder = divmod(excess, suffix_len)
    suffix_level = suffix_floor + base_add
    if prefix and suffix_level < prefix[-1]:
        return None  # would violate non-decreasing

    suffix_payments = [suffix_level] * suffix_len
    for i in range(suffix_len - remainder, suffix_len):
        suffix_payments[i] += 1

    payments = prefix + suffix_payments
    if not _validate_common(payments, k, offer_total, rules):
        return None
    if len(set(payments)) > max_segments:
        return None
    return payments
