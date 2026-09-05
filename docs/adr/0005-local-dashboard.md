# ADR 0005 — Local research dashboard

**Status**: accepted (Phase 7)

## Problem

Phases 1–6 produce a complete research pipeline that can only be reached by
writing a script. Making it visible is straightforward; making it visible
*without changing what it means* is not.

An interface is where a research project usually loses its discipline. The
pressure is structural rather than careless: a screen that shows `BULLISH` and
also has a button is, in practice, a screen that recommends. Every prior phase
was built to keep classification separate from instruction — Phase 3 refused
`BUY`/`SELL` for `ResearchState`, Phase 5 requires an explicit human
`PaperIntent`, Phase 6 reports counts rather than confidence — and a UI is the
first place where all of it sits together on one page and could be quietly
undone by layout alone.

Streamlit adds a second problem. It re-runs the entire script on every
interaction, so any mutation written in ordinary rendering code executes again
on every keystroke.

## Decisions

### 1. A three-layer dependency direction

```
dashboard  ->  application  ->  Phase 1-6 domain
```

`src/dashboard` may import Streamlit and `src.application`, nothing else.
`src.application` may orchestrate the domain but never imports a UI framework,
so all orchestration stays headlessly testable. No Phase 1–6 module learns that
either package exists.

The middle layer is not ceremony. Without it the UI would be the only place
where a fetch, a feature computation and an assessment are sequenced, and the
sequencing — which is where coherence and atomicity live — would only be
testable by driving a browser.

Enforced by AST import analysis, not review.

### 2. `ResearchSnapshot` is one frozen object

The worst thing this dashboard could do is show fresh bars beside a stale
assessment. Rather than making that unlikely, the snapshot makes it
*unrepresentable*: bars, features, observations, assessment and policy
fingerprint are built inside one call from one fetched series and published as
one immutable record. There is no code path that updates a single field.

The mapping of features is a read-only view rather than a plain dict — a frozen
dataclass wrapped around a mutable mapping is only half-frozen.

Publication is a single assignment that happens only after every stage
succeeded. A failure therefore leaves the previous complete snapshot in place,
which is why the error banner can honestly say which snapshot you are still
looking at.

### 3. The clock is injected at the application layer

No domain module reads a clock. `build_snapshot` takes a `now` callable so a
whole snapshot — window, `built_at`, and every derived timestamp — is
reproducible in a test. `built_at` is timezone-aware, checked at construction.

### 4. History windows are derived from the interval

2 years for `1d`, 3 for `1wk`, 10 for `1mo`, and no start-date control.

A window is only meaningful if it clears the ensemble's 51-bar warm-up floor,
and that is a property of the interval rather than a user preference. Two years
is ample for daily bars and yields 24 monthly bars, which would leave a monthly
view permanently `INSUFFICIENT_DATA` — a control whose obvious setting is wrong
is worse than no control.

The regression test asserts the floor deterministically, dividing the window by
`Interval.max_duration` — the domain's own upper bound on a period's length —
rather than relying on a bars-per-year estimate.

### 5. Settled bars only, RAW only, and no control for either

`include_unsettled=False` always, with no toggle. The forming bar's close keeps
moving, so an assessment built on it is not reproducible.

RAW basis only, shown on screen, with no toggle: adjustment needs
corporate-action data this dashboard has no source for. The view model still
renders the adjusted-history point-in-time warning if an adjusted basis is ever
passed to it, so the caveat cannot vanish if a later phase adds one.

### 6. `CsvBarStore` is out of scope

Refresh always goes to the provider. Adding a cache would introduce a freshness
question — *is what I am looking at what I just asked for?* — that a first
version of a research display should not have to answer. Phase 7 opens no files
at all.

### 7. The research panel has no action control

Not "no action control yet". The research module has no button, no form and no
submit control, and the paper module is never passed an assessment view. The
separation is structural in both directions, so the interface cannot present a
classification as a reason to act even by accident.

`src/application/paper.py` — the only module that mutates anything — imports
nothing from `src.assessments` or `src.strategies`. There is no identifier in
its scope through which a research state could be read, let alone branched on.
The optional provenance note is built from plain values for the same reason.

### 8. Four layers against duplicate actions

Streamlit's rerun model makes "apply this action" in rendering code a repeated
action. So: `st.form`, `st.form_submit_button`, ids minted before the form
renders and held across reruns, and Phase 5's replay protection underneath.

The fourth layer only works if the third feeds it. Ids are therefore passed
**explicitly** into `PaperSession.open_long` rather than regenerated inside it:
a resubmission arrives with the same `intent_id`, and `PaperPortfolio.apply`
refuses it. Had the application layer minted a fresh id on each call, the
backstop would have been decorative — it would have seen a new intent every
time and approved a second position.

Phase 5's asymmetry is preserved exactly: an **approved** id is consumed and
cannot be replayed; a **rejected** id is not consumed and the same intent can be
retried once conditions change.

### 9. View models format and nothing else

A `CONFLICTED` badge appears because `assessment.state` is `CONFLICTED`, never
because the UI inspected the counts and drew its own conclusion. Re-deriving
domain meaning in the presentation layer is how an interface becomes a second,
disagreeing implementation of the research rules.

The view models also own the project's timing vocabulary. `Bar opened`,
`Earliest this could be worked out`, `Earliest this assessment could exist` and
`Snapshot built` mean four different things, and none of them is when data
reached anyone. A test fails the build if wording implying provider arrival,
publication or a continuous feed appears in any Phase 7 file.

Because `ResearchObservation` and `ResearchAssessment` carry no `source`, the
interface attributes provenance to the build — *"Snapshot built from
&lt;source&gt;"* — and never to the assessment object.

### 10. Session-only paper state

Streamlit session state, nothing else. No journal, no database, no replay file.
The warning on the panel is worded to stay true whatever the installed Streamlit
does on a browser reconnect: it promises nothing and lists losing the session as
a reset. Overpromising persistence in a research tool that holds no real money
would be a strange risk to take.

### 11. Loopback binding, and therefore no authentication

`server.address = "127.0.0.1"` in `.streamlit/config.toml`, and the documented
run command passes the flag as well, so either alone is sufficient. The process
is reachable only from this machine, so there is nothing for an authentication
system to protect. A test asserts loopback is configured and that no Phase 7
runtime file *sets* `0.0.0.0` — while allowing the comment that warns against it,
because a documented prohibition is not a capability.

## Consequences

Refresh is a network call every time, so it is as slow as the provider and there
is no offline mode. That is the honest trade for never having to ask whether the
screen reflects what was requested.

The dashboard cannot answer "what changed since yesterday": a snapshot is a
point in time and nothing is retained. Any history feature needs the persistence
question answered properly rather than as a UI convenience.

Adding an interval means choosing a window that clears the warm-up floor, which
is deliberately a decision rather than a configuration line.

## Alternatives rejected

**A chart library (Plotly, Altair as a direct dependency).** Streamlit's built-in
`st.line_chart` is enough for a close series. A charting dependency would be
added for polish and would then have to be maintained.

**Auto-refresh on a timer.** It would make the dashboard a monitoring tool,
which is a different product with different failure modes, and would fetch
without a human asking.

**Caching the assessment separately from the bars.** The single most direct
route to the incoherent state this design exists to prevent.

**A "suggested notional" or any research-derived default on the action form.**
This is the automatic research-to-action path the whole project is built to
refuse. A default is a recommendation with a smaller font.
