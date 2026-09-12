# Local research dashboard (Phase 7)

A Streamlit interface for reading what Phases 1–6 already compute, plus a
manual paper-position panel. It adds **no research rule, no risk rule and no
new capability**: every state, count and reason code on screen was produced by
a domain module that existed before this phase.

Later phases add panels to this interface without changing that rule. Phase
11A adds an optional, explicitly requested **grounded AI explanation** of the
research evidence below the assessment — see the section near the end and
**[docs/reasoning.md](reasoning.md)**.

## Purpose

Until now the only way to look at a research assessment was to write a script.
Phase 7 makes the existing pipeline legible: pick a symbol and an interval,
press Refresh, and see the bars, the indicators, what each hypothesis
classified, and what the fixed policy made of them together.

It is a reading tool. It is not a trading application.

## Running it

```
streamlit run src/dashboard/app.py --server.address=127.0.0.1
```

Then open <http://127.0.0.1:8501>.

The dashboard binds to the loopback interface only, and `.streamlit/config.toml`
sets `server.address = "127.0.0.1"` as well, so forgetting the flag still cannot
expose it to your network. There is no authentication because there is nothing
to authenticate to: the process is reachable only from this machine. **Do not
change the bind address.** Everything about the design assumes a single local
reader.

## What a Refresh does

Every explicit Refresh performs the whole sequence, from the provider down:

```
human clicks Refresh
    -> resolve the history window from the interval
    -> provider.get_bars(symbol, start, end, interval, include_unsettled=False)
    -> build a RAW BarSeries
    -> deduplicate the required FeatureSpecs by spec.key
    -> build_evidence()
    -> evaluate the three hypotheses at the latest settled bar
    -> assess() under the fixed Phase 7 policy
    -> freeze a ResearchSnapshot
    -> replace the previous snapshot atomically
```

Nothing is fetched until you ask. The symbol box starts empty, the placeholder
`e.g. AAPL` is **an example of the format and not a suggestion**, and no company
assessment is pre-loaded on first launch.

Ordinary Streamlit interaction — typing, switching tabs, changing a widget —
re-renders the stored snapshot and fetches nothing.

## Supported intervals and history windows

| Interval | History fetched | Why |
|---|---|---|
| `1d` | 2 years | ample for the 51-bar warm-up |
| `1wk` | 3 years | about 150 bars |
| `1mo` | 10 years | about 120 bars; 2 years would be only 24 |

The window is derived from the interval, not typed by a user, and **there is no
start-date control**. A window is only useful if it clears the ensemble's
warm-up floor, and that is a property of the interval rather than a preference.

There are no intraday intervals in V1. The development provider keeps roughly a
month of 1-minute history, which is fewer bars than the ensemble needs, so an
intraday view would be permanently `INSUFFICIENT_DATA`.

## Settled bars only

Research always requests `include_unsettled=False`, and **the interface offers
no control to change that**. The bar currently forming has a close that keeps
moving, so an assessment built on it would not be reproducible an hour later.

## RAW prices only

V1 reads the raw price basis and shows it on the market panel. There is no
adjusted/raw toggle: adjustment needs corporate-action data this dashboard has
no source for, and a control that cannot work is worse than no control.

The view model still knows how to render the adjusted-history point-in-time
warning, and does so if an adjusted basis is ever passed to it, so the caveat
cannot quietly disappear if a later phase adds one.

## The research ensemble and policy

Fixed, and not editable from the interface:

- `trend_alignment`
- `momentum_in_trend_context`
- `trend_crossover`

Between them the three request seven feature specifications, which deduplicate
by `spec.key` to three actual computations — `sma(20)`, `sma(50)` and `rsi(14)`.
The deduplication is necessary rather than tidy: `build_evidence` raises on a
duplicate specification.

The assessment policy is `directional_presence_v1` with
`minimum_sufficient_observations = 2`, pinned to the three hypotheses' live
identities. Its fingerprint is displayed. Policy editing is not exposed —
adjusting a policy until it produces a preferred answer is not research.

## Minimum history

51 settled bars is the floor at which **every** hypothesis in the ensemble can
classify: `sma(50)` produces its first value on bar 50, and `trend_crossover`
declares `lookback = 1`, so it needs a prior bar that also has one.

