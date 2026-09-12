# ADR 0009 — Grounded AI explanation of deterministic research evidence

**Status**: accepted (Phase 11A)

## Problem

Ten phases built a research pipeline whose every output is a classification, a
count or a reason code, and whose every phase refused to turn any of them into
an instruction. A language model is the first component that can produce
fluent prose, and fluent prose is where a research tool most easily stops
being one. The value on offer is real — a `CONFLICTED` assessment with six
reason codes is legible to a specialist and opaque to everyone else — but the
ways a model can undo the previous ten phases are specific and worth naming.

**Hallucination.** A model asked about a company will happily describe the
company. Nothing in the pipeline knows what the company does, and an
explanation that mentions earnings, sector or news would be citing evidence
that was never computed.

**Advice creep.** The output schema has a text field. Text fields hold "this
looks like a buying opportunity" as easily as they hold "two of three
hypotheses classified bullish", and a reader cannot tell which sentences the
system stands behind.

**Prediction creep.** "Bullish" is a label for what the evidence looks like.
A model restating it as "the stock is likely to rise" converts a
classification into a forecast the system never made and Phase 4 measures
nothing about.

**Uncontrolled egress.** Whatever the model is shown leaves the machine. A
convenient design hands it the snapshot; the snapshot holds two years of bars,
and the session next to it holds news, feeds, a scanner table and paper
positions.

**Hidden retries and cost.** Vendor SDKs retry by default. One click that
silently becomes three calls is a cost the user did not authorise and a rate
limit they cannot reason about.

**Stale explanation.** Streamlit re-renders on every interaction. An
explanation kept in session state outlives the research it described the
moment Refresh is pressed, and a stale paragraph beside fresh bars is exactly
the failure ADR 0005 built `ResearchSnapshot` to make unrepresentable.

**Coupling reasoning to trade actions.** The paper panel is one import away.
An explanation that could reach a `PaperIntent` — or a paper panel that could
read an explanation — would be the first path from research to position that
this repository has ever had.

## Decisions

### The deterministic system remains the authority

Every value with meaning — bars, features, observations, assessment, counts,
reason codes, data cutoff, scanner order, paper state — is produced by
Phases 1–10 exactly as before. The model produces prose about those values
and nothing else. It cannot alter, extend or re-judge any of them, and the
deterministic assessment is rendered first, with the explanation below it.

### The model sees bounded evidence only

`build_packet` copies scalar facts out of a `ResearchSnapshot` into an
`EvidencePacket` — symbol, interval, basis, cutoff, policy identity, the
assessment and its counts and codes, and each observation's classification,
reason codes, bar time and recorded feature values — and holds no reference to
the snapshot, its `BarSeries` or its `FeatureSeries`. It is pure and consults
no news, feed, scanner, paper state, file or socket. What is not in the packet
cannot leave the machine, and the privacy note above the button lists what is.

Feature series are deliberately excluded even though they are on the snapshot.
An observation already records the values its hypothesis consulted; a full
series would let the model reason from indicator values no deterministic rule
looked at.

### Explicit user action, one selected snapshot

An explanation happens when a person presses *Explain with AI* for the
research on screen, and at no other time: not on load, rerun, widget change,
symbol change or Refresh. One click is at most one provider call. There is no
scanner-wide explanation and no batch.

### Schema-constrained output, and the validator is the trust boundary

The model must return exactly `summary`, `claims` and `uncertainties`, each
statement carrying the evidence ids it rests on. `validate_provider_response`
checks schema, then boundary language, then grounding, then consistency, and
is the only production code that constructs a `ReasoningSnapshot`. Raw
provider output is never rendered, stored or partially salvaged: a refused
answer is shown as its category of refusal and nothing the model wrote.

The validator checks what is structurally checkable — shapes, citations,
vocabulary — and does not pretend to judge whether prose overstates evidence.
The defences that do not depend on wording are the real ones: a schema with
nowhere to put advice, a disclaimer rendered outside model output, and no path
from reasoning to a paper action.

### A provider abstraction in the application layer; Anthropic is a composition detail

`ReasoningService` depends on a `ReasoningProvider` contract and knows no
vendor. The Anthropic adapter is a transport that receives an already-built
client, holds no credential and reads nothing from the process. The two are
joined in `src/application/reasoning_composition.py`, the only application- or
dashboard-layer file permitted to import the SDK or read either variable — an
exemption the boundary suite asserts is both granted and exercised. Exactly
two production files import the SDK — the adapter and the composition module
— and the dashboard imports neither the SDK nor anything from `src.reasoning`.

### Optional configuration, no default model

`ANTHROPIC_API_KEY` and `ANTHROPIC_MODEL` are both required, and absence,
blankness or a malformed value switches the feature off with no exception, no
client and no request. There is no default model id: one written into source
would go stale silently and resurface as an apparent outage. The status line
names the variable to set and never its value.

### Fail closed

