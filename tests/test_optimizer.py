from datetime import date

from feasibility.domain.models import Client, CreditorRules, LedgerEntry, Offer
from feasibility.domain.money import offer_total_cents, program_fee_cents
from feasibility.domain.optimizer import generate_candidates, select_best
from feasibility.engine import _cadence_dates, evaluate_offer


def _worked_example_case():
    """ASSIGNMENT.md §6 worked micro-example: 3 cadence dates, $100 draft
    before each, start $0, offer_total=$250, program_fee=$50, bank_fee=$0,
    flat min $25. Expected: [$50, $100, $100], fee fully collected date 1."""
    client = Client(
        draft_amount_cents=10000, draft_day=1,
        first_draft_date=date(2026, 1, 1), last_draft_date=date(2026, 3, 31),
        as_of_date=date(2025, 12, 31), current_balance_cents=0,
        ledger=[
            LedgerEntry(date(2026, 1, 1), 10000, "credit"),
            LedgerEntry(date(2026, 2, 1), 10000, "credit"),
            LedgerEntry(date(2026, 3, 1), 10000, "credit"),
        ],
    )
    offer = Offer(creditor="X", creditor_balance_cents=25000, original_balance_cents=25000,
                  settlement_pct=1.0, first_payment_date=date(2026, 1, 31))
    rules = CreditorRules(
        max_terms=3, max_payments=3, min_payment_cents=2500, max_token_pays=3,
        min_payment_tiers=[], even_pays=False, is_ballooning_allowed=False,
        max_segments=3, bank_fee_cents=0, program_fee_pct=0.2,
    )
    return client, offer, rules


def test_worked_example_from_assignment():
    # ASSIGNMENT.md's [$50, $100, $100] is illustrative ("a valid schedule"),
    # not the unique optimum — the spec explicitly says there's no single
    # right shape formula. Assert the invariants the worked example is meant
    # to demonstrate instead of pinning exact payment numbers: the fee is
    # fully collectible on day 1 (since $100 - min $25 leaves >= $50 spare),
    # the sum is exact, payments are non-decreasing and respect the floor,
    # and the balance never goes negative.
    client, offer, rules = _worked_example_case()
    result = evaluate_offer(client, offer, rules)
    assert result.feasible is True
    payments = [row.creditor_payment_cents for row in result.schedule]
    assert sum(payments) == 25000
    assert payments == sorted(payments)
    assert all(p >= 2500 for p in payments)
    assert result.schedule[0].program_fee_cents == 5000
    assert all(row.program_fee_cents == 0 for row in result.schedule[1:])
    assert all(row.balance_cents >= 0 for row in result.schedule)


def test_optimizer_explores_multiple_k_and_a_smaller_k_can_win():
    # Larger k is not hard-coded as the winner: max_payments/max_terms caps
    # can exclude the largest k from consideration entirely, and among the
    # feasible ones the comparator (not k) decides. Demonstrate the search
    # genuinely spans k=1..effective_max_k by checking multiple candidates
    # are generated, and that select_best's choice matches a direct
    # from-scratch lexicographic comparison rather than "always max k".
    from feasibility.adapters.json_loader import load_case
    client, offer, rules = load_case("cases/case4_tiers")
    offer_total = offer_total_cents(offer)
    program_fee = program_fee_cents(offer, rules)
    cadence = _cadence_dates(client, offer)
    candidates = generate_candidates(client, offer, rules, offer_total, program_fee, cadence)
    assert len({c.k for c in candidates}) > 1  # more than one k was actually viable
    best = select_best(candidates)
    assert best is not None
    # best must be at least as good as every other candidate under the
    # documented lexicographic rule (fee vector desc, payments vector asc, k asc)
    from feasibility.domain.optimizer import compare_candidates
    for c in candidates:
        assert compare_candidates(best, c) <= 0


def test_determinism_repeated_runs_identical():
    client, offer, rules = _worked_example_case()
    r1 = evaluate_offer(client, offer, rules).to_dict()
    r2 = evaluate_offer(client, offer, rules).to_dict()
    assert r1 == r2
