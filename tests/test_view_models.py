"""Phase 7 view models: faithful formatting and honest vocabulary.

A view model's job is to say exactly what the domain said. These tests are
mostly about what the presentation layer must *not* add: no recommendation, no
confidence, no re-derived state, and no timing claim this repository cannot
support.
"""

from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from src.application.paper import DEFAULT_RISK_POLICY, PaperSession
from src.application.snapshot import (
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    WARMUP_BARS,
    ResearchSnapshot,
    build_snapshot,
)
from src.application.view_models import (
    LABEL_ASSESSMENT_AS_OF,
    LABEL_BAR_OPENED,
    LABEL_EVALUABLE_FROM,
    LABEL_SNAPSHOT_BUILT,
    PAPER_SESSION_WARNING,
    PIT_WARNING,
    PROVENANCE_HELP,
    PROVENANCE_LABEL,
    RESEARCH_DISCLAIMER,
    WARMUP_NOTE,
    assessment_view,
    decision_view,
    feature_rows,
    humanise_reason,
    market_view,
    observation_views,
    portfolio_view,
    provenance_choices,
)
from src.assessments import (
    AssessmentAggregationRule,
    AssessmentPolicy,
    AssessmentState,
    HypothesisIdentity,
    assess,
)
from src.data.models import Interval
from src.data.series import BarSeries, PriceBasis
from src.strategies.research import ReasonCode, ResearchObservation, ResearchState

from tests.test_application_snapshot import CLOCK_NOW, RecordingProvider, clock

UTC = timezone.utc
BAR_TIME = datetime(2024, 6, 3, tzinfo=UTC)

IDS = [
    ("alpha_hypothesis", 1, "aaaaaaaaaaaaaaaa"),
    ("beta_hypothesis", 1, "bbbbbbbbbbbbbbbb"),
    ("gamma_hypothesis", 1, "cccccccccccccccc"),
]


def make_observations(states):
    """One observation per identity, all aligned to the same bar."""
    return tuple(
        ResearchObservation(
            hypothesis_id=identity,
            version=version,
            fingerprint=fingerprint,
            symbol="AAPL",
            interval=Interval.DAY_1,
            basis=PriceBasis.RAW,
            timestamp=BAR_TIME,
            state=state,
            evidence={"sma(field='close',period=20)": 101.5},
            reason_codes=(ReasonCode.FAST_ABOVE_SLOW,),
        )
        for (identity, version, fingerprint), state in zip(IDS, states)
    )


def make_assessment(states):
    observations = make_observations(states)
    policy = AssessmentPolicy(
        tuple(HypothesisIdentity(*identity) for identity in IDS),
        MINIMUM_SUFFICIENT_OBSERVATIONS,
        AssessmentAggregationRule.DIRECTIONAL_PRESENCE_V1,
    )
    return assess(observations, policy), observations


def view_for(states):
    assessment, observations = make_assessment(states)
    return assessment_view(
        assessment, observations, MINIMUM_SUFFICIENT_OBSERVATIONS
    )


B, R, N, I = (
    ResearchState.BULLISH,
    ResearchState.BEARISH,
    ResearchState.NEUTRAL,
    ResearchState.INSUFFICIENT_DATA,
)


# -- assessment state is reported, never re-derived ---------------------


def test_bullish_is_reported_faithfully():
    view = view_for([B, B, N])
    assert view.state == "BULLISH"
    assert view.is_conflicted is False
    assert view.is_insufficient is False


def test_bearish_is_reported_faithfully():
    view = view_for([R, R, N])
    assert view.state == "BEARISH"


def test_neutral_is_reported_faithfully():
    view = view_for([N, N, N])
    assert view.state == "NEUTRAL"


def test_conflicted_stays_conflicted():
    view = view_for([B, R, N])
    assert view.state == "CONFLICTED"
    assert view.is_conflicted is True
    assert view.state != "NEUTRAL"


def test_conflicted_is_explained_as_disagreement_not_probability():
    view = view_for([B, R, N])
    explanation = view.conflict_explanation.lower()
    assert "disagree" in explanation
    # The words may appear, but only to deny them -- never as a claim.
    assert "not a probability" in explanation
    for forbidden in ("confidence", "50/50", "%", "likely", "chance of"):
        assert forbidden not in explanation


def test_conflicted_names_both_sides():
    view = view_for([B, R, N])
    assert view.bullish_names == ("alpha_hypothesis",)
    assert view.bearish_names == ("beta_hypothesis",)


def test_insufficient_data_stays_a_research_state():
    view = view_for([I, I, I])
    assert view.state == "INSUFFICIENT DATA"
    assert view.is_insufficient is True


def test_insufficient_explanation_names_the_policy_minimum():
    view = view_for([I, I, I])
    text = view.insufficient_explanation
    assert "0 of 3" in text
    assert str(MINIMUM_SUFFICIENT_OBSERVATIONS) in text


