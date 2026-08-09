# Specification: Settlement Feasibility & Fee Engine

## 1. Purpose

Build a production-quality Python implementation for the **Settlement Feasibility & Fee Engine** described in `assignment.md`.

The implementation must:

1. Determine whether a settlement offer is feasible using the client's escrow account and creditor rules.
2. Generate a valid payment schedule when feasible.
3. Optimize the schedule according to the assignment's objective:

   * **collect the program fee as early as possible**.
4. Report the payment shape used:

   * `"even"`
   * `"staircase"`
   * `"balloon"`
5. When infeasible, calculate the minimum additional funding required in:

   * lump-sum form;
   * uniform monthly-draft increment form.
6. Enforce the applicable guardrails.
7. Be deterministic, testable, and easy to reason about.

The implementation should prioritize **correctness, explicit modeling, edge-case handling, and test coverage** over unnecessary abstraction or feature breadth.

---

# 2. Source of Truth

`assignment.md` is the authoritative business specification.

Do not reinterpret hard requirements unless explicitly identified as ambiguous/open-ended in `assignment.md`.

When an aspect is intentionally open-ended, use the interpretation in this document and document it in `README.md`.

Do not hard-code behavior for a particular creditor or case.

All creditor-specific behavior must come from `creditor_rules.json`.

---

# 3. Expected Repository Structure

Use a clean structure similar to:

```text
.
├── assignment.md
├── specification.md
├── README.md
├── run.py
├── feasibility/
│   ├── __init__.py
│   ├── models.py
│   ├── dates.py
│   ├── money.py
│   ├── schedules.py
│   ├── simulation.py
│   ├── optimizer.py
│   ├── funds.py
│   └── engine.py
├── cases/
│   ├── case1_feasible_even/
│   │   ├── client.json
│   │   ├── offer.json
│   │   └── creditor_rules.json
│   └── ...
└── tests/
    ├── test_cases.py
    ├── test_dates.py
    ├── test_money.py
    ├── test_simulation.py
    ├── test_schedules.py
    ├── test_optimizer.py
    └── test_additional_funds.py
```

Do not create unnecessary modules if the existing repository already has an appropriate structure.

Before implementing, inspect the repository and reuse existing models/helpers where possible.

---

# 4. Core Domain Model

The implementation must conceptually model these entities.

## 4.1 Client

Fields:

```python
draft_amount_cents: int
draft_day: int
first_draft_date: date
last_draft_date: date
as_of_date: date
current_balance_cents: int
ledger: list[LedgerEntry]
```

Interpretation:

* `current_balance_cents` is the SDA balance at `as_of_date`.
* Ledger entries dated `<= as_of_date` are already reflected in this balance.
* Future ledger entries are committed and must be simulated.
* Future ledger debits/credits must not be modified.
* Drafts are represented by ledger credit entries.

---

## 4.2 LedgerEntry

```python
date: date
amount_cents: int
type: Literal["credit", "debit"]
```

Amounts should be non-negative magnitudes.

Do not represent debits as negative amounts inside the ledger model.

---

## 4.3 Offer

```python
creditor: str
creditor_balance_cents: int
original_balance_cents: int
settlement_pct: Decimal
first_payment_date: date | None
```

Compute:

```text
offer_total =
    round_half_up(
        settlement_pct * creditor_balance_cents
    )
```

---

## 4.4 CreditorRules

```python
max_terms: int
max_payments: int
min_payment_cents: int
max_token_pays: int
min_payment_tiers: list[tuple[int, int]]
even_pays: bool
is_ballooning_allowed: bool
max_segments: int
bank_fee_cents: int
program_fee_pct: Decimal
```

Maximum number of creditor payments:

```text
max_k = min(max_terms, max_payments)
```

---

# 5. Money Handling

All monetary values must remain integer cents.

Never use binary floating-point arithmetic for monetary calculations.

Use `Decimal` when percentages are involved.