It is a conservative ensemble requirement, **not** the point at which research
becomes possible. Because the policy needs only two sufficient observations,
the two `sma(50)`-based hypotheses can both classify on bar 50, so a directional
assessment is legitimately reachable one bar earlier than the floor.

| Bars returned | Behaviour |
|---|---|
| 0 | "No data for this symbol and interval." No crash, and not reported as `BEARISH` or `NEUTRAL`. |
| 1–49 | A normal research path. Every hypothesis is still warming up, so the assessment is legitimately `INSUFFICIENT_DATA`, and the panel says how many bars exist and how many are needed. |
| 50 | Two of the three hypotheses can classify, which meets the policy minimum, so a directional assessment is possible while `trend_crossover` is still warming up. The panel shows the state *and* notes that the ensemble is not fully warmed up. |
| 51+ | Every hypothesis can classify. |

The exact boundary depends on the ensemble and the policy minimum rather than on
any fixed law, which is why the interface reports the counts alongside the state
instead of asserting that a given number of bars was required.

A short history is **not** a provider fault and is never styled as one.

## Reading the assessment

The headline is one of `BULLISH`, `BEARISH`, `NEUTRAL`, `CONFLICTED` or
`INSUFFICIENT DATA`, taken directly from `assessment.state`. The panel always
shows the bullish, bearish, neutral, insufficient, sufficient and total counts,
the reason codes, the timing bound and the policy fingerprint.

There is no confidence, no probability and no score. The counts are counts, and
they show their denominator. Two of the three hypotheses are trend-family and
share inputs, so agreement is **not** independent confirmation.

`CONFLICTED` is kept distinct from `NEUTRAL` and is explained as what it is: at
least one sufficient hypothesis classified bullish and at least one classified
bearish, named individually. It is never rendered as a 50/50 or as low
confidence.

Every assessment carries: *Research information only — not a trading
recommendation.* There is no `BUY`, `SELL` or `HOLD` anywhere in the interface.

## Timing words

Three different fields mean three different things, and each has exactly one
approved label:

| Field | Label shown |
|---|---|
| `MarketBar.timestamp` | Bar opened |
| `ResearchObservation.evaluable_from` | Earliest this could be worked out |
| `ResearchAssessment.assessment_as_of` | Earliest this assessment could exist |
| `ResearchSnapshot.built_at` | Snapshot built |

None of them is when data reached anyone. This repository models no provider
latency and no exchange calendar, so `evaluable_from` is a **bound, not a
measurement**, and the interface must not be the first place to imply otherwise.
A test fails the build if misleading timing wording appears in any Phase 7 file.

## Provenance

`MarketBar` and `BarSeries` carry a `source`; `ResearchObservation` and
`ResearchAssessment` do not. The market panel therefore says *"Snapshot built
from &lt;source&gt;"* — a true statement about the build, owned by the application
layer — and provenance is never attached to the assessment object itself.

## Paper positions

The paper panel is separate from the research panel on purpose. The research
panel has **no paper-action control of any kind** — its only button, Phase
11A's *Explain with AI*, asks for words about what is already on screen and can
open or close nothing — and the paper panel is never given an assessment or an
explanation to display. Nothing in the interface turns "the research says
bullish" into a position; a human reads one and decides the other.

Only two actions exist, both manual:

- **OPEN_LONG** — you supply a symbol and a notional. Nothing pre-fills either,
  and the notional in particular is never defaulted from a research state.
- **CLOSE** — you pick one of your currently open positions.

Displayed for each position: id, symbol, notional, opened-at, and closed-at once
closed; plus total open notional and open-position count, and the configured
risk limits. There is deliberately **no quantity, price, cash, P&L, market value
or unrealised profit** — Phase 5 has no price semantics, so any of those would
be a number this system never computed.

A risk `REJECTED` is a normal outcome, shown with its reason codes, its intent
id and the policy fingerprint. It is not an error. Phase 5's semantics are
preserved exactly: an approved intent id is consumed and cannot be replayed; a
rejected one is not consumed and can be retried once conditions change.

### Optional research provenance

An unchecked-by-default control can attach a note recording which hypothesis you
were reading, labelled: *A note about what you were looking at — it does not
verify anything.* It preserves Phase 5's boundary — **preserved, not
authenticated**. Nothing checks it, and no provenance field can authorise,
justify or influence an action.

### Session-only state