def test_a_state_the_view_did_not_compute_comes_from_the_record():
    """The label follows assessment.state even when the counts look otherwise."""
    assessment, observations = make_assessment([B, R, N])
    view = assessment_view(assessment, observations, MINIMUM_SUFFICIENT_OBSERVATIONS)
    assert assessment.state is AssessmentState.CONFLICTED
    assert view.state == "CONFLICTED"


# -- counts and reasons --------------------------------------------------


def test_counts_are_exact():
    view = view_for([B, R, N])
    assert (view.bullish, view.bearish, view.neutral, view.insufficient) == (1, 1, 1, 0)
    assert view.sufficient == 3
    assert view.total == 3


def test_counts_with_a_warming_up_hypothesis():
    view = view_for([B, B, I])
    assert (view.bullish, view.bearish, view.neutral, view.insufficient) == (2, 0, 0, 1)
    assert view.sufficient == 2
    assert view.total == 3


@pytest.mark.parametrize(
    "states, expected_state, expected_reasons",
    [
        ([B, B, N], "BULLISH", ("directional bullish with neutral",)),
        ([R, R, N], "BEARISH", ("directional bearish with neutral",)),
        ([N, N, N], "NEUTRAL", ("unanimous neutral",)),
        ([B, R, N], "CONFLICTED", ("conflicting directional evidence",)),
        (
            [I, I, I],
            "INSUFFICIENT DATA",
            ("insufficient evidence", "insufficient inputs excluded"),
        ),
        (
            [R, R, I],
            "BEARISH",
            ("unanimous bearish", "insufficient inputs excluded"),
        ),
    ],
)
def test_reason_codes_are_faithful_to_the_record(
    states, expected_state, expected_reasons
):
    """Written out literally rather than recomputed.

    Deriving the expectation with ``humanise_reason`` -- the same function
    production uses -- would pass even if that function started inventing
    words. These strings are the independent expectation.
    """
    assessment, observations = make_assessment(states)
    view = assessment_view(assessment, observations, MINIMUM_SUFFICIENT_OBSERVATIONS)
    assert view.state == expected_state
    assert view.reasons == expected_reasons


def test_reason_code_order_is_deterministic():
    first = view_for([I, I, I]).reasons
    for _ in range(25):
        assert view_for([I, I, I]).reasons == first


def test_observation_order_does_not_change_the_rendered_record():
    """The domain is order-invariant; the view model must not reintroduce order."""
    import itertools

    baseline = None
    for permutation in itertools.permutations([B, R, N]):
        view = view_for(list(permutation))
        key = (
            view.state,
            view.bullish,
            view.bearish,
            view.neutral,
            view.reasons,
            view.policy_fingerprint,
        )
        baseline = key if baseline is None else baseline
        assert key == baseline


def test_humanise_reason_only_replaces_underscores():
    assert humanise_reason(ReasonCode.FAST_ABOVE_SLOW) == "fast above slow"


def test_policy_fingerprint_is_visible():
    assessment, observations = make_assessment([B, B, N])
    view = assessment_view(assessment, observations, MINIMUM_SUFFICIENT_OBSERVATIONS)
    assert view.policy_fingerprint == assessment.policy_fingerprint
    assert view.policy_fingerprint


# -- short history explanation ------------------------------------------


def test_short_history_note_is_absent_without_bar_counts():
    view = view_for([I, I, I])
    assert view.short_history_note is None


def test_short_history_note_names_the_warmup_floor():
    assessment, observations = make_assessment([I, I, I])
    view = assessment_view(
        assessment,
        observations,
        MINIMUM_SUFFICIENT_OBSERVATIONS,
        bar_count=10,
        warmup_bars=WARMUP_BARS,
    )
    note = view.short_history_note
    assert "10 settled bars" in note
    assert str(WARMUP_BARS) in note
    assert note in view.insufficient_explanation


def test_short_history_note_absent_once_history_is_sufficient():
    assessment, observations = make_assessment([I, I, I])
    view = assessment_view(
        assessment,
        observations,
        MINIMUM_SUFFICIENT_OBSERVATIONS,
        bar_count=500,
        warmup_bars=WARMUP_BARS,
    )
    assert view.short_history_note is None


def test_insufficient_data_is_not_worded_as_a_crash():
    assessment, observations = make_assessment([I, I, I])
    view = assessment_view(
        assessment,
        observations,
        MINIMUM_SUFFICIENT_OBSERVATIONS,
        bar_count=10,
        warmup_bars=WARMUP_BARS,
    )
    text = view.insufficient_explanation.lower()
    for forbidden in ("error", "crash", "failed", "exception", "bug"):
        assert forbidden not in text


# -- observations --------------------------------------------------------


