from feasibility.domain.models import CreditorRules
from feasibility.domain.schedules import build_balloon, build_even, build_staircase, floor_for_position


def _rules(**overrides) -> CreditorRules:
    base = dict(
        max_terms=12, max_payments=12, min_payment_cents=2500, max_token_pays=6,
        min_payment_tiers=[], even_pays=False, is_ballooning_allowed=False,
        max_segments=4, bank_fee_cents=500, program_fee_pct=0.2,
    )
    base.update(overrides)
    return CreditorRules(**base)


def test_build_even_remainder_on_last_payments():
    payments = build_even(3, 100, _rules(min_payment_cents=0))
    assert payments == [33, 33, 34]
    assert sum(payments) == 100


def test_build_even_exact_divisibility():
    payments = build_even(4, 40000, _rules())
    assert payments == [10000] * 4


def test_build_even_non_decreasing():
    payments = build_even(5, 103, _rules(min_payment_cents=0))
    assert payments == sorted(payments)
    assert sum(payments) == 103


def test_build_balloon_prefix_minimal_final_absorbs():
    rules = _rules(is_ballooning_allowed=True)
    payments = build_balloon(4, 25000, rules)
    assert payments[:3] == [2500, 2500, 2500]
    assert payments[3] == 25000 - 7500
    assert payments == sorted(payments)


def test_build_balloon_k1():
    rules = _rules(is_ballooning_allowed=True)
    assert build_balloon(1, 5000, rules) == [5000]


def test_build_balloon_rejects_if_final_below_prefix():
    rules = _rules(is_ballooning_allowed=True, min_payment_cents=100)
    # offer_total too small: final payment would be negative
    assert build_balloon(3, 50, rules) is None


def test_token_pay_cap_enforced():
    rules = _rules(max_token_pays=2, min_payment_cents=2500)
    # positions 1-2 may sit at 2500, position 3+ must exceed it
    assert floor_for_position(1, 5, rules) == 2500
    assert floor_for_position(2, 5, rules) == 2500
    assert floor_for_position(3, 5, rules) == 2501


def test_tier_floor_from_payment_number():
    rules = _rules(min_payment_tiers=[(7, 5000)])
    assert floor_for_position(6, 12, rules) == 2500
    assert floor_for_position(7, 12, rules) == 5000
    assert floor_for_position(12, 12, rules) == 5000


def test_multiple_overlapping_tiers_uses_largest():
    rules = _rules(min_payment_tiers=[(3, 3000), (7, 5000), (10, 7000)])
    assert floor_for_position(2, 12, rules) == 2500
    assert floor_for_position(3, 12, rules) == 3000
    assert floor_for_position(6, 12, rules) == 3000
    assert floor_for_position(7, 12, rules) == 5000
    assert floor_for_position(9, 12, rules) == 5000
    assert floor_for_position(10, 12, rules) == 7000


def test_build_staircase_respects_max_segments():
    rules = _rules(min_payment_tiers=[(7, 5000)], max_segments=2)
    payments = build_staircase(12, 60000, rules, rules.max_segments)
    assert payments is not None
    assert len(set(payments)) <= 2
    assert sum(payments) == 60000
    assert payments == sorted(payments)
    assert all(p >= 5000 for p in payments[6:])


def test_build_staircase_max_segments_1_forces_flat():
    rules = _rules(min_payment_tiers=[(7, 5000)], max_segments=1)
    payments = build_staircase(12, 60000, rules, rules.max_segments)
    assert payments is not None
    assert len(set(payments)) == 1


def test_build_staircase_exact_sum_invariant():
    rules = _rules(min_payment_tiers=[(4, 4000)], max_segments=3)
    for k in range(1, 9):
        payments = build_staircase(k, 30000, rules, rules.max_segments)
        if payments is not None:
            assert sum(payments) == 30000
            assert payments == sorted(payments)
            assert len(set(payments)) <= 3


def test_build_staircase_tier_floor_larger_than_offer_total_infeasible():
    rules = _rules(min_payment_tiers=[(1, 999999)])
    assert build_staircase(1, 100, rules, rules.max_segments) is None
