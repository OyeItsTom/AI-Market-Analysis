# Phase 5 — Paper position and risk engine

Written for an engineer who will build the local dashboard on this. Read
`docs/research_framework.md` (Phase 3) and `docs/research_evaluation.md`
(Phase 4) first, then `docs/adr/0003-paper-position-risk-engine.md`.

> **Paper only.** There is no brokerage, no order, no execution, no account and
> no money anywhere in this package. Nothing here is a performance claim.

---

## 1. What this is

```
explicit PaperIntent → structural validation → RiskPolicy → RiskDecision
                                                          → new PaperPortfolio
```

It records *hypothetical exposure* a human chose to note down, and enforces
deterministic limits on new exposure.

## 2. Research classifications do not create paper actions

**`BULLISH` does not mean buy. `BEARISH` does not mean sell or short.
`NEUTRAL` does not mean close.**

This is structural. `src/portfolio` imports nothing from `src.strategies` or
`src.evaluation`, so `ResearchState` is not in scope and no function here can
branch on one. An AST test enforces it.

"Bullish research and no paper position" is the ordinary state, not a special
case that needed handling.

## 3. Manual intent

A `PaperIntent` means *a human explicitly recorded this hypothetical action*.
There is no `SimulationPolicy` in Phase 5 — mapping classifications to actions
under an experimental policy is a different workflow, and conflating the two
would make later results impossible to attribute.

## 4. Long-only

`PaperAction` is exactly `OPEN_LONG` and `CLOSE`. `OPEN_SHORT` **does not
exist** — a short is not representable, not merely rejected. Shorting needs
borrow availability, borrow cost, unbounded loss and margin, none of which this
system models.

## 5. Two intent records

| | `OpenLongIntent` | `CloseIntent` |
|---|---|---|
| identity | `intent_id`, `position_id` | `intent_id`, `target_position_id` |
| sizing | `symbol`, `notional` | **absent** |
| timing | `intent_created_at` | `intent_created_at` |
| research | optional `ResearchProvenance` | — |

A `CloseIntent` has no `symbol` or `notional` **attribute at all**, so it cannot
assert a size or symbol that disagrees with the position it closes. The
position stays authoritative.

## 6. Notional in `Decimal` — floats are rejected, not converted

Exposure is a notional amount, which aggregates without needing any price.

```python
notional=Decimal("1000")   # correct
notional=1000.0            # raises IntentError
```

Why it matters: in binary floats `0.1 + 0.2 == 0.30000000000000004`, so a float
ledger **rejects an intent that exactly meets a 0.3 limit**. `Decimal` makes
the boundary exact. A `float` raises rather than being converted, because
`Decimal(0.1)` carries the artefact into the ledger while looking correct.

## 7. No prices, no cash, no P&L

No entry, exit, reference, fill or market price. No cash, NAV, realised or
unrealised result, costs, slippage, equity curve, drawdown or Sharpe.

**Phase 4's `NEXT_BAR_OPEN` is not reused here.** It is an *evaluation*
convention for measuring what followed an observation; adopting it as a paper
entry price would fabricate execution semantics the data cannot support.

## 8. Identifiers and timestamps are caller-supplied

No `uuid4()`, no clock. `position_id` is supplied on open, so a retry cannot
silently create a second position. Timestamps must be timezone-aware; naive
ones are refused rather than assumed, matching the Phase 1 invariant.
`closed_at` comes from the closing intent and may not precede `opened_at`.

Symbols follow the Phase 1 contract — stripped and upper-cased, as `MarketBar`
does. That is an existing repository behaviour, not a new rule invented here.

## 9. Position state machine

`OPEN → CLOSED`. Nothing else. `PENDING`/`FILLED`/`PARTIALLY_FILLED`/
`CANCELLED` model an order lifecycle at a venue, and including them is how a
paper domain drifts into looking like an execution system.

Closed positions are **retained** — deleting them would erase the audit trail —
and contribute exactly zero to open exposure.

## 10. Risk policy

Every field must be given; there is **no default policy**, because one that
silently permits everything looks like risk control while being none.

| Field | Meaning |
|---|---|
| `max_notional_per_position` | largest single paper position |
| `max_total_notional` | largest aggregate open exposure |
| `max_open_positions` | most simultaneous open positions (≥ 1) |
| `allow_duplicate_symbol` | whether a symbol may be opened twice while open |

Identity: `canonical_form` → SHA-256 → 16 hex, following the Phase 3/4 pattern.
Never `hash()`. Semantically equal limits fingerprint identically —
`Decimal("1000")`, `Decimal("1000.00")` and `Decimal("1.000E+3")` are the same
policy, because a policy is not changed by how its limit was typed.

### Exposure arithmetic is pinned, not inherited

`Decimal` makes limit comparisons exact, but exactness is a property of the
arithmetic *context*, not of the type. The `decimal` context is process-global
and any library in the process can narrow it. Under `getcontext().prec = 4`,
`Decimal("999.999999999") + Decimal("0.5")` rounds to exactly `1000`, so an
intent whose true total exposure is `1000.499999999` would satisfy a `1000`
limit — a silent breach, produced by code that never touched this engine.

Exposure summation and the total-exposure comparison therefore run inside a
context the engine pins itself: maximum precision, widest exponent range, and
**no traps**, so a caller who has armed `Inexact` or `Overflow` cannot convert
a risk check into an exception. Reported exposure is likewise unrounded, so
`total_open_notional` never understates what is open.

## 11. Limits are inclusive

