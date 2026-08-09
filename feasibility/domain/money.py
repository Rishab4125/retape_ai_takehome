"""Money helpers: integer cents everywhere, explicit round-half-up.

Never use Python's built-in ``round()`` for business-rule rounding — it uses
round-half-to-even (banker's rounding), which the assignment explicitly
forbids. Percentages are computed via ``Decimal`` to avoid binary-float
drift (e.g. ``0.1`` is not exactly representable in float).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from feasibility.domain.models import CreditorRules, Offer


def round_half_up(value: Decimal | float | int) -> int:
    """Round to the nearest integer, ``.5`` always away from zero."""
    d = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(d.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def pct_of_cents(pct: float | Decimal, cents: int) -> int:
    """``round_half_up(pct * cents)``, computed via Decimal throughout."""
    pct_d = pct if isinstance(pct, Decimal) else Decimal(str(pct))
    return round_half_up(pct_d * Decimal(cents))


def offer_total_cents(offer: Offer) -> int:
    return pct_of_cents(offer.settlement_pct, offer.creditor_balance_cents)


def program_fee_cents(offer: Offer, rules: CreditorRules) -> int:
    return pct_of_cents(rules.program_fee_pct, offer.original_balance_cents)
