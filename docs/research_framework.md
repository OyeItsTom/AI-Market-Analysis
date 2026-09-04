# Phase 3 — Research hypothesis framework

Written for an engineer who will build the evaluation layer on top of this.
Read `docs/market_data.md` (Phase 1) and `docs/feature_engine.md` (Phase 2)
first.

> **A research classification is not a trade recommendation.** Phase 3 records
> what a deterministic hypothesis classified from a given piece of evidence. It
> measures nothing about what happened next and makes no profitability claim.

---

## 1. Research hypothesis vs trading strategy

| | Research hypothesis (this phase) | Trading strategy (not built) |
|---|---|---|
| Output | a classification of evidence | orders |
| Question answered | "how does this rule read this evidence?" | "what should I buy?" |
| Success criterion | deterministic, auditable, causal | profit after costs |
| Knows about | feature values at one bar | positions, sizing, costs, venues |

The vocabulary is deliberately not `BUY`/`SELL`. Naming the core abstraction
after an order type invites every later layer to treat a classification as an
instruction, and leaves no clean way to say "this evidence is genuinely
uninformative".

## 2. `ResearchState` semantics

```
BULLISH  BEARISH  NEUTRAL  INSUFFICIENT_DATA
```

`BULLISH` means *"this deterministic hypothesis classifies the supplied
evidence as bullish-leaning"*. It does **not** mean "buy", "this will rise", or
"this is a profitable signal".

`INSUFFICIENT_DATA` is reserved for **legitimately unavailable evidence** —
an indicator still in warm-up. It is never used to absorb a structural problem.
A symbol mismatch, interval mismatch, wrong price basis or missing required
feature all **raise**. Hiding a bug behind a plausible-looking state is how a
corrupted study survives review.

A hypothesis that returns `INSUFFICIENT_DATA` from its own classifier raises:
use `NEUTRAL` for "inconclusive".

## 3. Identity and versioning

```
HypothesisSpec(hypothesis_id, version, name, required_features, required_basis)
    ↓ canonical_form   "trend_alignment|v1|basis=any|features=sma(field=close,period=20);…"
    ↓ SHA-256, first 16 hex
  fingerprint          "fad097192e55331e"
    ↓
  label                "trend_alignment@v1#fad097192e55331e"
```

Four properties matter:

- **`v1` and `v2` are different hypotheses.** Changing decision logic means
  incrementing the version; old results keep their own identity.
- **Parameters are part of identity.** A `v1` whose RSI period is quietly
  changed from 14 to 7 gets a *different fingerprint*, so it cannot present
  itself as the original research definition. This is the masquerade the
  fingerprint exists to prevent.
- **Classification configuration is part of identity.** Thresholds and
  dead-bands are declared in `parameters` and folded into the fingerprint. A
  hypothesis whose RSI band moves from 55 to 90 classifies differently and gets
  a different fingerprint. This is enforced, not trusted: constructing a
  hypothesis with an undeclared public configuration attribute **raises**,
  because a stale fingerprint is a silent failure — nothing about it looks
  wrong.
- **The fingerprint is deterministic across processes and machines.** It uses
  SHA-256 over a canonical string. Python's built-in `hash()` is randomised per
  process and would give a different "identity" on every run — useless for a
  persistent record.

`canonical_form` is human-readable on purpose: when two runs disagree you can
diff it rather than two opaque hashes.

## 4. Feature requirements and identity

`"rsi"` is not an identity. `RSI(14)` and `RSI(7)` are different evidence.

`FeatureSpec` gives every parameterisation one canonical key:

```
FeatureSpec("rsi", {"period": 14})  →  rsi(field=close,period=14)
```

Parameters are sorted, so write order does not matter; **defaulted parameters
are filled in** (`resolve_feature_spec`); and values are rendered with their
type distinguishable, so `True` and `"true"` cannot produce the same key. Without that, the short
form and the full form would be two identities for one computation, and a spec
would never match the feature it describes.

A hypothesis declares its features; it never computes them.

## 5. Evidence alignment

A hypothesis combining RSI at `T` with SMA at `T+1` produces a number. It is a
wrong number and nothing about it looks wrong.

`EvidenceSet` verifies **once, at construction**: one symbol, one interval, one
price basis, identical timestamps across every feature, no duplicate specs.
By the time a hypothesis sees anything, misalignment is impossible rather than
merely unlikely.