Implement explicit round-half-up behavior.

For example:

```python
Decimal("0.5") -> 1
Decimal("1.5") -> 2
Decimal("2.5") -> 3
```

Do not use Python's built-in `round()` for business-rule rounding because it uses bankers rounding.

Create a reusable helper:

```python
round_half_up(value: Decimal) -> int
```

Use it for:

```text
offer_total
program_fee
monthly guardrail calculation
lump-sum guardrail calculation
```

---

# 6. Date Handling

Dates are calendar dates, not datetimes.

All scheduling must respect:

```text
horizon = last_draft_date
```

No generated transaction may occur after the horizon.

The horizon date itself is valid.

## 6.1 Draft dates

Drafts are already represented in the ledger.

Do not create duplicate draft credits.

The evaluator must use the ledger entries as the source of truth for committed drafts.

---

## 6.2 Payment cadence

Creditor payments and program-fee dates are based on `first_payment_date`.

If omitted:

```text
first_payment_date =
    end of month(first_draft_date)
```

If `first_payment_date` is the last day of its month:

```text
preserve end-of-month cadence
```

Example:

```text
Jan 31
Feb 28
Mar 31
Apr 30
...
```

If it is a mid-month date:

```text
preserve day-of-month and clamp to month length
```

Example:

```text
Jan 31 -> Feb 28 -> Mar 31
```

for a non-EOM interpretation only if the cadence originates from a 31st mid-month-style date.

Example for day 15:

```text
Jan 15 -> Feb 15 -> Mar 15
```

Use the existing date helpers in `feasibility/models.py` if available.

Write tests for:

* February;
* leap years;
* 30-day months;
* 31-day months;
* EOM cadence;
* mid-month cadence;
* horizon truncation.

---

# 7. Ledger Simulation

Create a single canonical simulation function.

Conceptually:

```python
simulate(
    client,
    generated_transactions
) -> SimulationResult
```

The simulator is the authoritative source for determining whether a schedule is financially feasible.

Do not duplicate balance-calculation logic across the optimizer.

---

## 7.1 Starting balance

Start from:

```text
client.current_balance_cents
```

Do not replay ledger entries dated `<= as_of_date`.

Only future ledger entries should be applied.

---

## 7.2 Same-day ordering

For every date:

1. Apply all credits.
2. Apply all debits.

This ordering is mandatory.

Example:

```text
2026-01-01:
    credit +20,000
    creditor debit -10,000
```

must result in:

```text
balance = previous_balance + 20,000 - 10,000
```

and not fail because the debit was processed first.

---

## 7.3 Generated transactions

Generated transactions include:

### Creditor payment

```text
debit = creditor_payment_cents
```

### Bank fee

```text
debit = bank_fee_cents
```

A bank fee exists on every date containing a creditor payment.

### Program fee

```text
debit = program_fee_cents
```

Program fee may be split over multiple cadence dates.

---

## 7.4 Negative-balance invariant

At every date after applying credits and debits:

```text
balance >= 0
```

If balance becomes negative at any point:

```text
feasible = False
```

Do not merely check the final balance.

---

# 8. Program Fee

Calculate total program fee once:

```text
program_fee_total =
    round_half_up(
        program_fee_pct * original_balance_cents
    )
```

The total must be collected completely by the horizon.

Constraints:

1. No program fee before the first creditor-payment date.
2. Program fee may be collected on the first creditor-payment date.
3. Program fee may be collected on later cadence dates.
4. A cadence date containing only program fee is a fee-only month.
5. Fee-only month has:

   * program fee;
   * no creditor payment;
   * no bank fee.
6. Program fee must sum exactly to `program_fee_total`.
7. Program fee cannot be negative.

---

# 9. Payment Count

Choose:

```text
1 <= k <= min(max_terms, max_payments)
```

Payments must occupy consecutive cadence dates.

No gaps are allowed.

