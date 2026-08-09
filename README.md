# Settlement Feasibility & Fee Engine — Take-home

Welcome, and thanks for taking the time. The full problem is in
[`ASSIGNMENT.md`](./ASSIGNMENT.md). This README is just orientation.

## The task in one line

Given a client's escrow account, a settlement offer, and a creditor's rules,
decide whether the offer is affordable (and schedule it, collecting our fee as
early as allowed) or — if not — compute the minimum extra funding needed.

## Setup

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

## Layout (Updated)

> Updated to the original layout to the actual submitted structure — see "Implementation
> notes"

```
retape_ai_takehome/
├── ASSIGNMENT.md            # full specification — read this
├── specifications.md        # an internal, non-authoritative implementation spec
├── feasibility/
│   ├── domain/               # pure logic, zero I/O
│   │   ├── models.py          # Client, Offer, CreditorRules, LedgerEntry
│   │   ├── money.py            # round_half_up, pct_of_cents (Decimal-based)
│   │   ├── dates.py             # cadence generation, EOM/mid-month clamping
│   │   ├── simulation.py         # the one canonical ledger simulator
│   │   ├── schedules.py           # floors/tiers/token rule + even/balloon/staircase builders
│   │   ├── optimizer.py            # candidate generation, fee allocation, lexicographic selection
│   │   └── funds.py                 # lump-sum / monthly-increment binary search + guardrails
│   ├── adapters/
│   │   └── json_loader.py    # the one I/O boundary — case JSON -> domain objects (+ validation)
│   ├── engine.py             # >>> evaluate_offer <<< — orchestrates domain, owns Result shape
│   └── models.py             # re-export shim (`from feasibility.models import ...` still works)
├── cases/                   # example cases (client.json / offer.json / creditor_rules.json)
│   ├── case1_feasible_even
│   ├── case2_infeasible_minima
│   ├── case3_balloon
│   └── case4_tiers
├── tests/                   # test_smoke.py / test_cases.py (provided) plus test_money.py,
│                              test_dates.py, test_simulation.py, test_schedules.py,
│                              test_optimizer.py, test_funds.py, test_edge_cases.py,
│                              test_cli.py, test_input_validation.py (added)
├── run.py                   # python run.py cases/<case>
└── requirements.txt
```

## Run

```bash
# evaluate a single case (prints the Result as JSON)
python run.py cases/case1_feasible_even

# tests
pytest -q
```

Out of the box, `tests/test_smoke.py` passes and `tests/test_cases.py` fails —
the latter is your target. Go beyond those four cases with your own tests.

## What to submit

Your implementation, your tests, and a short README section describing:
- your approach and the alternatives you considered,
- **your interpretation of the payment shapes** (even / staircase / balloon — we
  left these loosely defined on purpose),
- assumptions you made, and known edge cases / limitations.

Budget ~5–6 hours. Prefer a correct, well-tested core over breadth. When in
doubt, write down your assumption and keep going.

---

## Solution Implementation notes (the submission)

### Architecture

The code is organized as a **hexagonal architecture** layout: 
  - **domain core** main logic with. Dataclass and 'Date Helpers' logic from 
  original 'feasibility/models.py' are transfered here
  - **adapter layer** for the one real I/O boundary (JSON file loading). 
  'Loaders' section definations from 'feasibility/models.py' are transfered here.
  -**`engine.py`** as the application/use-case layer that wires domain and adapter
  layer together.

```
feasibility/
  domain/            # logic layer
    models.py         # Client, Offer, CreditorRules, LedgerEntry
    money.py          # round_half_up, pct_of_cents (Decimal-based)
    dates.py          # cadence generation, EOM/mid-month clamping
    simulation.py     # the one canonical ledger simulator
    schedules.py      # floors/tiers/token rule + even/balloon/staircase builders
    optimizer.py      # candidate generation across k, fee allocation, lexicographic selection
    funds.py          # lump-sum / monthly-increment binary search + guardrails
  adapters/
    json_loader.py    # the one I/O boundary — case JSON -> domain objects (+ light validation)
  engine.py          # evaluate_offer(): orchestrates domain modules, owns the output Result shape
  models.py          # re-export shim so `from feasibility.models import ...` keeps working
run.py               # CLI adapter: argv -> load_case -> evaluate_offer -> JSON on stdout
```

