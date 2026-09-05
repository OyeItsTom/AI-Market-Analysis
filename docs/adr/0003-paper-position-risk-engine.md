# ADR 0003 — Paper position and risk engine

- **Status:** accepted
- **Date:** 2026-09-05
- **Phase:** 5 (Paper position / risk engine)

## Problem

Phases 1–4 produce research classifications and measure what followed them.
Nothing yet represents a *position*. A local dashboard will eventually let a
human record hypothetical paper actions and see their exposure.

The danger in building that is a single silent step: something, somewhere,
turning `BULLISH` into `BUY`. Once that step exists, four phases of separation
between evidence and action collapse, and every later result is contaminated by
a mapping nobody chose deliberately.

## Decisions

### 1. Research and paper actions are separated structurally, not by convention

`src/portfolio` imports **nothing** from `src.strategies` or `src.evaluation`.
`ResearchState` is not in scope, so no function in the package can branch on a
classification — this is an absence of vocabulary, not a rule to be reviewed.
An AST test enforces it.

Research linkage travels as `ResearchProvenance`: plain identifier strings,
optional, preserved for audit and never interpreted. A paper position with no
research behind it is an ordinary case, because a human idea is a first-class
input.

*Rejected:* importing `ResearchState` for a "convenience" mapping.

### 2. Long-only; `OPEN_SHORT` is not representable

`PaperAction` is exactly `OPEN_LONG` and `CLOSE`. **`BEARISH ≠ SHORT`.**
Shorting drags in borrow availability, borrow cost, unbounded loss and margin —
none of which this system models. Adding `OPEN_SHORT` later is additive.

*Rejected:* a `direction` field, which would make a short *rejectable* rather
than *impossible*.

### 3. Two intent records, not one

`OpenLongIntent` and `CloseIntent` are separate frozen records. A `CloseIntent`
has no `symbol` and no `notional` **attribute at all**, so a close cannot claim
a size or symbol that disagrees with the position it targets — the position
stays authoritative.

*Rejected:* one record with optional fields. That makes the same guarantee a
validation rule instead of a structural impossibility.

### 4. Notional in `Decimal`, floats rejected rather than converted

Sizing is notional, so exposure aggregates without any price. Verified: in
binary floats `0.1 + 0.2 == 0.30000000000000004`, so a float ledger **rejects**
an intent that exactly meets a `0.3` limit. `Decimal` is standard library.

A `float` argument raises rather than being converted, because `Decimal(0.1)`
carries the binary artefact into the ledger and looks correct while doing it.

### 5. Exposure only — no cash, no prices, no P&L

No cash balance, no NAV, no entry/exit/reference/market price, no realised or
unrealised result, no costs, no slippage.

A cash ledger would have to return cash "± hypothetical P&L" on close, which
*is* P&L. Storing an entry and an exit price puts a cost-free, unlabelled
return one subtraction away.

**Phase 4's `NEXT_BAR_OPEN` is deliberately not reused.** It is an *evaluation*
convention for measuring what followed an observation; silently adopting it as
a paper entry price would fabricate execution semantics.

### 6. Immutable snapshots with functional application

`portfolio.apply(intent, policy) -> (new_portfolio, decision)`. The receiver is
never modified, which makes "a rejection changed nothing" provable by comparing
two values.

Exposure and open count are **computed properties**, never stored totals: a
cached total is a conservation invariant waiting to be violated.

*Rejected:* a mutable portfolio (puts state corruption one bug away) and full
event sourcing (more machinery than a single-user research tool needs).

### 7. Inclusive limits; closing is risk-reducing

Rejection requires strictly exceeding a limit. "Maximum 1000" that refuses 1000
is a surprising contract, and `Decimal` makes the boundary exact.

A valid **close is never rejected for exposure reasons**. Refusing to let
someone reduce exposure because their exposure is too high would trap a
portfolio in the state the limit exists to prevent. Structural problems —
unknown target, already closed, close before open — still raise.

### 8. Rejected intents are not marked processed

An **approved** intent id is recorded and cannot be replayed, so a retry never
doubles exposure. A **rejected** intent id is *not* recorded, so the same
conceptual intent can be reconsidered after the human closes something or the
policy changes — that is the expected workflow.

Limitation: nothing authenticates an intent id against its *content*. Two
different intents reusing one id are indistinguishable. That belongs to a
persistence layer, which Phase 5 does not have.

### 9. Structural invalidity and policy rejection are different outcomes

Malformed size, naive timestamp, unknown target, duplicate or recycled id →
**raise**. A well-formed intent a limit declines → `RiskDecision.REJECTED` with
reason codes. Domain corruption is never reported as a policy outcome, and a
policy outcome never raises.

### 10. A decision records the intent and the policy that produced it

`RiskDecision` carries `intent_id` and `policy_fingerprint`, both required.
An outcome plus reason codes is not a sufficient audit record: an archived
`APPROVED` says a limit was satisfied without saying which intent was judged,
or whether the limits in force were strict or permissive. Rejections are
already legible from their reason codes; approvals are the case that needs the
provenance, and they are the majority.

The fingerprint canonicalises `Decimal` limits through an exponent form
(`1E2`) derived structurally from `as_tuple()`, not through `normalize()` and
fixed-point rendering. `Decimal` admits exponents far past any plausible
limit, so fixed point makes the canonical string grow with magnitude rather
than with significant digits, and `normalize()` raises `decimal.Overflow`
beyond the context `Emax` — meaning a policy that constructed successfully
could fail to fingerprint itself. Readability of the canonical string is not a
requirement; it is hash input.

Canonical reason-code ordering is enforced in `RiskDecision.__post_init__`
rather than only in the evaluator, so the documented order is a property of the
type rather than of one code path.

### 11. Exposure arithmetic runs in a pinned decimal context

Choosing `Decimal` over `float` (decision 4) is necessary for exact limit
comparisons but not sufficient: `decimal` precision is process-global mutable
state. A narrowed ambient precision rounds an exposure sum down and approves an
intent that genuinely breaches a limit, and an armed `Inexact` or `Overflow`
trap turns a risk check into an exception. Neither failure originates in this
module, and both defeat the guarantee decision 4 exists to provide.

Exposure summation and the total-exposure comparison run in a module-owned
context (maximum precision, widest exponent range, no traps) rather than the
inherited one. The engine's arithmetic is then a function of its inputs alone.

### 12. Deferred

`SimulationPolicy`, persistence, concurrency, shorting, cash, and every form of
economic performance.

## Consequences

- A classification cannot become an action, by construction.
- Exposure arithmetic is exact at limit boundaries.
- The portfolio is a value; stale snapshots are the caller's concern.
- Exposure is **nominal** — not marked to market, because there are no prices.
- Risk rules are portfolio-local: no correlation, sector or drawdown limits are
  expressible.

## Future simulation should not reuse `PaperIntent`

A `PaperIntent` asserts *a human chose this*. A simulated action asserts *a
policy generated this*. Sharing the record would make provenance unanswerable
and let one type carry two incompatible claims. A future simulation layer may
reuse `RiskPolicy` — a limit is a limit — but should have its own action
records.