Every payment date must be:

```text
<= horizon
```

Therefore:

```text
k <= number_of_cadence_dates_available_before_or_on_horizon
```

The effective maximum is:

```text
effective_max_k =
    min(
        max_terms,
        max_payments,
        cadence_dates_available
    )
```

A candidate `k` is valid only if:

```text
1 <= k <= effective_max_k
```

---

# 10. Payment Floors

For payment position `i`, where `i` is 1-based:

```text
floor(i) =
    max(
        min_payment_cents,
        applicable_tier_floor(i)
    )
```

Tier example:

```json
"min_payment_tiers": [
    [7, 5000]
]
```

means:

```text
payments 1-6: floor = base minimum
payment 7+:   floor = max(base minimum, 5000)
```

If multiple tiers apply, use the largest applicable tier.

Example:

```text
[[3, 3000], [7, 5000], [10, 7000]]
```

results in:

```text
1-2  -> base
3-6  -> 3000
7-9  -> 5000
10+  -> 7000
```

---

# 11. Token Pay Rule

A token pay is a payment exactly equal to:

```text
min_payment_cents
```

At most:

```text
max_token_pays
```

payments may equal this value.

Any later payment that is subject to the token restriction must be:

```text
> min_payment_cents
```

Important:

* A payment greater than the base minimum is not a token pay.
* Tier floors can make token payments impossible at later positions.
* Token counting is based on actual generated payment amounts.
* The schedule must remain non-decreasing.

The implementation should make token validity explicit rather than relying accidentally on another constraint.

---

# 12. Exact Sum

For every valid schedule:

```text
sum(creditor_payments) == offer_total
```

This must be checked exactly in integer cents.

Never tolerate rounding differences.

If exact sum cannot be achieved for a candidate `k`, reject that candidate.

---

# 13. Non-Decreasing Payments

For non-even schedules:

```text
payment[i] >= payment[i-1]
```

for all `i > 1`.

This applies to all staircase and balloon schedules.

The final payment of a balloon is expected to be greater than or equal to previous payments.

---

# 14. Even Payment Shape

If:

```text
even_pays == True
```

the selected shape must be:

```text
pay_shape_used = "even"
```

For a selected `k`:

```text
base = offer_total // k
remainder = offer_total % k
```

Generate:

```text
[
    base,
    ...
    base,
    base + 1,
    ...
    base + 1
]
```

with the remainder cents assigned to the **latest** payments.

Example:

```text
offer_total = 100
k = 3

[33, 33, 34]
```

not:

```text
[34, 33, 33]
```

Validate:

* exact sum;
* floor constraints;
* token constraints;
* non-negative balance;
* horizon.

Do not treat `even_pays` as "approximately equal." It means equal/as-equal-as-possible according to the explicit remainder rule.

---

# 15. Balloon Shape

If:

```text
is_ballooning_allowed == True
```

the optimizer may produce:

```text
pay_shape_used = "balloon"
```

Interpret ballooning as:

```text
early payments are as small as permitted,
final payment absorbs all remaining creditor balance.
```

For a selected `k`:

1. Generate the smallest feasible prefix payments according to:

   * floors;
   * token constraints;
   * non-decreasing constraint.
2. Set the final payment to:

```text
offer_total - sum(prefix_payments)
```

3. Validate the final payment against:

   * applicable floor;
   * non-decreasing constraint;
   * exact sum.
4. Validate full ledger feasibility.

Do not generate an arbitrary large final payment merely because ballooning is allowed.

The balloon should be the natural result of minimizing early creditor outflow.

If the minimum prefix makes the final payment invalid, reject that candidate and search for another valid prefix.

---

# 16. Staircase Shape

If:

```text
even_pays == False
is_ballooning_allowed == False
```

use:

```text
pay_shape_used = "staircase"
```

The schedule must:

* be non-decreasing;
* respect floors;
* respect token limits;
* sum exactly to offer total;
* contain at most `max_segments` distinct payment values.

