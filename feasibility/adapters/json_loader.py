"""JSON-file adapter: loads Client/Offer/CreditorRules from case directories.

This is the one I/O boundary on the input side. Includes light validation of
obviously-invalid input (raises ``ValueError``); it deliberately does not
implement a full schema validator.
"""

from __future__ import annotations

import json
from pathlib import Path

from feasibility.domain.models import Client, CreditorRules, LedgerEntry, Offer


def _d(s: str):
    from datetime import date

    return date.fromisoformat(s)


def load_client(path: str | Path) -> Client:
    raw = json.loads(Path(path).read_text())

    draft_day = int(raw["draft_day"])
    if not (1 <= draft_day <= 31):
        raise ValueError(f"draft_day must be in 1..31, got {draft_day}")

    ledger: list[LedgerEntry] = []
    for e in raw.get("ledger", []):
        if e["type"] not in ("credit", "debit"):
            raise ValueError(f"invalid ledger entry type: {e['type']!r}")
        amount = int(e["amount_cents"])
        if amount < 0:
            raise ValueError(f"ledger amount_cents must be non-negative, got {amount}")
        ledger.append(LedgerEntry(_d(e["date"]), amount, e["type"]))

    return Client(
        draft_amount_cents=int(raw["draft_amount_cents"]),
        draft_day=draft_day,
        first_draft_date=_d(raw["first_draft_date"]),
        last_draft_date=_d(raw["last_draft_date"]),
        as_of_date=_d(raw["as_of_date"]),
        current_balance_cents=int(raw["current_balance_cents"]),
        ledger=ledger,
    )


def load_offer(path: str | Path) -> Offer:
    raw = json.loads(Path(path).read_text())
    fpd = raw.get("first_payment_date")

    settlement_pct = float(raw["settlement_pct"])
    if settlement_pct < 0:
        raise ValueError(f"settlement_pct must be non-negative, got {settlement_pct}")

    return Offer(
        creditor=raw["creditor"],
        creditor_balance_cents=int(raw["creditor_balance_cents"]),
        original_balance_cents=int(raw["original_balance_cents"]),
        settlement_pct=settlement_pct,
        first_payment_date=_d(fpd) if fpd else None,
    )


def load_creditor_rules(path: str | Path) -> CreditorRules:
    raw = json.loads(Path(path).read_text())

    max_terms = int(raw["max_terms"])
    max_payments = int(raw["max_payments"])
    min_payment_cents = int(raw["min_payment_cents"])
    program_fee_pct = float(raw["program_fee_pct"])
    tiers = [(int(a), int(b)) for a, b in raw.get("min_payment_tiers", [])]

    if max_terms < 1:
        raise ValueError(f"max_terms must be >= 1, got {max_terms}")
    if max_payments < 1:
        raise ValueError(f"max_payments must be >= 1, got {max_payments}")
    if min_payment_cents < 0:
        raise ValueError(f"min_payment_cents must be >= 0, got {min_payment_cents}")
    if program_fee_pct < 0:
        raise ValueError(f"program_fee_pct must be non-negative, got {program_fee_pct}")
    for from_pn, min_cents in tiers:
        if from_pn < 1:
            raise ValueError(f"min_payment_tiers from_payment_number must be >= 1, got {from_pn}")
        if min_cents < 0:
            raise ValueError(f"min_payment_tiers min_cents must be >= 0, got {min_cents}")

    return CreditorRules(
        max_terms=max_terms,
        max_payments=max_payments,
        min_payment_cents=min_payment_cents,
        max_token_pays=int(raw["max_token_pays"]),
        min_payment_tiers=tiers,
        even_pays=bool(raw.get("even_pays", False)),
        is_ballooning_allowed=bool(raw.get("is_ballooning_allowed", False)),
        max_segments=int(raw.get("max_segments", 4)),
        bank_fee_cents=int(raw["bank_fee_cents"]),
        program_fee_pct=program_fee_pct,
    )


def load_case(case_dir: str | Path) -> tuple[Client, Offer, CreditorRules]:
    p = Path(case_dir)
    return (
        load_client(p / "client.json"),
        load_offer(p / "offer.json"),
        load_creditor_rules(p / "creditor_rules.json"),
    )
