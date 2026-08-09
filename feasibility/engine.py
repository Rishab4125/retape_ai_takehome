"""Candidate implementation goes here.

Implement ``evaluate_offer`` so that it satisfies the rules in ASSIGNMENT.md and
the example expectations in tests/test_cases.py. The dataclasses below define the
required OUTPUT shape (see ASSIGNMENT.md "Output"). You may add helpers, modules,
or rewrite internals freely, but keep ``evaluate_offer``'s signature and the
serialized shape of ``Result`` (so the runner and tests work).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date

from feasibility.domain import funds, money, optimizer
from feasibility.domain.dates import cadence_dates_through_horizon, default_first_payment_date
from feasibility.domain.models import Client, CreditorRules, LedgerEntry, Offer
from feasibility.domain.optimizer import Candidate


@dataclass
class ScheduleRow:
    date: date
    creditor_payment_cents: int
    program_fee_cents: int
    bank_fee_cents: int
    balance_cents: int


@dataclass
class FundsOption:
    amount_cents: int
    within_guardrail: bool
    reason: str
    # lump-sum only:
    date: date | None = None
    # monthly-increment only:
    num_drafts: int | None = None


@dataclass
class AdditionalFunds:
    lump_sum: FundsOption
    monthly_increment: FundsOption


@dataclass
class Result:
    feasible: bool
    # One of "even", "staircase", or "balloon" — the shape your solution produced
    # (driven by the creditor flags). None when infeasible.
    pay_shape_used: str | None = None
    schedule: list[ScheduleRow] | None = None
    additional_funds: AdditionalFunds | None = None

    def to_dict(self) -> dict:
        out: dict = {"feasible": self.feasible, "pay_shape_used": self.pay_shape_used}
        out["schedule"] = (
            [
                {
                    "date": r.date.isoformat(),
                    "creditor_payment_cents": r.creditor_payment_cents,
                    "program_fee_cents": r.program_fee_cents,
                    "bank_fee_cents": r.bank_fee_cents,
                    "balance_cents": r.balance_cents,
                }
                for r in self.schedule
            ]
            if self.schedule is not None
            else None
        )
        if self.additional_funds is None:
            out["additional_funds"] = None
        else:
            def opt(o: FundsOption) -> dict:
                d = {
                    "amount_cents": o.amount_cents,
                    "within_guardrail": o.within_guardrail,
                    "reason": o.reason,
                }
                if o.date is not None:
                    d["date"] = o.date.isoformat()
                if o.num_drafts is not None:
                    d["num_drafts"] = o.num_drafts
                return d

            out["additional_funds"] = {
                "lump_sum": opt(self.additional_funds.lump_sum),
                "monthly_increment": opt(self.additional_funds.monthly_increment),
            }
        return out


def _cadence_dates(client: Client, offer: Offer) -> list[date]:
    start = offer.first_payment_date or default_first_payment_date(client)
    return cadence_dates_through_horizon(start, client.last_draft_date)


def _find_feasible_schedule(client: Client, offer: Offer, rules: CreditorRules) -> Candidate | None:
    offer_total = money.offer_total_cents(offer)
    program_fee = money.program_fee_cents(offer, rules)
    cadence = _cadence_dates(client, offer)

    if offer_total == 0:
        # No creditor payment is owed at all. A pass-through schedule with
        # zero payments is the simplest reading: k=0, only fee (if any) needs
        # to be collected. Assumption documented in README.
        if program_fee == 0:
            return Candidate(
                k=0, shape=_shape_name(rules), payments=[], payment_dates=[],
                fee_dates=[], fee_alloc={}, all_dates=[], balances={},
            )
        # Fee still owed with no creditor payment: allocate the fee alone,
        # starting from the first cadence date (fee timing constraint 6a
        # requires a first-payment-date anchor; with k=0 we treat the first
        # cadence date itself as that anchor).
        if not cadence:
            return None
        fee_result = optimizer.allocate_fee_earliest(
            starting_balance_cents=client.current_balance_cents,
            future_ledger=optimizer._future_ledger_transactions(client),
            payments=[],
            payment_dates=[cadence[0]],
            bank_fee_cents=0,
            program_fee_total=program_fee,
            horizon=client.last_draft_date,
            extra_cadence_dates=cadence,
        )
        if fee_result is None:
            return None
        fee_alloc, fee_dates = fee_result
        return Candidate(
            k=0, shape=_shape_name(rules), payments=[], payment_dates=[],
            fee_dates=fee_dates, fee_alloc=fee_alloc, all_dates=sorted(fee_dates),
            balances={},
        )

    if not cadence:
        return None

    candidates = optimizer.generate_candidates(client, offer, rules, offer_total, program_fee, cadence)
    return optimizer.select_best(candidates)


def _shape_name(rules: CreditorRules) -> str:
    if rules.even_pays:
        return "even"
    if rules.is_ballooning_allowed:
        return "balloon"
    return "staircase"


def _with_lump_sum(client: Client, amount_cents: int, on_date: date) -> Client:
    ledger = list(client.ledger) + [LedgerEntry(date=on_date, amount_cents=amount_cents, type="credit")]
    return Client(
        draft_amount_cents=client.draft_amount_cents,
        draft_day=client.draft_day,
        first_draft_date=client.first_draft_date,
        last_draft_date=client.last_draft_date,
        as_of_date=client.as_of_date,
        current_balance_cents=client.current_balance_cents,
        ledger=ledger,
    )


def _with_monthly_increment(client: Client, amount_cents: int) -> Client:
    ledger = [
        LedgerEntry(date=e.date, amount_cents=e.amount_cents + amount_cents, type=e.type)
        if e.type == "credit" and e.date > client.as_of_date
        else e
        for e in client.ledger
    ]
    return Client(
        draft_amount_cents=client.draft_amount_cents,
        draft_day=client.draft_day,
        first_draft_date=client.first_draft_date,
        last_draft_date=client.last_draft_date,
        as_of_date=client.as_of_date,
        current_balance_cents=client.current_balance_cents,
        ledger=ledger,
    )


def _to_rows(candidate: Candidate, rules: CreditorRules) -> list[ScheduleRow]:
    rows: list[ScheduleRow] = []
    payment_by_date = dict(zip(candidate.payment_dates, candidate.payments))
    running_balance = None
    for d in candidate.all_dates:
        creditor_payment = payment_by_date.get(d, 0)
        bank_fee = rules.bank_fee_cents if creditor_payment > 0 else 0
        fee = candidate.fee_alloc.get(d, 0)
        balance = candidate.balances.get(d, 0)
        rows.append(
            ScheduleRow(
                date=d,
                creditor_payment_cents=creditor_payment,
                program_fee_cents=fee,
                bank_fee_cents=bank_fee,
                balance_cents=balance,
            )
        )
    return rows


def evaluate_offer(client: Client, offer: Offer, rules: CreditorRules) -> Result:
    """Evaluate a single offer. See ASSIGNMENT.md for the full specification.

    Return a Result with feasible=True and a schedule when the offer fits, or
    feasible=False with additional_funds (minimum lump sum AND minimum monthly
    increment) when it does not.
    """
    best = _find_feasible_schedule(client, offer, rules)
    if best is not None:
        return Result(
            feasible=True,
            pay_shape_used=_shape_name(rules),
            schedule=_to_rows(best, rules),
            additional_funds=None,
        )

    offer_total = money.offer_total_cents(offer)

    def lump_feasibility_check(amount_cents: int, on_date: date) -> bool:
        return _find_feasible_schedule(_with_lump_sum(client, amount_cents, on_date), offer, rules) is not None

    def increment_feasibility_check(amount_cents: int) -> bool:
        return _find_feasible_schedule(_with_monthly_increment(client, amount_cents), offer, rules) is not None

    lump_amount, lump_date = funds.find_min_lump_sum(client, offer_total, lump_feasibility_check)
    inc_amount, inc_n = funds.find_min_monthly_increment(client, increment_feasibility_check)

    if lump_amount is None:
        lump_opt = FundsOption(
            amount_cents=0, within_guardrail=False,
            reason="No finite lump sum (within the search bound) makes the offer feasible.",
            date=None,
        )
    else:
        within, reason = funds.lump_sum_guardrail(lump_amount, offer_total)
        lump_opt = FundsOption(amount_cents=lump_amount, within_guardrail=within, reason=reason, date=lump_date)

    if inc_amount is None:
        inc_opt = FundsOption(
            amount_cents=0, within_guardrail=False,
            reason=(
                "No future drafts exist to apply a monthly increment to."
                if inc_n == 0
                else "No finite monthly increment (within the search bound) makes the offer feasible."
            ),
            num_drafts=inc_n,
        )
    else:
        within, reason = funds.increment_guardrail(inc_amount, client.draft_amount_cents)
        inc_opt = FundsOption(amount_cents=inc_amount, within_guardrail=within, reason=reason, num_drafts=inc_n)

    return Result(
        feasible=False,
        pay_shape_used=None,
        schedule=None,
        additional_funds=AdditionalFunds(lump_sum=lump_opt, monthly_increment=inc_opt),
    )
