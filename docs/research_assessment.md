# Phase 6 — Research assessment

Combines aligned Phase 3 research observations into one immutable, auditable
record.

```
ResearchObservation(s)  →  AssessmentPolicy  →  ResearchAssessment
```

## 1. What this is

A `ResearchAssessment` says what an exact ensemble of hypotheses collectively
classified at one market point.

It is **not** a signal, a recommendation, a prediction, a probability, a
confidence, a measure of strength, or an instruction. There is no `BUY`, `SELL`
or `HOLD`, and there is no path from an assessment to a paper action.

The ordinary flow keeps a human in the middle:

```
ResearchObservation(s) → ResearchAssessment → displayed to a human
                                                     ↓
                              the human may do nothing (ordinary outcome)
                                                     ↓
                              or explicitly create a PaperIntent → RiskPolicy → PaperPortfolio
```

"Bullish assessment and no paper position" is the normal state, not a special
case.

## 2. Terminology

`ResearchAssessment`, not `Signal`. In finance a "signal" means *a trigger to
act*; naming the abstraction after one invites every later layer to treat a
classification as an instruction. Phase 3 made the same choice when it refused
`BUY`/`SELL` for `ResearchState`.

`AssessmentState` is a **separate enum** from `ResearchState`. It has to be:
Phase 3 has no `CONFLICTED` — `MomentumInTrendContext` is forced to report an
internal contradiction as `NEUTRAL` for want of the word — and adding one there
would change Phase 3's meaning. A separate enum also lets a future evaluator
tell a single hypothesis' classification from a combined one by type.

## 3. Input and output

**Input**: `ResearchObservation` records only.

Phase 6 re-runs no hypothesis, computes no feature, fetches no market data, and
reads no outcome. It consumes finished records and reduces them.

**Output**: one `ResearchAssessment`:

| Field | Meaning |
| --- | --- |
| `policy_fingerprint` | which policy produced this |
| `symbol`, `interval`, `basis`, `timestamp` | the market point assessed |
| `assessment_as_of` | timing bound (§10) |
| `state` | the combined classification |
| `inputs` | every contributing identity and what it said |
| `counts` | integer evidence accounting |
| `reason_codes` | closed-vocabulary explanation |

## 4. The exact ensemble

`AssessmentPolicy.hypotheses` is an **exact ensemble**, not a minimum subset.
Every listed hypothesis must appear exactly once; extras raise; duplicates
raise. Policy identity therefore completely determines which hypotheses
contributed, which is what makes an archived assessment reproducible.

A hypothesis is pinned by all three of `hypothesis_id`, `version` and
`fingerprint`. An id alone is not an identity: a `v1` whose parameters were
quietly changed has a different fingerprint, and pinning only the id would let
it present itself as the original.

## 5. The decision table

The rule is `directional_presence_v1`:

```
1. validate structure                        — any problem RAISES
2. count bullish / bearish / neutral / insufficient
3. sufficient = bullish + bearish + neutral
4. sufficient < policy minimum  → INSUFFICIENT_DATA
5. bullish > 0 and bearish > 0  → CONFLICTED
6. bullish > 0                  → BULLISH
7. bearish > 0                  → BEARISH
8. otherwise                    → NEUTRAL
```

Steps 6 and 7 cannot tie: step 5 already excluded the case where both are
non-zero.

| Inputs | Result |
| --- | --- |
| `BULLISH + NEUTRAL + NEUTRAL` | `BULLISH` |
| `BEARISH + NEUTRAL + NEUTRAL` | `BEARISH` |
| `BULLISH + BEARISH + NEUTRAL` | `CONFLICTED` |
| `BULLISH + BEARISH + NEUTRAL×3` | `CONFLICTED` |
| `NEUTRAL + NEUTRAL + NEUTRAL` | `NEUTRAL` |
| `BULLISH + INSUFFICIENT + INSUFFICIENT` (min 2) | `INSUFFICIENT_DATA` |
| `NEUTRAL + NEUTRAL + INSUFFICIENT` (min 2) | `NEUTRAL` |

## 6. Why `NEUTRAL` behaves as an abstention

This is the decision the whole rule rests on, and it comes from what the actual
hypotheses do:

| Hypothesis | `NEUTRAL` reason | Meaning |
| --- | --- | --- |
| `TrendAlignment` | `TREND_MARGIN_BELOW_THRESHOLD` | gap too small to call |
| `TrendAlignment` | `FAST_EQUALS_SLOW` | exact equality (rare) |
| `MomentumInTrendContext` | `MOMENTUM_MIDRANGE` | momentum not extreme |
| `MomentumInTrendContext` | `MOMENTUM_CONTRADICTS_TREND` | contradiction, with no vocabulary for it |
| `TrendCrossover` | `RELATIONSHIP_UNCHANGED` | no crossover occurred |

`NEUTRAL` overwhelmingly means *"my condition did not fire"*, not *"I assert
flatness"*. `TrendCrossover` reports it on nearly every bar, because crossovers
are rare events.

Under a majority or plurality rule those abstentions would outvote a hypothesis
that actually fired, and a real crossover would be reported as `NEUTRAL`.
Directional presence lets a firing hypothesis be heard.

**The trade-off is real and is not hidden.** One directional hypothesis among
abstentions yields a directional state. That is exactly why the counts and
reason codes are mandatory parts of the record: `BULLISH` with
`bullish=1 neutral=2` and `DIRECTIONAL_BULLISH_WITH_NEUTRAL` says precisely how
thin the evidence was.

## 7. Conflict has precedence over volume

Step 5 runs before steps 6–8, so **any** simultaneous bullish and bearish
evidence yields `CONFLICTED` no matter how much neutral evidence accompanies
it.

`CONFLICTED` represents *directional contradiction*, not a vote-count tie.
Abstentions cannot resolve a disagreement between two hypotheses that both
fired.

`NEUTRAL` and `CONFLICTED` are semantically different and are never collapsed:
the first says the evidence points nowhere, the second says it disagrees — and
the second is when a human should look closer.

## 8. Sufficient, directional, insufficient

- **Sufficient**: `BULLISH`, `BEARISH`, `NEUTRAL` — the hypothesis classified.
- **Directional**: `BULLISH`, `BEARISH` — it also pointed somewhere.
- **Insufficient**: `INSUFFICIENT_DATA` — genuine warm-up shortage.

`NEUTRAL` is sufficient but not directional. Conflating "classified as neutral"
with "could not classify" would make a legitimate all-neutral ensemble
unreachable, which is why the minimum counts *sufficient* observations and not
*directional* ones.

`minimum_sufficient_observations` is how much real evidence the policy needs:
`1 ≤ minimum ≤ len(hypotheses)`. A minimum above the ensemble size is refused —
that policy could never produce a sufficient assessment.

Insufficient observations are excluded from the state reduction but **always
counted and recorded**. Nothing is dropped from the audit trail.

A **missing** hypothesis is a structural error and raises — it is never
reported as `INSUFFICIENT_DATA`. This follows Phase 3's rule that
`INSUFFICIENT_DATA` is reserved for legitimately unavailable evidence and never
absorbs a structural problem.

## 9. Counts, not confidence

`AssessmentCounts` stores four integers — `bullish`, `bearish`, `neutral`,
`insufficient` — and derives `sufficient` and `total`. Derived rather than
stored, because a stored total is a conservation invariant waiting to disagree
with the numbers it summarises.

Integers, deliberately: every quantity here is a count of classifications.
Phase 5's lesson was to pick the type that matches the quantity, not to reach
for `Decimal` by habit.

**There is no score, no confidence and no probability.** A number derived from a
handful of hypotheses would manufacture precision the research cannot support.
Anyone wanting a fraction can form one from these counts and will see the
denominator, which `0.67` would hide.

### Reason codes

Closed vocabulary, deduplicated and canonically ordered *by the record itself*,
so the ordering holds however the record was built:

`UNANIMOUS_BULLISH`, `UNANIMOUS_BEARISH`, `UNANIMOUS_NEUTRAL`,
`DIRECTIONAL_BULLISH_WITH_NEUTRAL`, `DIRECTIONAL_BEARISH_WITH_NEUTRAL`,
`CONFLICTING_DIRECTIONAL_EVIDENCE`, `INSUFFICIENT_EVIDENCE`,
`INSUFFICIENT_INPUTS_EXCLUDED`.

There is deliberately no `MAJORITY_BULLISH`: under this rule `BULLISH + NEUTRAL`
is a directional finding among abstentions, not a majority, and a code claiming
one would be false.