## 6. Deterministic reason codes

Every observation carries at least one `ReasonCode` from a closed vocabulary.
Not prose, and certainly nothing model-generated: reason codes are asserted on
in tests, counted in later analysis and compared across versions. Free text
serves none of those uses.

Reason codes also disambiguate a state. `MomentumInTrendContext` returns
`NEUTRAL` both when momentum is unremarkable and when momentum *contradicts*
the trend — the codes say which.

## 7. Timing semantics

`ResearchObservation.timestamp` is the **bar open time** (Phase 1 invariant).
`evaluable_from` is `timestamp + interval`: the earliest instant the
classification could logically be made, because the evidence depends on that
bar's completed OHLCV.

**`evaluable_from` is a bound, not a measurement.** It inherits Phase 2's
limitation exactly — no exchange calendar, no provider-latency model. It is
later than the true session close for session-based intervals, and *earlier*
than real data arrival for a delayed feed. It must not be read as "the
classification was actionable at this instant".

No exchange calendar or latency model is introduced in Phase 3.

## 8. Price basis

A hypothesis may declare `required_basis`. If it requires
`SPLIT_AND_DIVIDEND_ADJUSTED` evidence and is handed `RAW`, it **raises**. It
never converts: basis transformation belongs to the data layer
(`src/data/adjustment.py`).

Requiring adjusted evidence is **not** a claim of historical trading validity.
Adjusted history is still not point-in-time safe (ADR 0001) — its factors
depend on corporate actions that happened after the dates they apply to.

## 9. Causality and the evidence window

For an observation at bar `T`: evidence from `[T - lookback ... T]` only.

**Structural guarantee.** `evaluate()` is a template method; the subclass hook
`_classify(values)` receives an `EvidenceWindow` covering exactly the declared
lookback and nothing else. Future evidence is *absent*, not merely forbidden —
the window holds a fixed tuple of rows copied before the hypothesis ran.

Deliberately withheld from the window, each because it is a demonstrated cheat
vector:

| Withheld | Why |
|---|---|
| timestamps | so a hypothesis cannot key off the final date |
| dataset length | `len(window)` is the **feature** count, never the bar count |
| any positive offset | `past()` accepts `0..lookback` only |
| negative offsets | rejected, so Python's negative indexing cannot wrap into the future |
| the bar series | so features cannot be secretly recomputed |

### Declaring history

```python
class TrendCrossover(ResearchHypothesis):
    lookback = 1                       # participates in identity
    def _classify(self, values):
        now  = values.past(self.FAST, 0)   # the bar being classified
        before = values.past(self.FAST, 1) # one bar earlier
```

`lookback` defaults to `0` (point-in-time). The window is also a `Mapping` of
the current bar's values, so a point-in-time hypothesis reads
`values[spec.key]` exactly as before — **existing hypotheses needed no
change**.

### Insufficient history

A bar too early in the dataset to fill the window yields `INSUFFICIENT_DATA`
with `WARMUP_INCOMPLETE`, exactly like indicator warm-up. A dataset simply
starts somewhere; that is a legitimate shortage, not a fault. Structural
problems — missing features, wrong basis, misalignment — still raise.

### Why `lookback` is part of identity

A rule reading one prior bar and the same rule reading three are different
research definitions. `lookback` therefore appears in `canonical_form` and the
fingerprint, so changing `1 → 3` cannot masquerade as the original.

**Verified property.** A subclass *can* override `evaluate`, so the guarantee
is also tested, over the whole pipeline (bars → features → evidence →
classification), with two independent properties:

1. **Tail perturbation** — replace every bar after `k` with radically
   different ones; observations before `k` must be identical.
2. **Truncation invariance** — `run(series[:k])` must equal `run(series)[:k]`.
   Truncation changes the series length and removes future timestamps, which
   perturbation preserves.

Eight cheating hypotheses are pinned as regression tests: length-based,
final-timestamp, next-bar, global-maximum, global-minimum,
future-row-existence, an off-by-one window that includes `T+1`, and one that
retains a window reference and tries to mutate it. The global-minimum cheat
**initially survived** — the perturbation alternated up/down every bar, which
cancels under a moving average, so smoothed extrema never moved. The
perturbation now uses contiguous blocks. A safety net is worth only what it
catches.

## 10. Determinism