def test_observation_view_carries_full_identity():
    views = observation_views(make_observations([B, R, N]))
    first = views[0]
    assert first.hypothesis_id == "alpha_hypothesis"
    assert first.version == 1
    assert first.fingerprint == "aaaaaaaaaaaaaaaa"
    assert first.label == "alpha_hypothesis@v1#aaaaaaaaaaaaaaaa"


def test_observation_display_name_falls_back_to_the_id():
    views = observation_views(make_observations([B, R, N]))
    assert views[0].display_name == "alpha_hypothesis"
    named = observation_views(
        make_observations([B, R, N]), {"alpha_hypothesis": "Alpha"}
    )
    assert named[0].display_name == "Alpha"


def test_observation_states_are_faithful():
    views = observation_views(make_observations([B, R, I]))
    assert [v.state for v in views] == ["BULLISH", "BEARISH", "NOT ENOUGH HISTORY YET"]
    assert [v.is_insufficient for v in views] == [False, False, True]


def test_observation_evidence_renders_warmup_not_zero():
    observation = ResearchObservation(
        hypothesis_id="alpha_hypothesis",
        version=1,
        fingerprint="aaaaaaaaaaaaaaaa",
        symbol="AAPL",
        interval=Interval.DAY_1,
        basis=PriceBasis.RAW,
        timestamp=BAR_TIME,
        state=ResearchState.INSUFFICIENT_DATA,
        evidence={"sma(field='close',period=50)": None},
        reason_codes=(ReasonCode.WARMUP_INCOMPLETE,),
    )
    view = observation_views((observation,))[0]
    assert view.evidence == (("sma(field='close',period=50)", WARMUP_NOTE),)
    assert "0" not in view.evidence[0][1]


# -- market, basis and source -------------------------------------------


def snapshot_with(basis: PriceBasis, count: int = 80) -> ResearchSnapshot:
    built = build_snapshot(RecordingProvider(count), "AAPL", Interval.DAY_1, now=clock)
    if basis is PriceBasis.RAW:
        return built
    # Deliberately constructed: V1 never fetches adjusted data, but the view
    # model must still tell the truth if a future extension passes it.
    return ResearchSnapshot(
        symbol=built.symbol,
        interval=built.interval,
        basis=basis,
        source=built.source,
        series=built.series,
        features=built.features,
        decision_index=built.decision_index,
        observations=built.observations,
        assessment=built.assessment,
        policy_fingerprint=built.policy_fingerprint,
        history_label=built.history_label,
        built_at=built.built_at,
    )


def test_raw_basis_is_displayed():
    view = market_view(snapshot_with(PriceBasis.RAW))
    assert view.basis == "raw"
    assert view.is_adjusted is False


def test_no_pit_warning_for_raw_history():
    assert market_view(snapshot_with(PriceBasis.RAW)).pit_warning is None


def test_pit_warning_appears_if_an_adjusted_basis_is_ever_passed():
    view = market_view(snapshot_with(PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED))
    assert view.is_adjusted is True
    assert view.pit_warning == PIT_WARNING
    assert "point-in-time" in view.pit_warning


def test_source_is_attributed_to_the_snapshot_not_the_assessment():
    view = market_view(snapshot_with(PriceBasis.RAW))
    assert view.source_note == "Snapshot built from fake"
    assert "assessment" not in view.source_note.lower()


def test_assessment_view_carries_no_source_field():
    """Observations and assessments do not record a provider; do not imply one."""
    view = view_for([B, B, N])
    assert not hasattr(view, "source")


def test_market_view_reports_the_real_bar_count_and_window():
    snapshot = snapshot_with(PriceBasis.RAW, 80)
    view = market_view(snapshot)
    assert view.bar_count == 80
    assert view.history_label == "2 years of daily bars"
    assert view.symbol == "AAPL"
    assert view.interval == "1d"


def test_market_view_rows_are_limited_and_ordered():
    view = market_view(snapshot_with(PriceBasis.RAW, 80), recent=5)
    assert len(view.rows) == 5
    assert view.columns[0] == LABEL_BAR_OPENED


def test_empty_market_view_has_no_rows():
    view = market_view(snapshot_with(PriceBasis.RAW, 0))
    assert view.rows == ()
    assert view.bar_count == 0
    assert view.latest_bar_opened == "—"


# -- features ------------------------------------------------------------


def test_feature_rows_are_labelled_readably_and_canonically():
    rows = feature_rows(snapshot_with(PriceBasis.RAW, 80))
    names = {row.name for row in rows}
    assert names == {"SMA 20", "SMA 50", "RSI 14"}
    assert all(row.key for row in rows)


def test_feature_warmup_renders_as_text_never_zero():
    rows = feature_rows(snapshot_with(PriceBasis.RAW, 5))
    warming = [row for row in rows if row.is_warming_up]
    assert warming
    for row in warming:
        assert row.value == WARMUP_NOTE
        assert row.value != "0"
        assert row.value != "0.0000"


