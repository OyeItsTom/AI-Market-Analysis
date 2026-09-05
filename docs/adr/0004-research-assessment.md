# ADR 0004 — Research assessment

**Status**: accepted (Phase 6)

## Problem

Phase 3 produces one classification per hypothesis per bar. With three
hypotheses there is no way to ask *"what does the combined evidence say here?"*
without a human mentally reducing several records — an operation with no
definition, no identity and no audit trail.

The danger in answering it is that a combined classification looks much more
like an instruction than a single hypothesis' output does. "Three hypotheses
agree: bullish" reads as advice in a way "trend_alignment classified bullish"
does not. So the design question is not only how to combine evidence, but how
to combine it without manufacturing authority the research does not have.

## Decisions

### 1. `ResearchAssessment`, not `Signal`

"Signal" means *a trigger to act*. Naming the abstraction after one invites
every later layer to treat a classification as an instruction, and makes it
awkward to express "the combined evidence is genuinely uninformative". Phase 3
made the same call refusing `BUY`/`SELL` for `ResearchState`.

`BUY`/`SELL`/`HOLD` are excluded outright — no research-only semantics justify
words that cannot be distinguished from an order type.

### 2. `AssessmentState` is a separate enum

Not a reuse of `ResearchState`, for two reasons. Phase 3 has no `CONFLICTED`,
and adding one there would change Phase 3's meaning — `MomentumInTrendContext`
currently reports an internal contradiction as `NEUTRAL` precisely because the
word does not exist. And a distinct type lets a future evaluator tell a single
hypothesis' classification from a combined one without relying on convention.

### 3. `CONFLICTED` is distinct from `NEUTRAL`

`NEUTRAL` means the evidence points nowhere; `CONFLICTED` means sufficient
evidence disagrees. Collapsing them would erase exactly the situation a human
most needs to examine: two hypotheses that both fired, in opposite directions.

Conflict takes precedence over volume — any simultaneous bullish and bearish
evidence yields `CONFLICTED` regardless of accompanying neutrals. It represents
directional contradiction, not a vote-count tie, and abstentions cannot resolve
a disagreement.

### 4. Exact ensemble (P0), not a required subset

`AssessmentPolicy.hypotheses` is the complete set: each member exactly once,
nothing else. Missing, unexpected and duplicate all raise.

The alternative — a mandatory subset that permits extras — would mean policy
identity did not determine which hypotheses contributed, so two assessments
with the same fingerprint could have been computed from different evidence. The
field is named `hypotheses` rather than `required_hypotheses` so nothing
suggests otherwise.

### 5. `minimum_sufficient_observations` (M1), not `minimum_directional`

An earlier draft used a directional minimum. It was wrong: three `NEUTRAL`
observations give `directional_count = 0`, so any minimum ≥ 1 would report a
legitimate all-neutral ensemble as `INSUFFICIENT_DATA`.

The distinction that fixes it: `NEUTRAL` is **sufficient but not directional**.
The minimum counts observations that *classified*, and `INSUFFICIENT_DATA` is
the only state that does not count.

### 6. Directional presence (V1), not majority or plurality

Decided from what `NEUTRAL` actually means in the hypotheses that exist.
`TrendAlignment` reports it when the gap is below its margin,
`MomentumInTrendContext` when momentum is mid-range, `TrendCrossover` whenever
no crossover occurred — nearly every bar, since crossovers are rare.

`NEUTRAL` therefore means "my condition did not fire", not "I assert flatness".
Under majority or plurality those abstentions would outvote a hypothesis that
actually fired, and `TrendCrossover`'s quiescence alone would drown a
three-hypothesis ensemble into permanent `NEUTRAL`, hiding real crossovers.

**Rejected: V2 (plurality) and V3 (strict majority)** for that reason.

The cost is asymmetry — one firing hypothesis among abstentions yields a
directional state. Accepted because the record makes it fully legible: `BULLISH`
with `bullish=1 neutral=2` and `DIRECTIONAL_BULLISH_WITH_NEUTRAL`. The counts
and reason codes are mandatory, not decoration.

### 7. No `conflict_mode`

An earlier draft included one. It was dead configuration: only one conflict
behaviour is defined and defensible in v1, so the field would have offered a
caller a decision they cannot actually make. The conflict rule is part of the
aggregation contract, not a setting.

### 8. The aggregation rule *is* part of the policy identity

Removing `conflict_mode` left a real gap: the reduction function lived entirely
in `aggregate.py`, so a future change from directional presence to plurality
would alter results for the same ensemble, minimum and observations while
leaving the fingerprint unchanged. Archived assessments would become
uninterpretable — the failure `HypothesisSpec.fingerprint` exists to prevent.

`AssessmentAggregationRule` closes it. It has exactly one member and enters the
canonical form.