### Assumptions

- **Prioritize early program-fee collection:** The payment schedule should collect the program fee as early as possible. For balloon and tiered-payment schedules, keep early creditor payments as low as the rules allow so that the maximum possible available balance can be used to cover the program fee at the earliest dates.

- **Even payments take priority:** If both `even_pays` and `is_ballooning_allowed` are `true`, use even payments and ignore ballooning.

- **Token payments come first:** Because payments cannot decrease, payments equal to `min_payment_cents` can only appear at the beginning. At most the first `max_token_pays` payments can be token. Later payments must be greater than the minimum.

- **Zero offer total:** If `offer_total` is `0` and there is no program fee, return a valid result with no creditor payments and an empty schedule. If a program fee is still due, collect it starting from the first available cadence date.

- **Lump-sum dates:** Only consider future draft dates and payment cadence dates as possible lump-sum dates. There is no need to check every calendar date.

- **No future drafts:** If there are no future drafts (`N = 0`), a monthly increment cannot help. Return `amount_cents: 0` and `within_guardrail: false` with a clear reason.

- **No possible funding solution:** If no reasonable lump sum or monthly increment can make the offer feasible, return `within_guardrail: false` with a clear reason instead of returning an arbitrary large amount.

### Bugs Fixed

Two bugs in the original scaffold were fixed as part of this: 
- `round()` (banker's rounding) was replaced everywhere with an explicit `round_half_up`
using `Decimal`
- `Offer.current_balance_cents` was renamed to `creditor_balance_cents` 
(matching ASSIGNMENT.md §3's own note and its own example `offer.json`) 
in the dataclass, loader, and all four case fixtures.

### Ledger simulation

`domain/simulation.py::simulate` is the single function used everywhere a
balance must be checked — for scoring a candidate schedule, and for testing
whether an additional-funding amount makes the offer feasible. 

It groups transactions by date, applies all credits before all debits on each date,
and flags infeasibility as soon as the balance goes negative on *any* date
(not just the final balance).

### Candidate Generation & Objective

For each possible payment count `k = 1..effective_max_k`, generate one schedule using the selected payment shape:

- `even` → when `even_pays = true`
- `balloon` → when `is_ballooning_allowed = true` and `even_pays = false`
- `staircase` → otherwise

The shape is determined by the creditor rules and is **not searched as a separate option**.

For each `k`:

1. Generate the creditor payment schedule while respecting all payment rules.
2. Allocate the program fee as early as possible.
3. Simulate the complete ledger.
4. Discard the candidate if it is not feasible.

Among all feasible candidates, choose the best one using this order:

1. **Collect the maximum possible program fee as early as possible.**
2. If tied, **keep earlier creditor payments as small as possible**, pushing larger payments toward the end.
3. If still tied, choose the **smallest `k`**.

### Program Fee Allocation

Program fees are allocated using a forward greedy approach. Starting from the first creditor payment date:

1. Calculate how much balance is available after that date's required transactions.
2. Collect as much of the remaining program fee as possible.
3. Move to the next eligible cadence date with any remaining fee.

The goal is always to collect the program fee at the **earliest possible date**.

For balloon and tiered schedules in particular, the payment generator should keep early creditor payments as low as the rules allow, leaving the maximum possible cash available to collect the program fee early.

No backtracking is required for fee allocation because delaying a fee payment cannot improve the outcome: available cash carries forward, so collecting an available fee earlier is always at least as good as collecting it later.

### Payment shape interpretation

- **Even** (`even_pays=true`): `offer_total // k`, with the remainder cents
  placed on the *last* payments (Binding Constraint 7). `k` is still chosen
  by the objective, not fixed.
- **Balloon** (`is_ballooning_allowed=true`): the first `k-1` payments sit at
  their position's floor (token/tier rules included); the final payment
  absorbs whatever remains. Rejected (that `k` is skipped) if the final
  payment would violate non-decreasing order or its own floor.
- **Staircase** (neither flag set): built as *(a) the first `k - L`
  positions at their own individual natural floor* — never forced onto a
  shared level — plus *(b) a trailing suffix of length `L` elevated to one
  uniform level that absorbs all remaining cash*. `L` is tried from `1` up to
  `k`, and the **smallest** `L` that (i) sums exactly, (ii) stays
  non-decreasing, and (iii) keeps the total distinct payment values within
  `max_segments` is used. Minimizing `L` means as many early positions as
  possible stay at their true floor, which is what "minimize early creditor
  outflow" means concretely — and it naturally produces a balloon-like final
  payment whenever `max_segments` allows it, without needing
  `is_ballooning_allowed`.

  Tier interaction: tiers already partition positions into natural floor
  groups (e.g. `[[7, 5000]]` → positions 1–6 at the base minimum, 7+ at
  5000); the staircase construction respects these as-is in the untouched
  prefix and only overrides the elevated suffix.

### Execution flow by scenario

`evaluate_offer(client, offer, rules)` always runs the same pipeline; what
changes per scenario is which branch/shape it lands in. General flow first,
then a concrete trace through each of the four example cases in `cases/`.

**General flow (every call):**

1. Compute `offer_total = round_half_up(settlement_pct × creditor_balance_cents)`
   and `program_fee = round_half_up(program_fee_pct × original_balance_cents)`
   (`domain/money.py`).
2. Generate the cadence — monthly dates from `first_payment_date` (or its
   default) up to and including the horizon (`domain/dates.py`).
3. Pick the shape once from the flags: `even_pays` → `"even"`,
   else `is_ballooning_allowed` → `"balloon"`, else `"staircase"`
   (`optimizer._build_shape`).
4. For every `k = 1..effective_max_k`: build that shape's payment sequence
   for `k` (`domain/schedules.py`), allocate the program fee as early as
   possible against it (`optimizer.allocate_fee_earliest`), then run the
   full ledger simulation (`domain/simulation.py::simulate`). A `k` that
   fails at any step (invalid sequence, fee can't be fully collected,
   balance goes negative) is simply dropped — not an error.
5. If at least one candidate survives step 4, pick the best one via the
   lexicographic comparator (`optimizer.select_best`) → build the
   `ScheduleRow`s → return `Result(feasible=True, ...)`.
6. If **no** candidate survives for **any** `k`, the offer is infeasible:
   run the lump-sum and monthly-increment binary searches
   (`domain/funds.py`), each repeatedly re-running steps 1–4 against an
   augmented ledger (one extra credit, or every future draft bumped) purely
   to ask "does *any* schedule become feasible?" — never recursing into
   funding math. Apply guardrails, return
   `Result(feasible=False, schedule=None, additional_funds=...)`.

### Alternatives considered

- **Brute-force cent-by-cent search** for schedules and funding minima —
  rejected: unnecessary given the exact-sum/floor/tier structure admits a
  much smaller, deterministic construction, and the assignment explicitly
  warns against brute-forcing every cent value.
- **Recursive additional-funds computation** (recomputing funding minima
  inside the funding search itself) — rejected per the spec's explicit
  warning; the funding search only asks "does *any* feasible schedule
  exist?", never "what funding does *this* infeasible case need?".
- **A formal `Protocol`-based loader port** — rejected; no second
  implementation of case loading exists anywhere in this assignment, so an
  interface would be abstraction with no consumer.

### Known edge cases

Covered by `tests/test_edge_cases.py` and friends: `offer_total == 0`;
`program_fee_pct == 0`; `bank_fee_cents == 0`; very large cent values (up to
10¹¹–10¹², verifying `Decimal`-based money math has no float drift);
first-payment date beyond the horizon (infeasible — no cadence date exists
at all); first-payment date exactly on the horizon (still valid, `k=1`
works); multiple ledger entries on the same date; a balance landing exactly
at zero; `max_segments == 1` (forces a flat/even-looking staircase); an
already-feasible offer (`additional_funds` is `null`); zero future drafts
for the monthly-increment search. Not otherwise handled: truly pathological
inputs like negative money fields are rejected at the JSON-loading boundary
with a `ValueError` (light validation, not a full schema validator) rather
than being simulated.

### Determinism & tie-breaking

Every search (candidate generation, fee allocation, lump-sum date ordering,
binary searches) iterates in a fixed, documented order with no randomness
and no reliance on set/dict iteration order for anything output-affecting,
so identical inputs always produce byte-identical output.