def test_feature_values_render_when_ready():
    rows = feature_rows(snapshot_with(PriceBasis.RAW, 80))
    ready = [row for row in rows if not row.is_warming_up]
    assert ready
    for row in ready:
        assert row.value != WARMUP_NOTE


# -- timing vocabulary ---------------------------------------------------


def test_the_four_timing_labels_are_the_approved_wording():
    assert LABEL_BAR_OPENED == "Bar opened"
    assert LABEL_EVALUABLE_FROM == "Earliest this could be worked out"
    assert LABEL_ASSESSMENT_AS_OF == "Earliest this assessment could exist"
    assert LABEL_SNAPSHOT_BUILT == "Snapshot built"


def test_assessment_as_of_is_taken_from_the_record():
    assessment, observations = make_assessment([B, B, N])
    view = assessment_view(assessment, observations, MINIMUM_SUFFICIENT_OBSERVATIONS)
    assert assessment.assessment_as_of.strftime("%Y-%m-%d") in view.assessment_as_of


def test_evaluable_from_is_the_bar_open_plus_one_interval():
    view = observation_views(make_observations([B, R, N]))[0]
    expected = BAR_TIME + Interval.DAY_1.max_duration
    assert expected.strftime("%Y-%m-%d") in view.evaluable_from


#: Phrases that would claim something this repository does not model: provider
#: latency, publication time, or a live feed.
FORBIDDEN_TIMING = (
    "real-time",
    "realtime",
    "real time",
    "live data",
    "live price",
    "streaming",
    "up to the minute",
    "up-to-the-minute",
    "as it happens",
    "tick data",
    "last traded",
    "data arrived at",
    "published at",
    "received at",
)

PHASE_7_SOURCES = (
    "src/application/view_models.py",
    "src/application/snapshot.py",
    "src/application/paper.py",
    "src/application/errors.py",
    "src/dashboard/app.py",
    "src/dashboard/research_view.py",
    "src/dashboard/paper_view.py",
    "src/dashboard/reasoning_view.py",
    "docs/dashboard.md",
    "docs/adr/0005-local-dashboard.md",
)


@pytest.mark.parametrize("path", PHASE_7_SOURCES)
def test_no_misleading_timing_claims_anywhere_in_phase_seven(path):
    text = pathlib.Path(path).read_text().lower()
    for phrase in FORBIDDEN_TIMING:
        assert phrase not in text, f"{path} contains misleading timing wording {phrase!r}"


# -- no recommendation language -----------------------------------------

FORBIDDEN_ACTION_WORDS = ("buy", "sell", "hold")


def _public_surface(obj) -> set[str]:
    """Every name a renderer could read off this view model.

    ``vars()`` alone is not enough: it returns instance attributes only, so a
    ``confidence`` *property* declared on the class would be invisible to it
    while still being fully renderable.
    """
    return {name for name in dir(obj) if not name.startswith("_")} | set(vars(obj))


def test_assessment_view_carries_no_recommendation_or_score():
    view = view_for([B, B, N])
    surface = _public_surface(view)
    for forbidden in (
        "confidence", "probability", "score", "recommendation", "action",
        "signal", "advice", "rating", "strength", "conviction",
    ):
        offenders = [name for name in surface if forbidden in name.lower()]
        assert not offenders, f"AssessmentView exposes {offenders}"


def test_no_phase_seven_view_model_exposes_a_score():
    """The same rule for every view model, properties included."""
    from src.application import view_models as module

    session = PaperSession()
    session.open_long("AAPL", "1000")
    snapshot = snapshot_with(PriceBasis.RAW, 80)
    samples = [
        view_for([B, R, N]),
        market_view(snapshot),
        feature_rows(snapshot)[0],
        observation_views(make_observations([B, R, N]))[0],
        portfolio_view(session.portfolio, session.policy),
        decision_view(session.last_decision),
    ]
    for sample in samples:
        surface = _public_surface(sample)
        for forbidden in ("confidence", "probability", "score", "recommendation"):
            offenders = [name for name in surface if forbidden in name.lower()]
            assert not offenders, f"{type(sample).__name__} exposes {offenders}"


def test_no_rendered_value_is_a_percentage():
    """A percentage would read as a confidence however it was labelled."""
    view = view_for([B, B, N])
    rendered = [view.state, view.disclaimer, *view.reasons,
                view.assessment_as_of, view.policy_fingerprint]
    for text in rendered:
        assert "%" not in text


def test_assessment_wording_contains_no_order_verbs():
    view = view_for([B, B, N])
    text = " ".join(
        [view.state, view.disclaimer, *view.reasons, view.conflict_explanation or ""]
    ).lower()
    for word in FORBIDDEN_ACTION_WORDS:
        assert f" {word} " not in f" {text} "


def test_research_disclaimer_is_present_and_explicit():
    view = view_for([B, B, N])
    assert view.disclaimer == RESEARCH_DISCLAIMER
    assert "not a trading recommendation" in RESEARCH_DISCLAIMER.lower()


