"""Pure domain data models for the feasibility take-home.

No I/O here (no ``json``, no ``pathlib``) — these are plain dataclasses.
Money is always integer cents; dates are ``datetime.date``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Literal

EntryType = Literal["credit", "debit"]


@dataclass(frozen=True)
class LedgerEntry:
    date: date
    amount_cents: int
    type: EntryType


@dataclass
class Client:
    draft_amount_cents: int
    draft_day: int
    first_draft_date: date
    last_draft_date: date
    as_of_date: date
    current_balance_cents: int
    ledger: list[LedgerEntry] = field(default_factory=list)


@dataclass
class Offer:
    creditor: str
    creditor_balance_cents: int
    original_balance_cents: int
    settlement_pct: float
    # Optional. When omitted, default to the end of the month of first_draft_date
    # (see default_first_payment_date()).
    first_payment_date: date | None = None


@dataclass
class CreditorRules:
    max_terms: int
    max_payments: int
    min_payment_cents: int
    max_token_pays: int
    min_payment_tiers: list[tuple[int, int]]  # [(from_payment_1based, min_cents), ...]
    # Two independent creditor flags (both default False):
    #   even_pays            -> every creditor payment must be equal (ballooning is irrelevant).
    #   is_ballooning_allowed -> the final payment may absorb the remainder (a "balloon").
    # When NOT ballooning (and not even), the payment structure is bounded to at most
    # `max_segments` distinct payment levels so it can't fan out into an arbitrarily
    # complex staircase. The actual shape is whatever the objective produces
    # (maximize fee collected upfront / keep creditor payments low early).
    even_pays: bool
    is_ballooning_allowed: bool
    max_segments: int
    bank_fee_cents: int
    program_fee_pct: float
