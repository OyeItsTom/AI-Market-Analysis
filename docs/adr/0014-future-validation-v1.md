# ADR 0014 — Future validation v1 (M2 pre-registration)

**Status**: accepted (FUTURE_VALIDATION_V1 defined, implemented and tested;
**not bound to activation** — that is the later M2B gate; Prospective
Collection v1 **not activated**)

FUTURE_VALIDATION_V1 fingerprint:
`79f7c4da914727ca8884e594ca997b2ab8dfc1a95a7279b110a7cef69cd6d2ab`
(supersedes the never-committed `0b113f89387871f4f17c401fee1e71f7bdc7d330015f718328b5d6ea7a17f377`,
which measured E1/F on the host clock — decision 14).
Methodology: `docs/research/future_validation_v1.md`.

## Context

Prospective Collection v1 (ADR 0013) records claims before their outcomes
exist, and N2 provenance can tell legitimate collector writes from anything
else. What was still missing is the question those claims will answer, fixed
before any of them exists. A question chosen after looking at prospective
outcomes would turn the one clean form of evidence the project can get into
another fitted description. The retrospective work gives the question its
subject: Phase R found the `trend_alignment` BULLISH h20 mean and median below
the matched unconditional benchmark on SPY, QQQ and IWM, and Phase 13A found
no reason to change any hypothesis.

## Decisions

### 1. `trend_alignment` is the primary hypothesis

It is the simplest of the three (one SMA20/SMA50 comparison), it is dense
(every bar has a state) and its retrospective deltas are non-zero on all
three equity ETFs, so there is a definite sign to compare against.

*Rejected:* `trend_crossover` as a target — its states are transitions and
are sparse; a few years of daily claims would give too few episodes to say
anything. It is out of scope.

### 2. `momentum_in_trend_context` is secondary only

It shares the SMA20/SMA50 structure with `trend_alignment` (it adds RSI14), so
it is not an independent test of anything; reporting it as a second primary
would count one structure twice. It is reported descriptively.

### 3. h20 is the primary horizon; RAW basis; observation-level view

h20 is where the retrospective deltas are clearest and is the horizon Phase
13A examined; the observation-level view is the view the frozen reference
was computed in, so the comparison is like for like. h5 is secondary; h1 is
out of scope. Episode counts measure adequacy and dependence; the
episode-start view is secondary.

### 4. Equity symbols separately; no vote, no overall verdict

SPY, QQQ and IWM each receive their own category. They are correlated equity
ETFs and are not three independent replications, so no k-of-3 rule, majority,
pooled statistic or overall verdict exists. TLT and GLD are described per
symbol, secondarily.

### 5. Stop rule: 48 months AND 750 matured claims per symbol, OR 72 months

48 calendar months gives several market regimes; 750 matured h20 claims per
equity symbol (roughly three years of sessions) supplies broad coverage
independent of what the claims say. The 72-month forced unlock bounds the
wait if collection is patchy; adequacy then decides conclusiveness. The rule
reads Level-1 metadata only (keys, bar timestamps, counts, provenance status),
so no one can time the opening on what the data show. Calendar months are
exact calendar arithmetic in UTC, never a day count, measured on the evidence
clock (decision 14).

### 6. Adequacy: at least 8 BULLISH episodes, nothing else

Adequacy needs the state that is being tested to have occurred in several
separate stretches; 8 episodes is a modest floor against a single trend
dominating (Phase R had 26–32 over ten years). There is **no BEARISH minimum**:
BEARISH observations enter the primary comparison only through the matched
benchmark, and requiring them would make the primary result depend on a
secondary state. There is no unconditional-sample minimum: E2 already
requires 750 matured claims.

### 7. Categories by sign, with no magnitude threshold

`directionally_consistent` / `directionally_reversed` require the mean and
median deltas to agree in non-zero sign with (or against) the reference;
anything else is `mixed`.

*Rejected:* the earlier proposal of a 0.5x magnitude cutoff and a `weaker`
category. Any such number is arbitrary, and a cutoff chosen now would still
invite reading the result through it. Magnitude ratios are reported
descriptively and never change a category.

### 8. No inferential claim

Overlapping h20 windows and serially dependent episodes make naive p-values
and confidence intervals misleading, and the project has never claimed
significance. The result is a pre-registered descriptive comparison; every
report says so.

### 9. One open, write-once, deterministic

`status` is blind; `run` is the only opening; `unlock.json` and `result.json`
are written once and never replaced; the input snapshot is frozen by length
and SHA-256 under the collection's shared lock; a crash after unlock can only
complete that same unlock from its recorded prefixes. This removes every
"look, then decide whether to look properly" path.

### 10. The reserved interval stays excluded

Bars from 2025-03-01 to `activated_at` were never claimed prospectively and
must not be mixed with claims that were. They remain available to a
separately pre-registered retrospective study only.

### 11. Degraded evidence is excluded everywhere

N2 lets collection continue with degraded (interrupted-run) evidence listed
for exclusion. The validation removes every excluded key from every number —
stricter than merely letting such keys through — so evidence with doubtful
attribution never shapes a result.

### 12. No early termination in v1 — a stalled collection never opens

*Amended in the M2A blocker repair.* There is no operator, host-clock or
result-driven early opening and no "terminate and validate now" action. Because
E1 and F run on the evidence clock (decision 14), a collection that ends
permanently before `evidence_through` reaches 72 calendar months (with E1 and
E2 never met together) **never opens** FUTURE_VALIDATION_V1. Analysing such a
terminated collection requires a separately pre-registered amendment or a new
validation version. This is a deliberate trade-off: blindness and
pre-registration integrity outrank a guaranteed eventual opening after a
collection failure.

*Superseded:* "a permanently ended collection opens only through the 72-month
forced unlock" — that opening was measured on the host clock, which anyone can
set forward.

### 13. Definition separate from runner (and runs keyed by fingerprint)

The definition module imports nothing from the project; the engine and the
runner apply it. The later M2B gate can bind "this committed definition and
document are the pre-registration" without treating operational code as the
research question. Unlock, result and report live under a directory named by
the definition's full fingerprint, so a run under any other definition can
never occupy the frozen one's single opening; a written result is re-derived
from its unlock's recorded prefixes on every later run and refused unless
byte-identical.

### 14. E1 and F run on the evidence clock, never the host clock

*Added in the M2A blocker repair.* The independent review showed that with the
host wall clock as the time source, setting the clock forward satisfied F and
opened Level 3 with about a month of evidence. E1 and F are therefore measured
on `evidence_through`: the settlement time of the latest legitimate
(non-excluded, post-activation) claim bar in the frozen snapshot, any symbol
and any producer. Those are provider market dates the collector could claim
only while current, so the clock cannot run ahead of real collected evidence.
The host clock is recorded as unlock metadata (`host_recorded_at`) and decides
nothing; `status` reads no clock at all. `evidence_through` is distinct from
the analysis cutoffs `C_s`.

*Rejected:* host time (forward-settable); `min(host, evidence)` (adds nothing
over the evidence clock alone and keeps a host dependency); a hybrid F that
falls back to host time after collection stops (reintroduces the early-opening
path).

## Consequences

* Activation still requires M2B (bind the M2 commit, fingerprint and
  `origin/main` containment into activation), the **pre-activation
  dependency-drift decision** (runtime enforcement against activation
  metadata, or a verified pinned environment), scheduling/backup, and human
  approval.
* Any change to the question, thresholds, categories or analyses is a new
  version with a new fingerprint, decided before activation — never after.