Identical specification + identical evidence ⇒ identical output. No randomness,
no clock, no network, no global mutable state, no model calls. Tested.

## 11. Example hypotheses

Two, deliberately. They exist to prove the framework works.

- **`TrendAlignment` (v1)** — fast vs slow moving average with a fractional
  dead-band, so two averages sitting on top of each other read as *no
  separation* rather than flipping on floating-point noise. Point-in-time.
- **`TrendCrossover` (v1)** — a *transition* in that relationship, declaring
  `lookback = 1`. Exists to prove the causal-window abstraction. A crossover
  classifier is an architectural fixture, **not** a profitability claim and
  not a trading recommendation.
- **`MomentumInTrendContext` (v1)** — RSI read *against* prevailing trend.
  Deliberately not "RSI below 30 means buy": that treats one number as a
  recommendation and ignores context. When momentum and trend disagree the
  state is `NEUTRAL` with a `MOMENTUM_CONTRADICTS_TREND` code — saying the
  evidence is mixed is more honest than picking a side.

**No parameter optimisation was performed.** 20/50 moving averages and a
14-period RSI are conventional, recognisable values chosen to make tests
readable. Selecting parameters by historical outcome is how a study fits its
own noise; that belongs in a controlled research protocol, not here.

**A volatility-regime example was considered and rejected.** `ResearchState` is
a directional vocabulary; "high volatility" is not a direction. Forcing it in
would either overload `NEUTRAL` to mean two different things or invent a
directional reading that volatility does not carry. A regime classification
needs its own vocabulary — a decision worth making deliberately, not as a side
effect of wanting a third example.

## 12. Why Phase 3 does not measure profitability

Phase 3 answers *"what did hypothesis X classify at each valid evidence
point?"*

Phase 4 will answer *"what happened afterwards, under a precisely defined
evaluation protocol?"* — and that question needs decisions Phase 3 deliberately
does not make: entry and exit timing, transaction costs, slippage, position
sizing, survivorship handling, and what "afterwards" even means.

Conflating the two produces a number that looks like a return and is not one.
A hypothesis becoming `BULLISH` is **not** evidence that it is profitable.

## 13. Known limitations

- **Bounded history only.** A hypothesis reads `[T - lookback ... T]`. Rules
  needing unbounded history ("N bars since the last crossing", accumulating
  state machines) still cannot be expressed. Lifting that would need carried
  state between bars, which reintroduces order-dependence and a much larger
  causal-testing burden. **DEFERRED.**
- **No `ResearchState` vocabulary for non-directional hypotheses.** See §15.
- **`evaluable_from` is a bound, not provider-arrival time** (§7).
- **Observations are not persisted.** There is no research-record store yet;
  the fingerprint is designed to key one. **DEFERRED.**
- **No exchange calendar** — inherited from Phase 2.
- **No regime/non-directional state vocabulary** (§11). **DEFERRED.**
- **Adjusted evidence is still not point-in-time safe** (§8).
- Evaluation is straightforward O(n) Python.

## 15. `ResearchState` scope — a known coupling

`ResearchState` is the **directional** vocabulary and is correct for
directional hypotheses. One coupling is worth recording before it bites:

`BULLISH` / `BEARISH` / `NEUTRAL` are classifications. `INSUFFICIENT_DATA` is
**availability** — a framework-level concept that every future vocabulary will
also need. It currently lives inside the directional enum.

Consequence: a future regime vocabulary (`HIGH_VOLATILITY` / …) could coexist
by value — those strings do not collide with the directional ones — **except**
for its own "insufficient data" member, which would. `ResearchObservation`
also coerces `state` through `ResearchState(...)`, so it would need widening.

This is deliberately **not** solved in Phase 3: no non-directional hypothesis
exists yet, and separating availability from classification changes the
observation record, which is a decision worth making with a real second
vocabulary in hand rather than speculatively. Recorded as **DEFERRED**, with
the specific shape of the future change named above so it is not a surprise.

What was explicitly rejected: adding regime members to `ResearchState`. A
single enum mixing direction, volatility and trendiness makes every consumer
handle states that cannot apply to it.

## 14. Continuous integration

`.github/workflows/tests.yml` runs `compileall`, an import check and the full
suite on pushes to `main` and on pull requests.

**Supported Python version: 3.11.** That is what the project is developed and
verified on. No other version is claimed, because no other version has been
run.