> Paper positions are temporary. Nothing here is saved to disk. Restarting the
> dashboard, refreshing the browser tab, or losing the current session will
> reset the paper portfolio to empty. This is a research tool — no real money,
> no broker, no orders.

Paper state lives in Streamlit session state and nowhere else. There is no JSON
journal, no database, no replay file. Phase 7 opens no files at all — a test
asserts it.

## Reruns and duplicate actions

Streamlit re-runs the whole script on every interaction, so "apply this action"
written in ordinary rendering code would fire again on every rerun. Four
independent layers prevent a duplicate paper action:

1. both actions are inside an `st.form`, so nothing submits mid-edit;
2. `st.form_submit_button` reports true only on the run that carried the
   submission;
3. the intent and position ids are minted **before** the form renders, held
   across reruns, and passed explicitly into the application layer;
4. Phase 5 refuses an already-applied `intent_id` outright.

Layer 4 is the backstop that makes layer 3 worth having: because the captured
ids are passed in rather than regenerated, a submission that somehow arrived
twice reaches `PaperPortfolio.apply` with the *same* id and is refused instead
of creating a second position.

Mutation happens in exactly one place — `PaperSession.open_long` /
`close_position`. A test asserts that no dashboard module calls `.apply(`.

## Failure behaviour

A snapshot is built into a local variable and published only once every stage
has succeeded. If any stage fails you keep the previous complete snapshot and
see:

> Refresh failed at &lt;step&gt;: &lt;message&gt;. Showing the previous snapshot from
> &lt;built_at&gt;.

You never see new bars beside an older assessment, because there is no code path
that updates one field of a snapshot. Failures are classified — provider,
data-quality, request, domain, unexpected — so an upstream outage does not read
like a bug. An unexpected exception shows one safe sentence and writes the
traceback to the terminal, never to the interface.

## Grounded AI explanation (Phase 11A)

Below the assessment, the Research tab has one further control: **Explain with
AI**. Pressing it sends a bounded view of the evidence on screen — symbol,
interval, assessment state and counts, each hypothesis's classification, reason
codes, latest bar time and recorded evidence values — to an external AI
provider, and shows the answer only after the reasoning layer has validated it
against that evidence. Raw market history, news, feeds, scanner results and
paper positions are not sent, and a privacy note beside the button says so.

The explanation is *of* the deterministic assessment and adds no assessment of
its own. It is asked for, never assumed: nothing is explained on load, on a
rerun, on a widget change or on a Refresh, and one click asks at most once.

It is optional. The feature is composed from `ANTHROPIC_API_KEY` and
`ANTHROPIC_MODEL` inside the application layer
(`src/application/reasoning_composition.py`); with either unset the button is
disabled, a status line names the variable, and nothing else on the dashboard
changes. No dashboard module imports the vendor SDK or reads either variable.
The credential is read once, inside the composition module, and handed to the
vendor client; it is never rendered, never named in a message, and never
placed in a reasoning result or failure. The model id is shown, as the
provider reported it, in the Diagnostics expander of a trusted explanation.
Session state keeps the composed service (which holds the vendor client, as a
client must), one trusted explanation and one safe failure description — and
never a raw provider response or an exception. A successful Refresh discards
the explanation and the failure, and an explanation is rendered only while it
matches the snapshot on screen by symbol and data cutoff.

A provider failure, a rejected answer and a snapshot with nothing to explain
are rendered as three different things. A rejected answer is shown as its
rejection — no partial text is salvaged — and there is no retry, fallback or
cache. Full detail: **[docs/reasoning.md](reasoning.md)** and
**[ADR 0009](adr/0009-grounded-reasoning.md)**.

## Phase 7 non-goals

Not built, deliberately:

- no `CsvBarStore` reads, writes or merges; Refresh always goes to the provider
- no intraday intervals, no start-date editor, no adjusted-price toggle
- no policy, limit or ensemble editing from the interface
- no persistence of any kind, no database, no journal
- no scheduler, no background refresh, no continuous monitoring
- no broker, trading API, order, execution, or broker credential
- no LLM and no generated explanation *in Phase 7 itself*; Phase 11A adds an
  optional grounded AI explanation, composed from an API key that the
  application layer reads and no dashboard module reads (see above)
- no news ingestion, no notifications
- no authentication, no hosting, no non-loopback binding
- no confidence, probability, score or recommendation