A provider failure, a validation refusal and an unexplainable snapshot are
three distinct facts and render three distinct ways (`st.error`,
`st.warning`, `st.info`), each from a fixed sentence chosen by code. No raw
error detail is rendered, no exception is retained in session state, and there
is no retry, no fallback provider, no repair of a rejected answer and no cache.
SDK retries are set to zero explicitly on every call.

### Stale-result protection

Session state holds one trusted `ReasoningSnapshot` and one
`ReasoningFailureView`, each whole or `None`. A successful Refresh clears both,
because the research they described has been replaced. Before rendering, an
explanation must match the snapshot on screen by symbol and by
`data_cutoff == snapshot.built_at`; any other explanation is not shown.

### No authority over paper trading or the scanner

The reasoning layer imports no paper, scanner, news or feed module, and the
boundary tests fail if it does. The paper panel is never shown an explanation,
and no explanation can produce a `PaperIntent`.

## Alternatives rejected

**Let the model interpret raw market history.** The obvious design: hand it
the bars and ask what it sees. It would make the model a fourth, unversioned,
unfingerprinted hypothesis whose classification cannot be reproduced,
evaluated by Phase 4 or aggregated by Phase 6 — and it would send two years of
prices to an external service to do it.

**Let the model decide the research classification.** Even with bounded
evidence, asking "is this bullish?" makes the answer the model's rather than
the policy's. The counts, the reason codes and the policy fingerprint exist so
that a classification is reproducible from stated rules. A model's verdict has
no fingerprint.

**Let the model generate trade recommendations.** The most requested shape
and the one every prior phase was built to refuse. It is excluded three ways —
schema, system instructions, vocabulary check — because a text field that may
hold advice is, in practice, a text field that will.

**Call the vendor directly from the dashboard.** Fewer files. It would put a
credential read and a vendor type inside a Streamlit script, make the
explanation path testable only through a browser, and break the three-layer
rule ADR 0005 enforces by AST.

**Explain automatically on every Refresh or symbol change.** Convenient, and
it would make every Refresh a paid request the user did not ask for, send
evidence to an external service without a click, and — through Streamlit's
rerun model — risk sending it several times. The same reasoning kept the
scanner manual in ADR 0008.

**Scanner-wide batch explanations.** A hundred symbols is a hundred calls, a
hundred egress events and a table of prose beside a table of classifications,
which is a ranking with commentary. The scanner's ordering was designed to
resist exactly that reading.

**Accept raw provider output without validation.** Simpler, and it would mean
rendering whatever came back — an invented evidence id, a buy, a target price
— under the project's name. The validator exists so that what is shown is
what was checked.

**A hardcoded or default vendor model.** One fewer variable to set. Model ids
are operational configuration that age on their own schedule; a default would
fail months later in a way that looks like a provider outage rather than a
configuration mistake.

**Automatic retry or fallback in v1.** A transient rate limit would be
smoother with one retry. But a retry is a second paid call the user did not
press for, a fallback model is an answer from something other than what was
configured, and both hide the failure the user needs to see to reason about
cost. One click, one call, one honest result.

## Consequences

Positive:

* Every statement in an explanation cites evidence that exists in the
  packet, and the packet is reconstructible from the snapshot — the
  explanation is grounded and auditable rather than plausible.
* The feature is optional: with no configuration the dashboard is unchanged,
  and no user of the project must acquire an API key.
* Deterministic authority is preserved by construction. The model cannot
  change a state, a count or a code.
* The provider is replaceable behind one contract, and the vendor is one
  composition file.
* Egress and cost are bounded: one click, one call, a listed set of fields.
* Failures are contained and distinguishable; nothing the validator refused
  reaches a reader in whole or in part.

Negative:

* An explanation can fail after the provider succeeded — a well-formed answer
  that cites an unknown id or uses a forbidden word is refused, and the user
  sees a warning rather than the text. This is the design working, but it will
  read as a failure.
* Explicit configuration is required and there is no default model, so the
  feature does nothing until two variables are set correctly.
* There is no automatic convenience: no explanation appears without a click,
  and Refresh discards the previous one.
* Evidence ids are technical (`obs:<hypothesis>:v<version>:<fingerprint>#<feature>`) and
  are rendered as-is; a friendlier citation would need presentation work not
  done here.
* The external provider receives the bounded evidence. Pressing the button is
  an egress event and is disclosed as one; nothing here claims otherwise.
* No live-provider acceptance run has been performed. The adapter is verified
  against a stand-in client at the surface it uses, not against the vendor.

## Deferred

* An optional live provider smoke test.
* Logging and observability of reasoning calls — `logging` is on the
  orchestration module's forbidden-import list until it is designed, because
  the first thing a log line would be handed is an error detail.
* Caching or persistence of explanations.
* Phase 12 outcome tracking, and Phase 11B outcome-aware reasoning on top of
  it.
* News and feed content in reasoning.
* Phase 13 error analysis.

See [docs/reasoning.md](../reasoning.md) for the architecture as built.
