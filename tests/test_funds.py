from datetime import date

from feasibility.adapters.json_loader import load_case
from feasibility.domain.funds import (
    _binary_search_min,
    find_min_lump_sum,
    find_min_monthly_increment,
    increment_guardrail,
    lump_sum_guardrail,
)
from feasibility.domain.models import Client, LedgerEntry
from feasibility.engine import evaluate_offer


def test_case2_minimum_lump_sum_matches_expected():
    client, offer, rules = load_case("cases/case2_infeasible_minima")
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is False
    assert r.additional_funds.lump_sum.amount_cents == 10000
    assert r.additional_funds.lump_sum.within_guardrail is True


def test_case2_minimum_monthly_increment_matches_expected():
    client, offer, rules = load_case("cases/case2_infeasible_minima")
    r = evaluate_offer(client, offer, rules)
    assert r.additional_funds.monthly_increment.amount_cents == 2500
    assert r.additional_funds.monthly_increment.num_drafts == 5
    assert r.additional_funds.monthly_increment.within_guardrail is True


def test_binary_search_min_monotonic_synthetic():
    # feasible for L >= 42
    assert _binary_search_min(lambda L: L >= 42, 1000) == 42


def test_binary_search_min_infeasible_even_at_upper_bound():
    assert _binary_search_min(lambda L: False, 1000) is None


def test_binary_search_min_feasible_at_zero():
    assert _binary_search_min(lambda L: True, 1000) == 0


def test_increment_guardrail_pass():
    within, reason = increment_guardrail(9000, draft_amount_cents=20000)  # 0.4*20000=8000, max(10000,8000)=10000
    assert within is True
    assert reason == ""


def test_increment_guardrail_fail():
    within, reason = increment_guardrail(10001, draft_amount_cents=20000)
    assert within is False
    assert "10001" in reason and "10000" in reason


def test_increment_guardrail_exactly_at_boundary():
    within, _ = increment_guardrail(10000, draft_amount_cents=20000)
    assert within is True


def test_lump_sum_guardrail_pass():
    within, reason = lump_sum_guardrail(60000, offer_total=100000)  # 0.65*100000=65000
    assert within is True
    assert reason == ""


def test_lump_sum_guardrail_fail():
    within, reason = lump_sum_guardrail(65001, offer_total=100000)
    assert within is False
    assert "65001" in reason


def test_lump_sum_guardrail_exactly_at_boundary():
    within, _ = lump_sum_guardrail(65000, offer_total=100000)
    assert within is True


def test_monthly_increment_zero_future_drafts():
    client = Client(
        draft_amount_cents=10000, draft_day=1,
        first_draft_date=date(2026, 1, 1), last_draft_date=date(2026, 1, 1),
        as_of_date=date(2026, 1, 1), current_balance_cents=0,
        ledger=[LedgerEntry(date(2026, 1, 1), 10000, "credit")],  # dated ON as_of_date, not future
    )
    amount, n = find_min_monthly_increment(client, feasibility_check=lambda x: True)
    assert amount is None
    assert n == 0