@pytest.mark.parametrize("path", PHASE_7_SOURCES)
def test_no_phase_seven_source_emits_a_buy_sell_or_hold_instruction(path):
    """Guards rendered strings, not comments about the rule itself."""
    text = pathlib.Path(path).read_text().lower()
    for phrase in ("recommend buying", "recommend selling", "you should buy",
                   "you should sell", "signal to buy", "signal to sell"):
        assert phrase not in text


# -- paper view models ---------------------------------------------------


def test_session_warning_is_present_and_promises_nothing():
    view = portfolio_view(PaperSession().portfolio, DEFAULT_RISK_POLICY)
    assert view.session_warning == PAPER_SESSION_WARNING
    lowered = PAPER_SESSION_WARNING.lower()
    assert "nothing here is saved to disk" in lowered
    assert "reset the paper portfolio to empty" in lowered
    assert "no real money" in lowered and "no broker" in lowered


def test_portfolio_view_shows_the_real_configured_limits():
    view = portfolio_view(PaperSession().portfolio, DEFAULT_RISK_POLICY)
    assert view.max_open_positions == DEFAULT_RISK_POLICY.max_open_positions
    assert view.allow_duplicate_symbol is DEFAULT_RISK_POLICY.allow_duplicate_symbol
    assert view.open_position_count == 0
    assert view.open_rows == ()


def test_position_rows_expose_only_phase_five_semantics():
    session = PaperSession()
    session.open_long("AAPL", "1000")
    view = portfolio_view(session.portfolio, session.policy)
    row = view.open_rows[0]
    fields = set(vars(row))
    assert fields == {"position_id", "symbol", "notional", "opened_at", "closed_at"}
    for invented in ("quantity", "price", "cash", "pnl", "market_value"):
        assert invented not in fields


def test_closed_position_row_shows_both_timestamps():
    session = PaperSession()
    session.open_long("AAPL", "1000")
    session.close_position(session.open_positions[0].position_id)
    view = portfolio_view(session.portfolio, session.policy)
    row = view.closed_rows[0]
    assert row.opened_at != "—"
    assert row.closed_at != "—"


def test_decision_view_reports_a_rejection_as_normal():
    session = PaperSession()
    decision = session.open_long("AAPL", "999999")
    view = decision_view(decision)
    assert view.approved is False
    assert view.outcome == "REJECTED"
    assert "normal outcome" in view.note
    assert view.intent_id == decision.intent_id
    assert view.policy_fingerprint == decision.policy_fingerprint
    assert view.reasons


def test_decision_view_reports_an_approval():
    session = PaperSession()
    view = decision_view(session.open_long("AAPL", "1000"))
    assert view.approved is True
    assert view.outcome == "APPROVED"


# -- provenance ----------------------------------------------------------


def test_provenance_choices_offer_each_observation():
    choices = provenance_choices(make_observations([B, R, N]))
    assert len(choices) == 3
    assert choices[0].hypothesis_id == "alpha_hypothesis"
    assert choices[0].observation_timestamp == BAR_TIME


def test_provenance_wording_disclaims_verification():
    assert "does not verify" in PROVENANCE_LABEL.lower()
    assert "authorise" in PROVENANCE_HELP.lower() or "authorize" in PROVENANCE_HELP.lower()


# -- grounded AI explanation (Phase 11A Stage F2) -------------------------
#
# The trusted snapshot is produced the only way production produces one: a
# real ReasoningService, a recording provider whose payload is grounded in the
# real packet, and the real validator. Nothing here constructs a
# ReasoningSnapshot by hand.

from src.application.reasoning import (  # noqa: E402
    ReasoningFailureCode,
    ReasoningProviderError,
    ReasoningSnapshot,
    ReasoningUnavailable,
    ReasoningValidationError,
)
from src.application.view_models import (  # noqa: E402
    FAILURE_PROVIDER,
    FAILURE_UNAVAILABLE,
    FAILURE_VALIDATION,
    REASONING_DISCLAIMER,
    REASONING_HEADING,
    REASONING_NO_ASSESSMENT,
    REASONING_PRIVACY_NOTE,
    ReasoningClaimView,
    ReasoningExplanationView,
    ReasoningFailureView,
    explanation_is_current,
    reasoning_explanation_view,
    reasoning_failure_view,
)
from tests.test_application_reasoning import explaining  # noqa: E402

SECRET_MARKER = "SYNTHETIC-KEY-MARKER-F2-NEVER-RENDER"


@pytest.fixture
def research():
    return build_snapshot(RecordingProvider(count=120), "AAPL", Interval.DAY_1, now=clock)


@pytest.fixture
def trusted(research) -> ReasoningSnapshot:
    service, _ = explaining(research)
    return service.explain(research)


