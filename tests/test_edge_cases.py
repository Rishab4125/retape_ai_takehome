from datetime import date

from feasibility.domain.models import Client, CreditorRules, LedgerEntry, Offer
from feasibility.engine import evaluate_offer


def _base_client(**overrides):
    defaults = dict(
        draft_amount_cents=10000, draft_day=1,
        first_draft_date=date(2026, 1, 1), last_draft_date=date(2026, 3, 31),
        as_of_date=date(2025, 12, 31), current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 1), 10000, "credit"),
            LedgerEntry(date(2026, 2, 1), 10000, "credit"),
            LedgerEntry(date(2026, 3, 1), 10000, "credit"),
        ],
    )
    defaults.update(overrides)
    return Client(**defaults)


def _base_rules(**overrides):
    defaults = dict(
        max_terms=3, max_payments=3, min_payment_cents=2500, max_token_pays=3,
        min_payment_tiers=[], even_pays=False, is_ballooning_allowed=False,
        max_segments=3, bank_fee_cents=0, program_fee_pct=0.2,
    )
    defaults.update(overrides)
    return CreditorRules(**defaults)


def test_offer_total_zero_no_fee_is_pass_through_feasible():
    client = _base_client()
    offer = Offer(creditor="X", creditor_balance_cents=0, original_balance_cents=0,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(program_fee_pct=0.0)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is True
    assert r.schedule == []


def test_program_fee_zero_still_produces_schedule():
    client = _base_client()
    offer = Offer(creditor="X", creditor_balance_cents=10000, original_balance_cents=10000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(program_fee_pct=0.0)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is True
    assert all(row.program_fee_cents == 0 for row in r.schedule)


def test_bank_fee_zero():
    client = _base_client()
    offer = Offer(creditor="X", creditor_balance_cents=10000, original_balance_cents=10000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(bank_fee_cents=0)
    r = evaluate_offer(client, offer, rules)
    assert all(row.bank_fee_cents == 0 for row in r.schedule)


def test_first_payment_date_beyond_horizon_is_infeasible_or_handled():
    client = _base_client(last_draft_date=date(2026, 1, 15))
    offer = Offer(creditor="X", creditor_balance_cents=10000, original_balance_cents=10000,
                  settlement_pct=1.0, first_payment_date=date(2026, 2, 28))
    rules = _base_rules()
    r = evaluate_offer(client, offer, rules)
    # No cadence date exists within the horizon at all -> cannot be feasible
    assert r.feasible is False


def test_first_payment_date_exactly_on_horizon_k1_works():
    client = _base_client(last_draft_date=date(2026, 1, 31))
    offer = Offer(creditor="X", creditor_balance_cents=5000, original_balance_cents=5000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(max_terms=1, max_payments=1, program_fee_pct=0.0)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is True
    assert len(r.schedule) == 1
    assert r.schedule[0].date.isoformat() == "2026-01-31"


def test_very_large_cents_values_no_precision_loss():
    client = _base_client(
        draft_amount_cents=10**11,
        ledger=[
            LedgerEntry(date(2026, 1, 1), 10**11, "credit"),
            LedgerEntry(date(2026, 2, 1), 10**11, "credit"),
            LedgerEntry(date(2026, 3, 1), 10**11, "credit"),
        ],
    )
    offer = Offer(creditor="X", creditor_balance_cents=2 * 10**11, original_balance_cents=2 * 10**11,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(min_payment_cents=0, program_fee_pct=0.0)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is True
    assert sum(row.creditor_payment_cents for row in r.schedule) == 2 * 10**11


def test_multiple_ledger_entries_same_date():
    client = _base_client(
        ledger=[
            LedgerEntry(date(2026, 1, 1), 5000, "credit"),
            LedgerEntry(date(2026, 1, 1), 5000, "credit"),
            LedgerEntry(date(2026, 2, 1), 10000, "credit"),
            LedgerEntry(date(2026, 3, 1), 10000, "credit"),
        ],
    )
    offer = Offer(creditor="X", creditor_balance_cents=10000, original_balance_cents=10000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(program_fee_pct=0.0)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is True


def test_negative_balance_forces_infeasible_and_funding_computed():
    client = _base_client(
        ledger=[LedgerEntry(date(2026, 1, 1), 1000, "credit")],  # far too little
        last_draft_date=date(2026, 1, 31),
    )
    offer = Offer(creditor="X", creditor_balance_cents=100000, original_balance_cents=100000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(max_terms=1, max_payments=1)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is False
    assert r.schedule is None
    assert r.additional_funds is not None


def test_max_segments_1_forces_flat_staircase():
    client = _base_client()
    offer = Offer(creditor="X", creditor_balance_cents=15000, original_balance_cents=15000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(max_segments=1, program_fee_pct=0.0)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is True
    payments = [row.creditor_payment_cents for row in r.schedule]
    assert len(set(payments)) == 1


def test_already_feasible_additional_funds_is_null():
    client = _base_client()
    offer = Offer(creditor="X", creditor_balance_cents=10000, original_balance_cents=10000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(program_fee_pct=0.0)
    r = evaluate_offer(client, offer, rules)
    assert r.feasible is True
    assert r.additional_funds is None


def test_result_serialization_round_trip_shape():
    client = _base_client()
    offer = Offer(creditor="X", creditor_balance_cents=10000, original_balance_cents=10000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = _base_rules(program_fee_pct=0.0)
    r = evaluate_offer(client, offer, rules)
    d = r.to_dict()
    assert set(d.keys()) == {"feasible", "pay_shape_used", "schedule", "additional_funds"}
    for row in d["schedule"]:
        assert set(row.keys()) == {
            "date", "creditor_payment_cents", "program_fee_cents", "bank_fee_cents", "balance_cents",
        }