The staircase shape must be **derived from the optimization objective**, not hard-coded as a particular number of steps.

---

# 17. Max Segments

For non-even, non-balloon schedules:

```text
len(set(payments)) <= max_segments
```

A schedule violating this is invalid.

Do not count repeated equal payments as multiple segments.

Examples:

```text
[100, 100, 100, 200, 200]
```

has:

```text
2 segments
```

while:

```text
[100, 150, 200]
```

has:

```text
3 segments
```

---

# 18. Optimization Objective

The objective is:

> Collect the program fee as early as possible.

This should be modeled explicitly rather than merely choosing the first feasible schedule.

The fundamental economic interpretation is:

```text
Early cash should first satisfy the minimum required creditor outflow,
allowing the program fee to be collected as early as possible.
```

Therefore, among otherwise valid schedules, prefer schedules that:

1. collect more program fee earlier;
2. minimize early creditor payments;
3. defer larger creditor payments toward later dates;
4. satisfy all creditor shape constraints.

---

# 19. Recommended Optimization Model

Use a deterministic lexicographic objective.

For a candidate schedule define:

```text
fee_collection_dates
```

and compare schedules by:

### Priority 1 — earliest fee collection

Prefer the schedule with the earliest cumulative fee collection.

Conceptually maximize:

```text
cumulative_fee_collected(t)
```

for every cadence date, lexicographically from earliest to latest.

Equivalent practical representation:

```text
fee_vector = [
    fee_collected_at_date_1,
    fee_collected_at_date_2,
    ...
]
```

Prefer the lexicographically largest early-fee vector.

### Priority 2 — minimize early creditor outflow

If fee timing is equivalent, prefer:

```text
smaller payment_1
```

then:

```text
smaller payment_2
```

and so on.

This directly represents the assignment's statement that larger creditor payments should be deferred.

### Priority 3 — deterministic tie-breaking

Use a deterministic tie-breaker such as:

```text
smaller k
```

or another documented deterministic rule.

The README must state the exact tie-breaking strategy.

---

# 20. Important Optimization Insight

Do not assume that maximizing `k` is always optimal.

A larger number of payments:

* increases bank fees;
* may increase the number of required minimum payments;
* changes the available cadence;
* may allow smaller early creditor payments;
* may make the offer infeasible.

Therefore evaluate possible `k` values.

For each:

```text
k = 1 ... effective_max_k
```

generate valid candidate schedules and compare them using the objective.

---

# 21. Candidate Generation Strategy

Because the assignment is explicitly scoped to approximately 5–6 hours, correctness is more important than building an unnecessarily sophisticated mathematical optimizer.

Use a deterministic search/constructive approach.

Recommended approach:

## Step 1

Generate all feasible payment counts:

```text
k = 1 ... effective_max_k
```

## Step 2

For each `k`, construct the payment sequence that minimizes early creditor payments while satisfying:

* floors;
* token rules;
* tiers;
* non-decreasing rule;
* exact sum;
* segment cap;
* even/balloon rules.

## Step 3

For each payment sequence, determine the earliest possible program-fee collection.

## Step 4

Simulate the entire ledger.

## Step 5

Reject infeasible candidates.

## Step 6

Choose the candidate with the best objective score.

Avoid brute-forcing arbitrary cent values.

Payment values may be large, so search should operate over **structural levels / constraints**, not every possible cent amount.

---

# 22. Recommended Staircase Construction

For staircase schedules, model the payment sequence as:

```text
level_1 repeated n_1 times
level_2 repeated n_2 times
...
level_m repeated n_m times
```

where:

```text
m <= max_segments
n_1 + ... + n_m = k
level_1 < level_2 < ... < level_m
```

The first level should be as low as possible while still allowing the remaining amount to be distributed among later payments.

For each candidate segmentation:

1. establish minimum permissible values;
2. calculate the remaining amount;
3. allocate excess toward later levels;
4. maintain non-decreasing order;
5. ensure the number of distinct levels does not exceed `max_segments`;
6. validate exact sum.

Prefer excess allocation to later payments because this delays creditor cash outflow.

---

# 23. Fee Allocation Strategy

Once a creditor-payment schedule is selected, allocate the program fee as early as possible.

For each cadence date starting from the first creditor-payment date:

```text
available_balance_after_required_debits
```

Determine how much program fee can safely be collected while keeping:

```text
balance >= 0
```

The fee allocation should:

* maximize fee collected on the earliest date;
* continue to later cadence dates only when necessary;
* collect the entire fee by the horizon.

This means fee allocation itself is an optimization problem, but it is straightforward once the creditor schedule is fixed.

---

# 24. Fee and Bank-Fee Interaction

On a creditor-payment date:

```text
creditor payment
+
bank fee
+
program fee
```

are all debits.

The bank fee must always be charged when a creditor payment exists.

On a fee-only date:

```text
program fee only
```

and:

```text
bank fee = 0
```

Never charge a bank fee merely because a program fee is collected.

---

# 25. Feasibility Evaluation

Create one central function:

```python
evaluate_offer(
    client,
    offer,
    rules
) -> Result
```

It should:

1. validate/normalize inputs;
2. calculate offer total;
3. calculate program fee;
4. generate cadence;
5. determine feasible payment counts;
6. generate candidate schedules;
7. allocate program fee;
8. simulate ledger;
9. optimize;
10. return `Result`.

The returned result must match the structure required by `assignment.md`.

---

# 26. Result Model

Expected shape:

```python
{
    "feasible": bool,
    "pay_shape_used": "even" | "staircase" | "balloon" | None,
    "schedule": list | None,
    "additional_funds": dict | None
}
```

Schedule row:

```python
{
    "date": "YYYY-MM-DD",
    "creditor_payment_cents": int,
    "program_fee_cents": int,
    "bank_fee_cents": int,
    "balance_cents": int
}
```

Only include used/generated cadence dates in the schedule.

Do not create unnecessary zero-value rows unless the existing `Result` model requires them.

---

# 27. Schedule Balance Semantics

`balance_cents` must be the actual running SDA balance after all transactions represented by that row/date.

For a date:

```text
credits
- creditor payment
- bank fee
- program fee
```

must produce the reported balance.

The schedule must be internally self-consistent.

The final balance does not have to be zero unless the inputs/rules imply that it should be.

---

# 28. Additional Funds

If no feasible schedule exists:

```python
feasible = False
schedule = None
```

Then independently compute:

1. minimum lump sum;
2. minimum uniform monthly increment.

These must not reuse a result from the other method.

---

# 29. Lump-Sum Minimum

The lump sum is:

> the smallest single additional credit that makes some valid schedule feasible.

The placement date may be any date:

```text
<= horizon
```

An earlier placement is weakly more useful than a later placement.

Therefore:

1. Search candidate placement dates chronologically.
2. For each date determine the minimum amount required.
3. Find the globally smallest amount.
4. If multiple dates require the same minimum amount, choose the earliest date.

Do not assume the best placement is necessarily `as_of_date`.

The assignment specifically permits a chosen future date.

However, because earlier funding is weakly more useful, the earliest date with the globally minimum amount is the preferred deterministic result.

---

# 30. Lump-Sum Search

Use monotonicity.

For a fixed placement date:

```text
if L makes the problem feasible,
then any L' > L also makes it feasible.
```

Therefore use binary search for the minimum `L`.

For each candidate `L`:

1. add a synthetic credit;
2. run the complete `evaluate` logic for feasibility;
3. do not recursively calculate additional funds;
4. only determine whether a valid schedule exists.

Create an internal function such as:

```python
find_feasible_schedule_with_extra_funding(...)
```

to avoid recursion.

---