**"Unanimous" is scoped to the *sufficient* inputs** — those that actually
classified. `BULLISH + BULLISH + INSUFFICIENT_DATA` is `UNANIMOUS_BULLISH`,
because the hypothesis that could not classify cast no vote to disagree with.
The exclusion is never concealed: that assessment also carries
`INSUFFICIENT_INPUTS_EXCLUDED`, and `counts.insufficient` records it. Read the
two codes together.

`INSUFFICIENT_INPUTS_EXCLUDED` means those observations *did not take part in
the state reduction*. It does not mean they were dropped — they remain in
`inputs` and in `counts.insufficient`.

## 10. Timing

```
assessment_as_of = max(observation.evaluable_from)
```

The combined classification cannot logically exist until every contributing
classification could, so `max` is the only safe reduction.

`evaluable_from` is Phase 3's `timestamp + interval.max_duration`. Since
alignment forces `timestamp` and `interval` to match, every aligned observation
currently shares one value; `max` is kept because it is the reduction that stays
correct if alignment is ever relaxed.

**What `assessment_as_of` is**: a conservative bound, never earlier than the
instant the combined classification could logically be made from completed-bar
evidence.

**What it is not**: exact (`max_duration` deliberately over-estimates — a 1 Feb
monthly bar yields 3 Mar while the next bar opens 1 Mar); actual data
availability; provider-arrival time; exchange-calendar truth; latency; or proof
that a live caller possessed the data. Latency and calendars are modelled
nowhere in this repository, and Phase 6 does not become the first place to
imply otherwise.

`timestamp` is bar **open** time (a Phase 1 invariant) and is used only for
alignment — never as evidence of knowability. No wall clock is read anywhere.

## 11. Alignment

Every observation must describe **exactly the same market decision point**.
Exact equality on `symbol`, `interval`, `basis` and `timestamp`; any mismatch
raises. No tolerance window, no nearest-match, no timestamp guessing, no
implicit basis conversion.

Basis is the sharpest of these: `RAW` and `SPLIT_AND_DIVIDEND_ADJUSTED` numbers
are denominated differently and must never be compared (ADR 0001).

## 12. Duplicates and mismatches

All raise; nothing is silently deduplicated or repaired.

| Condition | Reported as |
| --- | --- |
| Same identity twice | duplicate hypothesis |
| Same `id`+`version`, different fingerprint | **fingerprint mismatch** (distinct) |
| Pinned identity absent | missing hypothesis |
| Identity not in the ensemble | unexpected hypothesis |

The fingerprint-mismatch case is reported distinctly because it means a known
hypothesis/version whose implementation identity changed — the silent
redefinition `HypothesisSpec.fingerprint` exists to catch — not an unrelated
hypothesis appearing.

## 13. Policy identity

`AssessmentPolicy` has exactly three material fields, all required with no
defaults: `hypotheses`, `minimum_sufficient_observations`, `aggregation_rule`.

```
canonical JSON → SHA-256 → first 16 hex characters
```

A fingerprint is always **16 lowercase hex characters**, and a
`ResearchAssessment` refuses any other shape: an assessment naming a policy no
`AssessmentPolicy` could produce can never be matched back to one, which is
unauditable while looking auditable.

| Change | Fingerprint |
| --- | --- |
| Ensemble permuted | same |
| Any id / version / fingerprint changed | different |
| Minimum changed | different |
| Aggregation rule changed | different |

### The aggregation rule is part of the identity

`AssessmentAggregationRule` has exactly one member and is **not** a menu. It
exists so material aggregation semantics cannot change while the fingerprint
stays the same. Without it, `BULLISH + NEUTRAL + NEUTRAL` could yield `BULLISH`
under one release and `NEUTRAL` under the next with both records claiming the
same policy identity.

This is the job `HypothesisSpec.version` does for a hypothesis implementation:
it does not let a caller *select* behaviour, it records which behaviour applied.
A field whose purpose is versioned auditability is complete at one member.

**A rule identity is never materially redefined.** New semantics require
`directional_presence_v2`, which necessarily produces a new fingerprint.

`assess()` also *checks* the rule and refuses any it does not implement. That
is a guard, not a dispatch table: without it, adding a second member to the
enum would leave `assess()` silently applying V1 semantics to a policy whose
fingerprint claims the new identity — the precise silent redefinition the rule
identity exists to prevent.

### Canonical JSON

