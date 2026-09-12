# Grounded AI explanation of research evidence (Phase 11A)

An optional, explicitly requested explanation — in words — of a research
assessment the deterministic pipeline has already produced. It **explains**;
it does not predict, recommend, score or execute anything.

Everything that carries meaning on the Research tab — bars, features,
hypothesis classifications, the assessment, its counts and reason codes — is
still produced by Phases 1–6, exactly as before. Phase 11A adds one button,
*Explain with AI*, that sends a bounded view of that evidence to an external AI
provider and shows the answer only after it has been validated against the
evidence it was given.

The feature is off unless you configure it, and the dashboard is complete
without it.

## Purpose

- Explain deterministic research evidence in prose, with every statement
  cited back to the specific evidence it rests on.
- Not predict what a price will do.
- Not recommend an action, a size, a target or a direction.
- Not execute, open, close or size anything.

The deterministic assessment remains the authority. The explanation is *of*
it, is rendered below it, and adds no assessment of its own.

## Data flow

```
ResearchSnapshot              deterministic, already built by Refresh
    -> EvidencePacket         build_packet: bounded, pure, no I/O
    -> ReasoningRequest       provenance read from its owners, never retyped
    -> ReasoningProvider      one call to whichever provider was composed
    -> validate_provider_response
                              schema -> boundary language -> grounding -> consistency
    -> ReasoningSnapshot      trusted, immutable, session-only
    -> dashboard              rendered below the assessment it explains
```

`ReasoningService.explain` (`src/application/reasoning.py`) is the only
production path across that distance. `validate_provider_response`
(`src/reasoning/validation.py`) is the only production code that constructs a
`ReasoningSnapshot`; a boundary test enforces this because Python cannot.

## Authority boundary

Deterministic code owns, and the explanation cannot change:

- market data and the price basis
- feature values
- research observations (each hypothesis's classification and reason codes)
- the combined assessment, its state and its counts
- assessment reason codes
- the data cutoff
- scanner state and ordering
- paper positions and risk decisions

The external model owns exactly one thing: the wording of an explanation of
the bounded evidence it was shown. Its system instructions say so directly —
explain only the supplied evidence, cite an evidence id for every statement,
never invent an id, put anything the evidence does not settle under
*uncertainties*, and give no recommendation, target, size, probability or
confidence.

## Eligibility

Whether a snapshot can be explained is answered by
`ReasoningService.availability(snapshot)` and by nothing else. The dashboard
enables the button on that answer and the service repeats the check inside
`explain`, so the policy does not live in the interface.

- `NO_ASSESSMENT` — the snapshot has no assessment because no bars arrived.
  There is nothing to ground an explanation in, the button is disabled, and no
  provider is contacted.
- `AVAILABLE` — an assessment exists. `INSUFFICIENT_DATA` is a real
  assessment with real reason codes (a warming-up ensemble), so it **is**
  explainable; absence is not insufficiency.

The check builds the same `EvidencePacket` the explanation would send and asks
it, rather than inspecting `snapshot.assessment` directly, so the control and
the call can never disagree. It is local and free.

## Explicit action

- One selected `ResearchSnapshot`: the one on the Research tab.
- The user must press *Explain with AI*. Nothing is explained automatically.
- One click asks the provider at most once.
- No call is made on load, on a Streamlit rerun, on a widget change, on a
  symbol or interval change, or on a Refresh.
- There is no scanner-wide AI: Market Overview has no explanation control and
  the scanner never reaches the reasoning layer.
- No news or feed content reaches the reasoning layer.

## Composition and configuration

```
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=
```

Both variables are required together; see `.env.example`. There is **no
default model**: model identifiers age on their own schedule, and one
hardcoded in source would go stale quietly and then fail as though the
provider were down. A missing, blank, whitespace-only or malformed value
(`ANTHROPIC_MODEL` longer than 128 characters or containing control
characters) means `build_reasoning_service` returns `None` and the feature is
switched off — no exception, no client, no provider, no network. The status
line beside the disabled button names the variable to set and never its value.

Exactly two production files import the Anthropic SDK, and a test sweeps all
of `src` to keep it that way: `src/reasoning/anthropic_adapter.py` (the
transport, which receives an already-built client and holds no credential)
and `src/application/reasoning_composition.py` (the only place a client is
constructed and the only application- or dashboard-layer module that reads
either variable). The boundary suite asserts both that the composition
exemption exists and that it is exercised. The credential is read from the
environment mapping, passed to the client constructor as a keyword argument,
and not stored anywhere else — not as an attribute of the provider or the
service, not in a packet, request, fingerprint, snapshot or message. The
client that receives it necessarily holds it, and the client lives inside the
provider inside the service; the boundary kept is that the credential does not
escape the client. `src/dashboard/**` imports nothing from `src.reasoning`,
imports no vendor SDK, reads neither variable, and holds no name through which
a packet, request, provider call or validation could be driven directly.

The service is composed lazily the first time the Research tab needs it and
retained in session state as a dependency, exactly as the market provider is.
What is retained is the thing that asks, never anything it answered.

## Validation

Raw provider output is never trusted directly. `validate_provider_response`
runs four checks in order and constructs a `ReasoningSnapshot` only after all
of them pass:

1. **Schema** — the payload must be exactly `summary`, `claims` and
   `uncertainties`, with the declared shapes, sizes and no extra keys.
2. **Boundary language** — every model-authored string is refused if it
   contains trading vocabulary (buy/sell/hold, overweight, allocate,
   guarantee, target price, position size, expected return, stop loss and the
   rest), after Unicode folding and separator stripping. Negations are refused
   too: the disclaimer is rendered deterministically outside model output, so
   the vocabulary has no reason to appear at all.
3. **Grounding** — every cited `evidence_id` must name evidence the packet
   actually contains.
4. **Consistency** — a claim that repeats an earlier claim verbatim, with the
   same citations, is refused.

Validation checks what is structurally checkable. It does not attempt to
decide whether prose contradicts the assessment or overstates it; that needs
a reader.

A validation failure **fails closed**: no partial answer, no salvaged summary,
no repair, no retry. What the dashboard shows is the category of refusal and
nothing the model wrote.

## Failures

Three different facts, kept distinct all the way to the screen:

| What happened | Type | Codes | Rendered as |
|---|---|---|---|
| The provider did not answer | `ReasoningProviderError` | `authentication_failed`, `rate_limited`, `provider_unavailable`, `request_invalid`, `unexpected` | `st.error` — "No answer was received. Nothing about the research above has changed." |
| The provider answered and the answer was refused | `ReasoningValidationError` | `output_schema_failed`, `grounding_failed`, `boundary_violation` | `st.warning` — worded so the reader knows something came back and was declined |
| There was no assessment to explain | `ReasoningUnavailable` | — (an application `REQUEST` error, not a reasoning failure) | `st.info` — "No provider was contacted." |

Every message shown is chosen from a fixed table by code. The error's
`detail` field is never rendered, and the exception itself is never kept in
session state — only a `ReasoningFailureView` holding a category, a code and
two sentences.

## Session state and staleness

Session state holds exactly three reasoning keys, each a whole object or
`None`:

- `reasoning_service` — the composed service (a dependency, not a result)
- `reasoning_snapshot` — one trusted `ReasoningSnapshot`, never a raw
  response, request or packet
- `reasoning_failure` — one `ReasoningFailureView`, never the exception

Pressing the button clears both outcomes first, so exactly one is set
afterwards. A **successful** Refresh clears the explanation and the failure
(the research they describe has been replaced) and keeps the service; a
**failed** Refresh keeps everything, because the snapshot on screen is
unchanged.

Before a retained explanation is rendered it must pass a stale guard:

```
reasoning.symbol == snapshot.symbol
AND reasoning.data_cutoff == snapshot.built_at
```

The data cutoff is set by the evidence builder to the research snapshot's
`built_at`, so an explanation of any other snapshot is simply not shown.
Nothing is persisted: restarting the dashboard or losing the session discards
the explanation along with everything else.

## Privacy and egress

Pressing *Explain with AI* sends data to an **external AI provider, which
processes it outside this machine**. The privacy note above the button says so
every time. This document does not claim, and the dashboard never claims, that
no data leaves the machine.

The bounded evidence sent (`evidence_for_model` over `build_packet`) is:

- the symbol, interval and price basis
- the data cutoff (the snapshot's `built_at`)
- the warm-up bar count and the policy's minimum sufficient observations
- whether an assessment is present
- the assessment policy fingerprint
- the assessment state, its four counts, and its reason codes
- for each hypothesis observation: its hypothesis id, version, evidence id
  (derived from id, version and hypothesis fingerprint), classification,
  reason codes, the opening time of the bar it was evaluated at, and the
  feature values that hypothesis actually consulted

Not sent:

- raw or full market history (no `BarSeries`, no OHLCV rows)
- feature series (only the values a hypothesis recorded in its observation)
- news or company announcements
- external feed entries
- scanner results or the universe
- paper positions, intents or risk decisions
- application bookkeeping: the packet's `generated_at`, the evidence and
  reasoning fingerprints, and the schema versions (the policy fingerprint and
  each hypothesis fingerprint *are* sent, as evidence identity)

`build_packet` is pure and consults nothing but the snapshot passed to it: no
news, feeds, scanner, paper state, file or socket. What is not in the packet
cannot leave the machine.

## Safety and non-capabilities

- No recommendation, and no `BUY`/`SELL`/`HOLD` anywhere — refused by the
  output schema, the system instructions and the boundary-language check, and
  covered by a deterministic disclaimer rendered outside model output.
- No target price, expected return, confidence or probability score.
- No connection to paper actions: the reasoning layer has no path to a
  `PaperIntent`, and the paper panel is never shown an explanation.
- No broker, no execution.
- No automatic retry (SDK retries are explicitly set to zero; every call is
  one attempt), no fallback provider, no cache, no persistence.
- No background execution, scheduler or memoisation in the orchestration,
  and no logging of reasoning calls yet.
- No claim about the quality or usefulness of any particular model's output.
- No live provider acceptance run has been performed yet (see Deferred).

## Testing

Verified baseline for this phase: **5044 passed, 0 failed, 0 skipped**.

- Provider tests run offline against test-local fakes and hand-built
  payloads; the Anthropic adapter is exercised through a stand-in client at
  exactly the surface it uses.
- Dashboard tests seed a fake `ReasoningService` through session state and
  count calls, so "one click asks once and a rerun asks nothing" is a counted
  claim. An autouse fixture replaces `anthropic.Anthropic` so no test can
  reach a real client by accident; the one test that runs real composition
  replaces the constructor explicitly and never presses the button.
- Architecture boundaries are enforced by AST tests: the dashboard imports
  nothing from `src.reasoning` and no vendor SDK, the application layer
  imports no UI framework, exactly two production files import the vendor SDK
  and the composition exemption is exercised, and the orchestration module
  imports nothing that runs in the background, memoises, or logs.

## Deferred

Not part of Phase 11A; not started:

- an optional live provider smoke test
- logging and observability of reasoning calls
- caching or persistence of explanations
- Phase 12 outcome tracking
- Phase 11B outcome-aware reasoning
- news and feed content in reasoning
- Phase 13 error analysis

See [ADR 0009](adr/0009-grounded-reasoning.md) for the decision record, and
[docs/dashboard.md](dashboard.md) for the interface it sits in.
