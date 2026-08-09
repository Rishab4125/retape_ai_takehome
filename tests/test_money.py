from decimal import Decimal

from feasibility.domain.models import CreditorRules, Offer
from feasibility.domain.money import offer_total_cents, pct_of_cents, program_fee_cents, round_half_up


def test_round_half_up_positive_half():
    assert round_half_up(Decimal("0.5")) == 1
    assert round_half_up(Decimal("1.5")) == 2
    assert round_half_up(Decimal("2.5")) == 3


def test_round_half_up_negative_half_away_from_zero():
    assert round_half_up(Decimal("-0.5")) == -1
    assert round_half_up(Decimal("-1.5")) == -2
    assert round_half_up(Decimal("-2.5")) == -3


def test_round_half_up_not_bankers_rounding():
    # Python's builtin round() would give 2 here (round-half-to-even); we must not.
    assert round_half_up(Decimal("2.5")) == 3
    assert round(2.5) == 2  # sanity: confirms builtin round() really is banker's rounding


def test_round_half_up_zero_and_exact():
    assert round_half_up(Decimal("0")) == 0
    assert round_half_up(Decimal("5")) == 5
    assert round_half_up(5) == 5
    assert round_half_up(5.0) == 5


def test_pct_of_cents_float_drift_case():
    # 0.145 is not exactly representable in binary float; must not drift.
    assert pct_of_cents(0.145, 10000) == 1450


def test_pct_of_cents_exact_half_cent_boundary():
    # 12.5 cents -> rounds up to 13
    assert pct_of_cents(0.125, 100) == 13


def test_offer_total_cents_zero_pct():
    offer = Offer(creditor="X", creditor_balance_cents=100000, original_balance_cents=100000, settlement_pct=0.0)
    assert offer_total_cents(offer) == 0


def test_program_fee_cents_zero_pct():
    offer = Offer(creditor="X", creditor_balance_cents=100000, original_balance_cents=100000, settlement_pct=0.5)
    rules = CreditorRules(
        max_terms=1, max_payments=1, min_payment_cents=0, max_token_pays=1,
        min_payment_tiers=[], even_pays=True, is_ballooning_allowed=False,
        max_segments=1, bank_fee_cents=0, program_fee_pct=0.0,
    )
    assert program_fee_cents(offer, rules) == 0


def test_large_cents_no_float_precision_loss():
    offer = Offer(creditor="X", creditor_balance_cents=10**12, original_balance_cents=10**12, settlement_pct=0.5)
    assert offer_total_cents(offer) == 5 * 10**11
