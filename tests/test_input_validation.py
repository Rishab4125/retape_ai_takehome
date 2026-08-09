import json

import pytest

from feasibility.adapters.json_loader import load_client, load_creditor_rules, load_offer


def _write(tmp_path, name, data):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def test_invalid_draft_day_rejected(tmp_path):
    p = _write(tmp_path, "client.json", {
        "draft_amount_cents": 100, "draft_day": 32,
        "first_draft_date": "2026-01-01", "last_draft_date": "2026-02-01",
        "as_of_date": "2025-12-31", "current_balance_cents": 0, "ledger": [],
    })
    with pytest.raises(ValueError):
        load_client(p)


def test_invalid_ledger_entry_type_rejected(tmp_path):
    p = _write(tmp_path, "client.json", {
        "draft_amount_cents": 100, "draft_day": 1,
        "first_draft_date": "2026-01-01", "last_draft_date": "2026-02-01",
        "as_of_date": "2025-12-31", "current_balance_cents": 0,
        "ledger": [{"date": "2026-01-01", "amount_cents": 100, "type": "bogus"}],
    })
    with pytest.raises(ValueError):
        load_client(p)


def test_negative_settlement_pct_rejected(tmp_path):
    p = _write(tmp_path, "offer.json", {
        "creditor": "X", "creditor_balance_cents": 100, "original_balance_cents": 100,
        "settlement_pct": -0.1,
    })
    with pytest.raises(ValueError):
        load_offer(p)


def test_max_payments_below_1_rejected(tmp_path):
    p = _write(tmp_path, "creditor_rules.json", {
        "max_terms": 1, "max_payments": 0, "min_payment_cents": 0, "max_token_pays": 0,
        "bank_fee_cents": 0, "program_fee_pct": 0.1,
    })
    with pytest.raises(ValueError):
        load_creditor_rules(p)


def test_min_payment_cents_negative_rejected(tmp_path):
    p = _write(tmp_path, "creditor_rules.json", {
        "max_terms": 1, "max_payments": 1, "min_payment_cents": -1, "max_token_pays": 0,
        "bank_fee_cents": 0, "program_fee_pct": 0.1,
    })
    with pytest.raises(ValueError):
        load_creditor_rules(p)


def test_invalid_tier_from_payment_number_rejected(tmp_path):
    p = _write(tmp_path, "creditor_rules.json", {
        "max_terms": 5, "max_payments": 5, "min_payment_cents": 100, "max_token_pays": 0,
        "min_payment_tiers": [[0, 500]],
        "bank_fee_cents": 0, "program_fee_pct": 0.1,
    })
    with pytest.raises(ValueError):
        load_creditor_rules(p)


def test_valid_input_loads_cleanly(tmp_path):
    p = _write(tmp_path, "creditor_rules.json", {
        "max_terms": 5, "max_payments": 5, "min_payment_cents": 100, "max_token_pays": 2,
        "min_payment_tiers": [[3, 500]], "even_pays": False, "is_ballooning_allowed": False,
        "max_segments": 2, "bank_fee_cents": 50, "program_fee_pct": 0.1,
    })
    rules = load_creditor_rules(p)
    assert rules.max_terms == 5
    assert rules.min_payment_tiers == [(3, 500)]