# 31. Monthly Increment Minimum

The monthly increment means:

```text
X
```

is added to every future draft:

```text
draft_date > as_of_date
```

The number of affected drafts is:

```text
N
```

where `N` is the number of future drafts through the horizon.

Important:

* Do not add X to historical drafts.
* Do not alter existing ledger amounts in place.
* Treat the increment as an additional credit on each future draft date or construct an adjusted future cash-flow view.

The objective is to find the smallest integer:

```text
X >= 0
```

that makes a valid schedule feasible.

---

# 32. Monthly Increment Search

Feasibility is monotonic with respect to X.

Therefore:

1. test `X = 0`;
2. if infeasible, find an upper bound;
3. binary search for the minimum feasible integer X.

The search should return the exact cent value.

Do not search in dollars or floating-point values.

---

# 33. Guardrails

## Monthly Increment

Reject if:

```text
X > max(
    10000,
    round_half_up(0.40 * draft_amount_cents)
)
```

If rejected:

```text
within_guardrail = false
reason = explanatory message
```

The reason should contain the actual limit and computed X.

Example:

```text
"Required monthly increment of 12000 cents exceeds the guardrail of 10000 cents."
```

---

## Lump Sum

Reject if:

```text
L > round_half_up(0.65 * offer_total)
```

If rejected:

```text
within_guardrail = false
```

with a clear reason.

If within the guardrail:

```text
within_guardrail = true
reason = ""
```

The guardrail is a reporting constraint; it does not change the mathematically calculated minimum.

---

# 34. Additional Funds Output

Use:

```json
{
  "lump_sum": {
    "amount_cents": 10000,
    "date": "2026-01-01",
    "within_guardrail": true,
    "reason": ""
  },
  "monthly_increment": {
    "amount_cents": 2500,
    "num_drafts": 5,
    "within_guardrail": true,
    "reason": ""
  }
}
```

If no finite funding amount can make the case feasible under the rules, represent this explicitly and document the chosen representation.

Do not silently return a fake large amount.

---

# 35. Important Edge Cases

The implementation must explicitly handle:

### Money

* `.5` rounding;
* zero values;
* offer total of zero;
* program fee of zero;
* bank fee of zero;
* very large integer amounts.

### Dates

* first payment after horizon;
* first payment exactly on horizon;
* February;
* leap year;
* EOM cadence;
* mid-month cadence;
* cadence day 29/30/31;
* draft and payment on the same date;
* multiple ledger entries on the same date.

### Ledger

* multiple credits on same day;
* multiple debits on same day;
* committed debit before future draft date;
* balance exactly zero;
* balance becoming negative;
* future ledger entries that cannot be modified.

### Payments

* `k = 1`;
* `k = max_payments`;
* `k = max_terms`;
* offer total below minimum payment;
* offer total exactly equal to minimum;
* token limit of zero;
* token limit greater than k;
* tiers beginning at payment 1;
* overlapping tiers;
* tier floor larger than offer total;
* exact divisibility for even payments;
* remainder for even payments;
* max_segments = 1;
* max_segments >= k.

### Fees

* fee exactly fits available cash;
* fee requires multiple cadence dates;
* fee can be fully collected on first payment date;
* fee cannot be collected until later;
* fee-only month;
* fee cannot be collected before horizon.

### Funding

* already feasible => additional_funds must be `null`;
* infeasible with minimum lump exactly equal to guardrail;
* minimum lump one cent above guardrail;
* monthly increment exactly at guardrail;
* monthly increment one cent above guardrail;
* increment arrives too late to help an earlier payment.

---

# 36. Testing Requirements

At minimum, implement tests for:

## Shape

* even payment schedule;
* staircase schedule;
* balloon schedule.

## Payment rules

* token-pay limit;
* token payments cannot exceed max count;
* tier floors;
* multiple tiers;
* non-decreasing payments;
* exact sum;
* max_segments.