An intent **exactly at** a limit is APPROVED; only strictly exceeding it is
rejected. "Maximum 1000" that refuses 1000 is a surprising contract, and with
`Decimal` the boundary is exact so there is no floating-point excuse.

## 12. Closing is risk-reducing

A structurally valid close is **never rejected for exposure reasons** — not
when total exposure is at its limit, not when the open-position limit is
reached, not when duplicate symbols are forbidden. Refusing to let someone
reduce exposure because their exposure is too high would trap a portfolio in
the state the limit exists to prevent.

Structural problems still raise: unknown target, already closed, close before
open, duplicate intent id.

## 13. Risk decisions

`APPROVED` / `REJECTED` with reason codes from a closed vocabulary:
`POSITION_LIMIT`, `TOTAL_EXPOSURE_LIMIT`, `OPEN_POSITION_LIMIT`,
`DUPLICATE_SYMBOL`. No free-form text.

**Every applicable rule is evaluated** — the engine does not stop at the first
violation — and codes are returned in a fixed canonical order, so a dashboard
can show everything wrong at once and a test can pin the sequence.

An approval carries **no** reason codes; a rejection carries at least one.
Both invariants are enforced at construction.

Canonical ordering is enforced *at construction*, not only by the evaluator.
A `RiskDecision` built directly from unordered or duplicated codes is
normalised to the canonical sequence with duplicates collapsed, so the
documented ordering holds for every decision regardless of how it was made.

### The decision names what it judged

A decision carries `intent_id` and `policy_fingerprint` alongside its outcome.
Without both, an archived `APPROVED` record is not auditable: it says a limit
was satisfied but not *which* intent was judged, nor whether the limits in
force were strict or permissive. Two policies that differ only in their limits
produce decisions that are distinguishable by fingerprint. Both fields are
required non-empty strings.

Neither field is authenticated. Like the provenance in §16, the fingerprint
proves that *these* limit values were used; it does not prove who set them.

### The policy fingerprint's canonical number form

The fingerprint hashes limits through a canonical string so that `Decimal`
values that are numerically equal — `100`, `100.0`, `1E+2` — fingerprint
identically, while genuinely different values do not collide.

That string is a normalised mantissa plus an explicit exponent (`1E2`), **not**
fixed-point notation. Fixed point reads more naturally but costs one character
per power of ten, and `Decimal` accepts exponents far beyond any plausible
limit: `Decimal("1E+1000000")` is a structurally valid positive limit whose
fixed-point rendering is a million characters. The exponent form keeps the
canonical string proportional to the number of *significant digits*, so it
stays short for any magnitude.

The rendering is also computed structurally, from `Decimal.as_tuple()`, rather
than via `normalize()`, which raises `decimal.Overflow` past the arithmetic
context's `Emax`. A policy that passes construction can therefore always
compute its own fingerprint. Non-finite `Decimal`s (`NaN`, `Infinity`) are
refused rather than canonicalised.

## 14. Structural invalidity vs policy rejection

| | |
|---|---|
| **Raises** | malformed size, `float` where `Decimal` required, naive timestamp, empty id or symbol, duplicate intent id, recycled position id, unknown or already-closed close target, close before open |
| **`REJECTED`** | a well-formed intent a limit declines |

Domain corruption is never dressed up as a reason code, and a policy outcome
never raises.

## 15. Rejection and retry semantics

A **rejected** intent returns the *same portfolio value* — no position, no
exposure change, no history change — and its id is **not** recorded as
processed. The same conceptual intent may therefore be reconsidered after the
human closes something or changes the policy. That is the expected workflow.

An **approved** intent id *is* recorded, so replaying it raises and a retry can
never silently double exposure.

Limitation: nothing authenticates an intent id against its *content*. Two
different intents reusing one id are indistinguishable here; that belongs to a
persistence layer, which Phase 5 does not have.

## 16. Provenance — preserved, not authenticated

`ResearchProvenance` is optional and holds only `hypothesis_id`,
`hypothesis_version`, `hypothesis_fingerprint` and `observation_timestamp` —
plain strings, never a `ResearchState`. Nothing re-runs a hypothesis, so these
fields answer *"what does this record claim it referenced?"*, not *"is that
claim true?"*, exactly as in Phase 4.

Opening provenance survives a close unchanged. A close does not carry its own
research provenance in v1; it is identified by its own intent id and timestamp.

## 17. Invariants

Unique position ids (never recycled, including after a close) · unique
processed intent ids · notional finite and `> 0` · `total_open_notional ==
sum(open notionals)` · `open_position_count == len(open_positions)` · closed
positions contribute zero · a rejected or invalid intent leaves the portfolio
equal.

Exposure and count are **computed**, not stored — a cached total is a
conservation invariant waiting to be violated.

## 18. Not included

No persistence — the domain is in-memory values; atomicity, migrations and
partial-write recovery belong with the dashboard, where the access pattern will
be known. No concurrency handling: single-user, local, no shared state.

## 19. Future simulation stays separate

A future `ResearchObservation → SimulationPolicy → hypothetical action` layer
should **not** reuse `PaperIntent`. A `PaperIntent` asserts *a human chose
this*; a simulated action asserts *a policy generated this*. Sharing the record
would make provenance unanswerable. Such a layer may reuse `RiskPolicy` — a
limit is a limit — but should have its own action records.

## 20. Known limitations

Exposure is **nominal**, not marked to market — there are no prices. Long-only.
No cash, P&L, costs or performance of any kind. No persistence, no concurrency.
Provenance preserved, not authenticated. Risk rules are portfolio-local: no
correlation, sector or drawdown limits are expressible.

> **Nothing in this package measures or claims performance.**