def _every_string(view) -> list[str]:
    out: list[str] = []
    for name in dir(view):
        if name.startswith("_"):
            continue
        value = getattr(view, name)
        if isinstance(value, str):
            out.append(value)
        elif isinstance(value, tuple):
            for item in value:
                if isinstance(item, str):
                    out.append(item)
                elif isinstance(item, tuple):
                    out.extend(s for s in item if isinstance(s, str))
                elif isinstance(item, ReasoningClaimView):
                    out.append(item.text)
                    out.extend(item.evidence_ids)
                    out.append(item.citation)
    return out


def test_explanation_view_carries_the_trusted_summary_and_its_evidence(trusted):
    view = reasoning_explanation_view(trusted)
    assert isinstance(view, ReasoningExplanationView)
    assert view.summary == trusted.summary.text
    assert view.summary_evidence_ids == tuple(trusted.summary.evidence_ids)
    assert view.summary_citation.startswith("Evidence: ")
    for evidence_id in trusted.summary.evidence_ids:
        assert evidence_id in view.summary_citation


def test_explanation_view_carries_every_claim_with_its_citations(trusted):
    view = reasoning_explanation_view(trusted)
    assert len(view.claims) == len(trusted.claims)
    for shown, claim in zip(view.claims, trusted.claims):
        assert isinstance(shown, ReasoningClaimView)
        assert shown.text == claim.text
        assert shown.evidence_ids == tuple(claim.evidence_ids)
        for evidence_id in claim.evidence_ids:
            assert evidence_id in shown.citation


def test_explanation_view_carries_the_uncertainties_verbatim(trusted):
    view = reasoning_explanation_view(trusted)
    assert view.uncertainties == tuple(trusted.uncertainties)
    assert view.uncertainties


def test_explanation_view_identity_and_timing_come_from_the_record(trusted, research):
    view = reasoning_explanation_view(trusted)
    assert view.symbol == trusted.symbol == research.symbol
    assert view.data_cutoff == trusted.data_cutoff.strftime("%Y-%m-%d %H:%M %Z").strip()
    assert view.generated_at == trusted.generated_at.strftime("%Y-%m-%d %H:%M %Z").strip()
    assert view.heading == REASONING_HEADING
    assert view.disclaimer == REASONING_DISCLAIMER


def test_explanation_diagnostics_show_usage_provider_model_and_fingerprints(trusted):
    view = reasoning_explanation_view(trusted)
    rows = dict(view.diagnostics)
    usage = trusted.usage
    assert rows["Provider"] == usage.provider
    assert rows["Model (as reported by the provider)"] == usage.model
    assert rows["Input tokens"] == f"{usage.input_tokens:,}"
    assert rows["Output tokens"] == f"{usage.output_tokens:,}"
    assert rows["Latency"] == f"{usage.latency_ms:,} ms"
    assert rows["Attempts"] == str(usage.attempt_count)
    assert rows["Evidence fingerprint"] == trusted.evidence_fingerprint
    assert rows["Reasoning fingerprint"] == trusted.reasoning_fingerprint
    assert rows["Prompt"] == f"{trusted.prompt_id} v{trusted.prompt_version}"


def test_explanation_diagnostics_carry_no_cost_prompt_text_or_credential(trusted):
    view = reasoning_explanation_view(trusted)
    labels = [label.lower() for label, _ in view.diagnostics]
    for forbidden in ("cost", "price", "usd", "$", "key", "credential", "packet",
                      "payload", "raw", "confidence", "score", "probability",
                      "rating", "conviction", "signal"):
        assert not [l for l in labels if forbidden in l], forbidden
    # Pinned exactly: a new row has to be argued for here.
    assert [label for label, _ in view.diagnostics] == [
        "Provider", "Model (as reported by the provider)", "Input tokens",
        "Output tokens", "Latency", "Attempts", "Evidence fingerprint",
        "Reasoning fingerprint", "Prompt", "Output schema",
    ]
    for _, value in view.diagnostics:
        assert "$" not in value
        assert SECRET_MARKER not in value


def test_explanation_view_is_immutable(trusted):
    view = reasoning_explanation_view(trusted)
    with pytest.raises(Exception):
        view.summary = "changed"  # type: ignore[misc]
    with pytest.raises(Exception):
        view.claims[0].text = "changed"  # type: ignore[misc]
    assert isinstance(view.claims, tuple)
    assert isinstance(view.diagnostics, tuple)


def test_explanation_view_exposes_no_score_confidence_or_recommendation(trusted):
    view = reasoning_explanation_view(trusted)
    for sample in (view, view.claims[0]):
        surface = _public_surface(sample)
        for forbidden in ("confidence", "probability", "score", "recommendation",
                          "signal", "target", "entry", "exit", "allocation",
                          "position", "rating", "prediction"):
            offenders = [name for name in surface if forbidden in name.lower()]
            assert not offenders, f"{type(sample).__name__} exposes {offenders}"