The canonical form is JSON, not delimiter-joined text, because identity strings
are caller-supplied and may contain any character. Joining `id@vN#fp` with
separators would let a `hypothesis_id` containing `@` or `#` render identically
to a *different* ensemble — a fingerprint collision between two genuinely
different policies. Rather than banning delimiter characters (pushing an
encoding problem onto callers), the encoding is made unambiguous.

The serialization contract is pinned: `separators=(",", ":")`,
`ensure_ascii=True`, `sort_keys=True`, `allow_nan=False`, UTF-8. Mapping key
order is fixed by content; sequences preserve order, so the ensemble is sorted
*before* encoding.

Fingerprints use SHA-256, never Python's `hash()`, which is randomised per
process by `PYTHONHASHSEED`.

## 14. Direct-construction invariants

`ResearchAssessment` defends what it can prove alone rather than trusting its
producer: inputs non-empty, canonically ordered and unique; counts exactly
tallying the inputs; `counts.total == len(inputs)`; reason codes non-empty,
deduplicated and ordered; timestamps aware; `assessment_as_of >= timestamp`; and
state agreeing with the evidence —

- `CONFLICTED` ⟹ bullish > 0 **and** bearish > 0
- `BULLISH` ⟹ bullish > 0 **and** bearish == 0
- `BEARISH` ⟹ bearish > 0 **and** bullish == 0
- `NEUTRAL` ⟹ no directional evidence, and neutral > 0

**One invariant is deliberately not intrinsic**: whether `INSUFFICIENT_DATA`
correctly reflects `sufficient < policy.minimum_sufficient_observations`. The
record stores the policy *fingerprint*, not the minimum, so it cannot check
this alone. It remains a producer guarantee of `assess()`. Duplicating policy
fields into every assessment to close that one gap would create a second source
of truth for them — the worse trade. The boundary is stated here rather than
left for a reviewer to discover.

## 15. Trust boundaries

**Policy identity is preserved, not reconstructable.** The fingerprint proves
*which* policy was used; it does not let you rebuild the policy without the
object. Same boundary as Phase 3 hypothesis fingerprints and Phase 5
`ResearchProvenance`.

**No historical performance enters an assessment.** Phase 6 imports neither
`EvaluatedOutcome` nor `EvaluationSummary`. No hit rate, no forward return, no
performance-derived weighting, no adaptive threshold. Beyond the causal
problems, `EvaluationSummary` carries no as-of field at all, so nothing in it
records which evaluations were available before a given instant — lookahead
could not even be guarded against. A future evaluator may consume finished
assessments; the dependency never reverses.

## 16. Known limitations

1. **Provider provenance cannot be checked.** `ResearchObservation` has no
   source field, so two observations from different market-data providers are
   indistinguishable here. No `source="unknown"` is invented and no provider is
   inferred from a hypothesis id; the honest fix is provenance in Phase 3, which
   Phase 6 does not modify.

2. **Adjusted history is not point-in-time safe.** Its factors depend on
   corporate actions after the bar (ADR 0001), so a historically reconstructed
   assessment on an adjusted basis is **not** what would have been known live.
   `assessment_as_of` bounds bar completion; it says nothing about data vintage.

3. **Hypothesis agreement is not independent confirmation.** Two of this
   repository's three hypotheses are trend-family, and
   `MomentumInTrendContext` already fuses trend and momentum. `bullish=3` is
   three classifications, not three independent votes and not three times any
   confidence.

4. **Directional presence is asymmetric.** One firing hypothesis among
   abstentions produces a directional state. Mitigated by mandatory counts and
   reason codes, not eliminated.

5. **Phase 3 contradictions arrive as `NEUTRAL`.**
   `MOMENTUM_CONTRADICTS_TREND` is a contradiction Phase 3 had no word for, and
   Phase 6 does not re-interpret Phase 3 reason codes to infer conflict.

6. **Versioned rule identity is a discipline, not a compiler guarantee.**
   Nothing prevents editing `directional_presence_v1`'s behaviour in place; the
   locked decision-table tests are what make that detectable.

7. **No performance information of any kind** — by design (§15).

## 17. Not included

No broker, execution, order, or automatic paper action. No prices, quantity,
cash, P&L, costs, slippage, NAV, equity curve, drawdown or Sharpe. No
persistence, network, database, clock, randomness, LLM, news feed or dashboard.
No weights, scores, probabilities or confidences.