**This is not a contradiction of decision 7.** `conflict_mode` was dead
*configuration* — a switch with one position, offering a choice that does not
exist. `aggregation_rule` is live *identity* — it offers no choice at all, but
changes the fingerprint whenever semantics change. One would have been a knob;
the other is a version stamp, exactly as `HypothesisSpec.version` records which
implementation applied rather than letting a caller select one.

A field whose purpose is versioned auditability is complete at one member.
There is deliberately no registry, plugin mechanism, aggregator hierarchy or
dispatch: with one member there is nothing to dispatch on, and a branch would be
the first step toward the configurability this design excludes.

**A rule identity is never materially redefined.** New semantics require
`directional_presence_v2`. The locked decision-table tests are what make an
in-place edit detectable.

`assess()` refuses any rule it does not implement. Adding an enum member
without a reduction would otherwise produce assessments whose fingerprint
claims the new identity while V1 semantics were applied — well-formed,
plausible, and wrong. The check compares; it does not dispatch.

### 9. Canonical JSON, not delimiter-joined text

Identity strings are caller-supplied and may contain any character. Rendering
the ensemble as `id@vN#fp` joined by separators would let a `hypothesis_id`
containing `@` or `#` produce the same canonical string as a *different*
ensemble — a fingerprint collision between two genuinely different policies.

Two fixes were available: ban delimiter characters, or make the encoding
unambiguous. Banning them would push an encoding problem onto callers and
constrain identifiers for a reason that has nothing to do with research. The
encoding is JSON instead, with a pinned contract (`separators=(",", ":")`,
`ensure_ascii=True`, `sort_keys=True`, `allow_nan=False`, UTF-8), and the
ensemble sorted before encoding so caller order cannot leak into identity.

### 10. Counts, not confidence

Four stored integers with `sufficient` and `total` derived. No score, no
probability, no confidence, no weights.

A number computed from a handful of hypotheses — two of them trend-family and
sharing inputs — would manufacture precision the research cannot support, and
calling it "confidence" would be the most misleading version of that. Integer
counts say exactly what they are, and a caller wanting a fraction forms one and
sees the denominator.

Weights were rejected for v1 on the same ground: hand-chosen weights encode an
unjustified prior, and performance-derived weights are decision 11.

`MAJORITY_BULLISH` was removed from the reason codes for the same reason — under
this rule `BULLISH + NEUTRAL` is not a majority, and the code would be false.

### 11. No historical performance (H0)

Phase 6 accepts neither `EvaluatedOutcome` nor `EvaluationSummary`.

Beyond the usual causal problems — cutoffs, overlapping horizons, sample size,
feedback loops — inspection settled it: `EvaluationSummary` has no as-of field
at all. Nothing in it records which evaluations were available before a given
instant, so feeding it into an assessment would import lookahead the type system
could not even express a guard against.

Attaching summaries for display only was also rejected: a field on the record
will eventually be read by aggregation logic, and the boundary is cheaper to
hold than to restore. A dashboard can show Phase 4 summaries beside an
assessment without the record carrying them.

A future evaluator may consume finished assessments. The dependency points from
evaluation to assessment and never reverses.

### 12. `src/assessments`, not `src/signals`

The empty `src/signals` placeholder is unreferenced anywhere in `src/` or
`tests/`, and its name means "a trigger to act" — the semantics this phase
exists to avoid. Phase 6 does not delete it; removal is separate work.

### 13. The direct-construction trust boundary

`ResearchAssessment` defends its intrinsic invariants — count conservation,
canonical input order, unique identities, reason-code ordering, and state
agreeing with the evidence — rather than trusting its producer. A public
immutable record that callers can construct must not be constructible into a
state it could never legitimately reach.

One invariant is deliberately left as a producer guarantee: whether
`INSUFFICIENT_DATA` reflects `sufficient < minimum`. The record stores the
policy fingerprint, not the minimum, so it cannot check this alone. Duplicating
policy fields into every assessment to close that single gap would create a
second source of truth for them. The boundary is documented and tested as such
rather than left for a reviewer to find.

## Consequences

- A research classification cannot become a paper action, by construction:
  `src/assessments` and `src/portfolio` import nothing from each other.
- Policy identity fully determines the ensemble, the minimum and the semantics.
- Assessment states carry no confidence, strength or probability, and no number
  in the record can be mistaken for one.
- Combining evidence is possible without claiming independence: hypothesis
  agreement is descriptive accounting, and the docs say so.
- Adding a hypothesis or changing a minimum changes policy identity, so old
  assessments are never silently redefined.

## Limitations carried forward

Provider provenance cannot be verified (`ResearchObservation` has no source
field). Adjusted history remains not point-in-time safe (ADR 0001).
`assessment_as_of` is a conservative, inexact bound and never a claim about data
availability. Hypothesis agreement is not independent confirmation.