def test_reasoning_wording_is_explanatory_and_denies_recommendation():
    assert REASONING_HEADING == "AI explanation of research evidence"
    for forbidden in ("recommendation", "prediction", "signal", "trade"):
        assert forbidden not in REASONING_HEADING.lower()
    assert "not a trading recommendation" in REASONING_DISCLAIMER.lower()
    import re

    from src.application import view_models as module

    # Every reasoning-facing string constant the module defines, disclaimer
    # and guidance included, checked on word stems so "buying" is caught as
    # well as "buy".
    constants = [value for name, value in vars(module).items()
                 if isinstance(value, str) and name.isupper()
                 and ("REASONING" in name or "FAILURE" in name or "UNAVAILABLE" in name)]
    assert REASONING_DISCLAIMER in constants
    joined = " ".join(constants).lower()
    for stem in ("buy", "sell", "hold", "long", "short", "entry", "exit",
                 "target", "stop loss", "position size", "allocation",
                 "expected return", "confidence", "probability", "conviction",
                 "score", "rating", "signal", "prediction", "predict", "forecast"):
        assert not re.search(rf"\b{stem}\w*", joined), stem


def test_the_privacy_note_states_what_is_sent_and_what_is_not():
    low = REASONING_PRIVACY_NOTE.lower()
    assert "bounded view" in low
    assert "research evidence" in low
    # What the evidence builder actually puts in the packet, named: the symbol
    # is the most identifying thing that leaves the machine, so it is said.
    for sent in ("symbol", "interval", "assessment state", "counts",
                 "classification", "reason codes", "latest bar time",
                 "evidence values"):
        assert sent in low, sent
    assert "sends" in low or "sent" in low
    assert "external ai provider" in low
    assert "outside this machine" in low
    assert "generated locally" in low
    assert "deterministic" in low
    for not_sent in ("raw market history", "news", "external feeds",
                     "scanner results", "paper positions"):
        assert not_sent in low, not_sent
    assert "are not sent" in low
    for misleading in ("no data leaves", "nothing leaves", "never leaves",
                       "stays on your machine", "does not leave"):
        assert misleading not in low, misleading


# -- staleness --------------------------------------------------------------


def test_a_trusted_explanation_is_current_for_the_research_it_explained(trusted, research):
    assert explanation_is_current(trusted, research)


def test_an_explanation_of_another_symbol_is_not_current(trusted):
    other = build_snapshot(RecordingProvider(count=120), "MSFT", Interval.DAY_1, now=clock)
    assert other.built_at == trusted.data_cutoff  # same clock -- symbol alone differs
    assert not explanation_is_current(trusted, other)


def test_an_explanation_of_an_older_build_is_not_current(trusted):
    later = build_snapshot(
        RecordingProvider(count=120), "AAPL", Interval.DAY_1,
        now=lambda: clock() + timedelta(minutes=1),
    )
    assert later.symbol == trusted.symbol
    assert not explanation_is_current(trusted, later)


def test_currency_reads_only_symbol_and_cutoff_off_the_record(trusted, research):
    """No packet is rebuilt and no fingerprint recomputed to answer this."""
    import ast
    import inspect

    from src.application import view_models

    tree = ast.parse(inspect.getsource(view_models.explanation_is_current))
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert attrs == {"symbol", "data_cutoff", "built_at"}, attrs
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert not calls


# -- failure mapping --------------------------------------------------------


PROVIDER_CODES = [
    ReasoningFailureCode.AUTHENTICATION_FAILED,
    ReasoningFailureCode.RATE_LIMITED,
    ReasoningFailureCode.PROVIDER_UNAVAILABLE,
    ReasoningFailureCode.REQUEST_INVALID,
    ReasoningFailureCode.UNEXPECTED,
]
VALIDATION_CODES = [
    ReasoningFailureCode.OUTPUT_SCHEMA_FAILED,
    ReasoningFailureCode.GROUNDING_FAILED,
    ReasoningFailureCode.BOUNDARY_VIOLATION,
]


@pytest.mark.parametrize("code", PROVIDER_CODES, ids=lambda c: c.value)
def test_every_provider_failure_maps_to_a_safe_provider_view(code):
    view = reasoning_failure_view(ReasoningProviderError(code, SECRET_MARKER))
    assert isinstance(view, ReasoningFailureView)
    assert view.kind == FAILURE_PROVIDER
    assert view.is_provider_failure and not view.is_validation_failure
    assert not view.is_unavailable
    assert view.code == code.value
    assert view.message and view.guidance
    for text in _every_string(view):
        assert SECRET_MARKER not in text
        assert "Traceback" not in text
    assert "provider" in view.message.lower()