## Ledger

* same-day credits before debits;
* exact zero balance;
* negative balance;
* committed future ledger entries;
* multiple same-day entries.

## Dates

* EOM cadence;
* mid-month cadence;
* clamping;
* leap year;
* horizon inclusion;
* payment beyond horizon rejected.

## Fees

* program fee calculated correctly;
* half-up rounding;
* fee cannot be collected before first creditor payment;
* fee can be collected on first payment date;
* fee-only date has no bank fee;
* bank fee charged on every creditor payment.

## Funding

* minimum lump sum;
* minimum monthly increment;
* binary-search correctness;
* guardrail pass;
* guardrail fail.

---

# 37. Property / Invariant Tests

Where practical, add invariant-style tests.

For every returned feasible schedule:

```python
assert sum(row["creditor_payment_cents"] for row in schedule) == offer_total
```

and:

```python
assert all(
    row["balance_cents"] >= 0
    for row in schedule
)
```

and:

```python
assert total_program_fee_collected == program_fee_total
```

and:

```python
assert every_payment_date <= horizon
```

and:

```python
assert every_payment_date is a valid cadence date
```

For staircase:

```python
assert len(set(payments)) <= max_segments
```

For all non-even schedules:

```python
assert payments == sorted(payments)
```

---

# 38. CLI

`run.py` must support:

```bash
python run.py cases/case1_feasible_even
```

The command should:

1. read:

   * `client.json`;
   * `offer.json`;
   * `creditor_rules.json`;
2. construct the domain models;
3. call:

```python
evaluate_offer(client, offer, rules)
```

4. print a JSON representation of `Result.to_dict()`.

The CLI must return a non-zero exit code for malformed input or unexpected application errors.

Do not print debug logs into stdout because stdout should contain the machine-readable result.

---

# 39. Input Validation

Validate obvious invalid input.

Examples:

* negative monetary values where prohibited;
* invalid transaction type;
* invalid dates;
* invalid percentages;
* `max_payments < 1`;
* `max_terms < 1`;
* `min_payment_cents < 0`;
* invalid tier positions;
* invalid `draft_day`.

Do not over-engineer validation that is not necessary for the assignment.

Clearly distinguish:

```text
invalid input
```

from:

```text
valid but infeasible offer
```

---

# 40. Determinism

The same inputs must always produce the same output.

Do not use:

* random search;
* unordered iteration where output selection depends on ordering;
* non-deterministic optimization.

Document tie-breaking behavior in `README.md`.

---

# 41. Performance

The expected cases are small.

Prioritize:

```text
correctness > readability > optimization
```

However:

* do not brute-force every possible cent amount;
* use binary search for funding minima;
* use structural payment generation;
* avoid repeated full simulations where avoidable;
* cache cadence and static calculations when useful.

A normal assignment-sized case should complete quickly.

---

# 42. Separation of Concerns

Keep these responsibilities separate:

### `money.py`

* Decimal handling;
* round-half-up;
* percentage calculations.

### `dates.py`

* cadence generation;
* EOM logic;
* month clamping.

### `simulation.py`

* ledger aggregation;
* same-day ordering;
* balance simulation.

### `schedules.py`

* payment floor calculations;
* token validation;
* even schedule generation;
* balloon generation;
* staircase generation.

### `optimizer.py`

* candidate generation;
* objective comparison;
* shape selection.

### `funds.py`

* lump-sum minimum;
* monthly increment minimum;
* binary searches;
* guardrails.

### `engine.py`

* orchestration;
* public `evaluate_offer`.

The exact module boundaries may be simplified if the repository's existing structure makes another organization clearer.

---

# 43. README Requirements

The README must explain:

## Approach

Explain:

* domain model;
* ledger simulation;
* payment candidate generation;
* optimization;
* funding search.

## Payment Shape Interpretation

Explicitly explain why:

* even schedules are handled as specified;
* balloon schedules minimize early payments and defer the remainder;
* staircase schedules minimize early creditor outflow while respecting `max_segments`.

## Objective

Explain how:

```text
"collect program fee as early as possible"
```

was converted into a deterministic optimization criterion.

## Assumptions

List all assumptions made for ambiguous areas.

Especially:

* balloon + token-pay interaction;
* balloon + tiers;
* staircase step placement;
* tie-breaking between equally optimal schedules;
* impossible funding scenarios.

## Alternatives Considered

Briefly discuss alternatives such as:

* brute-force search;
* dynamic programming;
* integer programming;
* greedy construction;
* lexicographic optimization.

Explain why the chosen approach is appropriate for the assignment.

## Known Edge Cases

Document any limitations or deliberately unsupported pathological inputs.

---

# 44. Implementation Workflow

Before coding:

1. Inspect all existing repository files.
2. Read `assignment.md` completely.
3. Inspect existing `feasibility/models.py` and `feasibility/engine.py`.
4. Inspect existing cases.
5. Inspect existing tests.
6. Preserve compatible existing APIs where practical.

Then implement in this order:

### Phase 1 — Foundations

* money helpers;
* date/cadence helpers;
* models;
* ledger simulation.

### Phase 2 — Payment validation

Implement:

* floors;
* tiers;
* token rules;
* exact sum;
* non-decreasing rule;
* segment validation.

### Phase 3 — Shapes

Implement:

* even;
* staircase;
* balloon.

### Phase 4 — Fee allocation

Implement earliest-feasible program fee allocation.

### Phase 5 — Optimization

Implement:

* candidate payment counts;
* candidate comparison;
* deterministic selection.

### Phase 6 — Additional funds

Implement:

* lump-sum search;
* monthly increment search;
* guardrails.

### Phase 7 — Tests

Add the required edge-case and invariant tests.

### Phase 8 — CLI / README

Verify:

```bash
python run.py cases/case1_feasible_even
```

and document the design.

---

# 45. Definition of Done

The implementation is complete only when all of the following are true:

* [ ] `evaluate_offer()` exists and returns the required `Result`.
* [ ] Money uses integer cents.
* [ ] Percentage calculations use explicit half-up rounding.
* [ ] Cadence is independent of draft dates.
* [ ] Horizon is enforced.
* [ ] Same-day credits occur before debits.
* [ ] Existing ledger entries are respected.
* [ ] Creditor payments are consecutive.
* [ ] Exact creditor sum is enforced.
* [ ] Payments are non-decreasing.
* [ ] Token-pay limits are enforced.
* [ ] Tier floors are enforced.
* [ ] Bank fees are correctly applied.
* [ ] Program fee timing is enforced.
* [ ] Fee-only months have no bank fee.
* [ ] Even payment remainder is placed on latest payments.
* [ ] Ballooning is only used when permitted.
* [ ] Staircase respects `max_segments`.
* [ ] Program fee is optimized to be collected as early as possible.
* [ ] Feasibility checks the balance at every date.
* [ ] Minimum lump sum is calculated.
* [ ] Minimum monthly increment is calculated.
* [ ] Both funding calculations are independent.
* [ ] Guardrails are reported correctly.
* [ ] Required tests exist and pass.
* [ ] CLI works.
* [ ] README documents the modeling decisions.
* [ ] Output is deterministic.
* [ ] No creditor-specific hard-coding exists.

---

# 46. Final Engineering Principle

Do not try to guess a hidden expected formula for the payment shape.

The assignment explicitly says there is no single correct shape formula.

Instead:

1. model the hard constraints precisely;
2. model the economic objective explicitly;
3. generate valid candidates;
4. optimize against the stated objective;
5. simulate the actual ledger;
6. return only schedules that survive the complete simulation;
7. document the interpretation clearly.

**Correctness of the financial simulation and clarity of the reasoning are more important than algorithmic sophistication.**
