"""Backward-compatible re-export shim.

The actual implementations now present in ``feasibility.domain.models``,
``feasibility.domain.dates``, ``feasibility.domain.money``
and ``feasibility.adapters.json_loader`` (the JSON file adapter). This
module exists purely so existing imports (``from feasibility.models import
...``) keep working unchanged.
"""

from __future__ import annotations

from feasibility.adapters.json_loader import (
    load_case,
    load_client,
    load_creditor_rules,
    load_offer,
)
from feasibility.domain.dates import (
    add_months,
    default_first_payment_date,
    end_of_month,
    is_end_of_month,
    monthly_payment_dates,
)
from feasibility.domain.models import Client, CreditorRules, EntryType, LedgerEntry, Offer
from feasibility.domain.money import offer_total_cents, program_fee_cents

__all__ = [
    "EntryType",
    "LedgerEntry",
    "Client",
    "Offer",
    "CreditorRules",
    "end_of_month",
    "is_end_of_month",
    "add_months",
    "default_first_payment_date",
    "monthly_payment_dates",
    "load_client",
    "load_offer",
    "load_creditor_rules",
    "load_case",
    "offer_total_cents",
    "program_fee_cents",
]