@pytest.mark.parametrize("code", VALIDATION_CODES, ids=lambda c: c.value)
def test_every_validation_failure_maps_to_a_distinct_rejection_view(code):
    view = reasoning_failure_view(ReasoningValidationError(code, SECRET_MARKER))
    assert view.kind == FAILURE_VALIDATION
    assert view.is_validation_failure and not view.is_provider_failure
    assert view.code == code.value
    low = view.message.lower()
    assert "returned an answer" in low
    assert "refused to display" in low
    for text in _every_string(view):
        assert SECRET_MARKER not in text


def test_the_provider_messages_name_the_remedy_by_code():
    def message(code):
        return reasoning_failure_view(ReasoningProviderError(code, "x")).message.lower()

    assert "credential" in message(ReasoningFailureCode.AUTHENTICATION_FAILED)
    assert "slower request rate" in message(ReasoningFailureCode.RATE_LIMITED)
    unavailable = message(ReasoningFailureCode.PROVIDER_UNAVAILABLE)
    assert "unavailable" in unavailable and "timed out" in unavailable
    assert "network" in unavailable
    invalid = message(ReasoningFailureCode.REQUEST_INVALID)
    assert "rejected the request" in invalid and "model" in invalid
    assert "unexpectedly" in message(ReasoningFailureCode.UNEXPECTED)


def test_the_validation_messages_name_the_category_by_code():
    def message(code):
        return reasoning_failure_view(ReasoningValidationError(code, "x")).message.lower()

    assert "required structure" in message(ReasoningFailureCode.OUTPUT_SCHEMA_FAILED)
    grounding = message(ReasoningFailureCode.GROUNDING_FAILED)
    assert "evidence it was not given" in grounding
    assert "explanation boundary" in message(ReasoningFailureCode.BOUNDARY_VIOLATION)


def test_provider_and_validation_failures_do_not_collapse():
    rate = reasoning_failure_view(
        ReasoningProviderError(ReasoningFailureCode.RATE_LIMITED, "x")
    )
    grounding = reasoning_failure_view(
        ReasoningValidationError(ReasoningFailureCode.GROUNDING_FAILED, "x")
    )
    assert rate.kind != grounding.kind
    assert rate.message != grounding.message
    assert rate.guidance != grounding.guidance
    assert "returned an answer" not in rate.message.lower()
    assert "returned an answer" in grounding.message.lower()
    # Neither is a generic "AI error".
    for view in (rate, grounding):
        assert view.message.lower() not in {"ai error", "an error occurred", "error"}


def test_unavailable_maps_to_the_local_no_assessment_state():
    view = reasoning_failure_view(ReasoningUnavailable("nothing to explain"))
    assert view.kind == FAILURE_UNAVAILABLE
    assert view.is_unavailable
    assert not view.is_provider_failure and not view.is_validation_failure
    assert view.message == REASONING_NO_ASSESSMENT
    assert "provider" not in view.message.lower()
    assert "no provider was contacted" in view.guidance.lower()
    assert view.code == ""


def test_the_failure_view_retains_no_exception_and_no_detail():
    error = ReasoningProviderError(ReasoningFailureCode.RATE_LIMITED, SECRET_MARKER)
    view = reasoning_failure_view(error)
    for name in vars(view):
        value = getattr(view, name)
        assert not isinstance(value, BaseException)
        assert isinstance(value, str)
    assert error.detail == SECRET_MARKER  # the detail exists ...
    assert SECRET_MARKER not in repr(view)  # ... and never reaches the view


def test_the_failure_view_is_immutable():
    view = reasoning_failure_view(
        ReasoningProviderError(ReasoningFailureCode.UNEXPECTED, "x")
    )
    with pytest.raises(Exception):
        view.message = "changed"  # type: ignore[misc]


def test_the_failure_mapper_refuses_unknown_exceptions():
    """A programming error is not laundered into a provider outage."""
    for error in (ValueError("x"), KeyError("k"), RuntimeError("r"), Exception("e")):
        with pytest.raises(TypeError):
            reasoning_failure_view(error)


def test_failure_messages_contain_no_recommendation_or_percentage():
    views = [reasoning_failure_view(ReasoningProviderError(c, "x")) for c in PROVIDER_CODES]
    views += [reasoning_failure_view(ReasoningValidationError(c, "x")) for c in VALIDATION_CODES]
    views.append(reasoning_failure_view(ReasoningUnavailable("x")))
    for view in views:
        for text in (view.message, view.guidance):
            assert "%" not in text
            low = f" {text.lower()} "
            for word in FORBIDDEN_ACTION_WORDS:
                assert f" {word} " not in low


def test_reasoning_view_construction_touches_no_network_or_filesystem(
    monkeypatch, trusted, research
):
    import builtins
    import socket

    def forbidden(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("view model reached outside the process")

    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    reasoning_explanation_view(trusted)
    reasoning_failure_view(ReasoningProviderError(ReasoningFailureCode.RATE_LIMITED, "x"))
    assert explanation_is_current(trusted, research)
