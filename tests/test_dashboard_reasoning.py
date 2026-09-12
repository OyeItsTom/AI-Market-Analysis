"""Phase 11A Stage F2: the dashboard's grounded AI explanation, end to end.

Driven through ``AppTest`` against the real script, with the one thing that
would reach a network -- the composed ``ReasoningService`` -- seeded through
session state exactly as the market provider is. The fake records every call,
so "one click asks once and a rerun asks nothing" is a countable claim rather
than a reading of the code.

What the fake returns is produced the way production produces it: Stage E's
real ``ReasoningService`` over a recording provider whose payload is grounded
in the real packet, validated by the real validator. Nothing here constructs a
trusted snapshot by hand, and nothing here contacts a vendor -- the one test
that lets the real composition run replaces the vendor constructor first and
never presses the button.
"""

from __future__ import annotations

import ast
import pathlib
from datetime import timedelta

import pytest
from streamlit.testing.v1 import AppTest

from src.application.reasoning import (
    ReasoningAvailability,
    ReasoningFailureCode,
    ReasoningProviderError,
    ReasoningService,
    ReasoningSnapshot,
    ReasoningUnavailable,
    ReasoningValidationError,
)
from src.application.snapshot import build_snapshot
from src.application.view_models import (
    PAPER_SESSION_WARNING,
    REASONING_HEADING,
    REASONING_NO_ASSESSMENT,
    REASONING_PRIVACY_NOTE,
    ReasoningFailureView,
)
from src.data.models import Interval
from tests.test_application_reasoning import RecordingReasoningProvider, explaining
from tests.test_application_snapshot import CLOCK_NOW, RecordingProvider, clock

REPO = pathlib.Path(__file__).resolve().parent.parent
APP_PATH = REPO / "src" / "dashboard" / "app.py"
APP = str(APP_PATH)

BUTTON = "explain_with_ai_button"
#: Never a real credential. Asserted absent from every rendered element.
SECRET_MARKER = "SYNTHETIC-KEY-MARKER-F2-NEVER-RENDER"
#: Stands in for text a model might have written and validation refused.
MODEL_TEXT_MARKER = "MODEL-WROTE-THIS-AND-IT-WAS-REFUSED"


@pytest.fixture(autouse=True)
def no_real_vendor_client(monkeypatch):
    """No test here may reach the real vendor client by accident.

    A real client under a socket trap is not loud: the adapter maps the
    refused connection to PROVIDER_UNAVAILABLE and the dashboard renders a
    safe error, so a test that quietly composed one would pass. Refusing the
    constructor itself turns that into an exception on the run that built it.
    The one test that exercises real composition replaces this with its own
    recorder, explicitly.
    """
    import anthropic

    def refuse(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError(
            "a dashboard test reached the real vendor client; seed a fake "
            "ReasoningService or replace anthropic.Anthropic explicitly"
        )

    monkeypatch.setattr(anthropic, "Anthropic", refuse)


# -- the double ------------------------------------------------------------


class FakeReasoningService:
    """Counts what it is asked; answers as scripted, or for real.

    ``availability`` and a successful ``explain`` delegate to Stage E's real
    service so the answers are the real ones for the snapshot on screen. A
    scripted ``failure`` is raised from ``explain`` instead, and a scripted
    ``availability`` overrides the real answer so the defensive path -- the
    gate says yes and the call says no -- can be exercised.
    """

    def __init__(self, *, failure: Exception | None = None,
                 availability: ReasoningAvailability | None = None):
        self.failure = failure
        self.forced_availability = availability
        self.explain_calls: list = []
        self.availability_calls: list = []

    def availability(self, snapshot):
        self.availability_calls.append(snapshot)
        if self.forced_availability is not None:
            return self.forced_availability
        real = ReasoningService(RecordingReasoningProvider(payload={}))
        return real.availability(snapshot)

    def explain(self, snapshot):
        self.explain_calls.append(snapshot)
        if self.failure is not None:
            raise self.failure
        service, _ = explaining(snapshot)
        return service.explain(snapshot)


def trusted_for(symbol: str = "AAPL", *, count: int = 120, now=clock) -> ReasoningSnapshot:
    """A real trusted snapshot for research built with the given clock."""
    research = build_snapshot(RecordingProvider(count=count), symbol, Interval.DAY_1, now=now)
    service, _ = explaining(research)
    return service.explain(research)


# -- driving the app ----------------------------------------------------------


def start(bar_count: int = 120, *, service=None, seed_service: bool = True) -> AppTest:
    app = AppTest.from_file(APP, default_timeout=60)
    app.session_state["provider"] = RecordingProvider(bar_count)
    app.session_state["clock"] = clock
    if seed_service:
        app.session_state["reasoning_service"] = (
            FakeReasoningService() if service is None else service
        )
    app.run()
    assert not app.exception, app.exception
    return app


def press(app: AppTest, key: str) -> AppTest:
    for button in app.button:
        if button.key == key:
            return button.click().run()
    raise AssertionError(f"no button with key {key!r}; have {[b.key for b in app.button]}")


def refreshed(app: AppTest, symbol: str = "AAPL") -> AppTest:
    app.sidebar.text_input(key="symbol_input").set_value(symbol)
    app = press(app, "refresh_button")
    assert not app.exception, app.exception
    return app


def explain_button(app: AppTest):
    matches = [b for b in app.button if b.key == BUTTON]
    assert len(matches) == 1, [b.key for b in app.button]
    return matches[0]


def session_keys(app: AppTest) -> set[str]:
    """Every non-widget session key, as AppTest exposes them."""
    return set(app.session_state.filtered_state)


def service_of(app: AppTest) -> FakeReasoningService:
    return app.session_state["reasoning_service"]


def rendered_text(app: AppTest) -> str:
    """Everything a person could read, in every element kind the app uses."""
    parts: list[str] = []
    for kind in ("markdown", "caption", "subheader", "info", "warning", "error",
                 "text", "title", "header", "success"):
        parts += [str(e.value) for e in getattr(app, kind)]
    for element in app.dataframe:
        # to_string, not str: a DataFrame's repr elides wide cells, and a scan
        # for a secret must read every cell in full.
        parts.append(element.value.to_string())
    for button in app.button:
        parts.append(button.label)
        parts.append(str(getattr(button, "help", "") or ""))
    return "\n".join(parts)


def warnings(app: AppTest) -> list[str]:
    """Warnings other than the paper panel's permanent session notice."""
    return [w.value for w in app.warning if w.value != PAPER_SESSION_WARNING]


def summary_text(app: AppTest) -> str:
    """The trusted summary the fake service produces, from the real payload."""
    return "Two hypotheses classified the trend upward and one was neutral."


def is_rendered(app: AppTest) -> bool:
    return summary_text(app) in rendered_text(app)


# -- 48: available ------------------------------------------------------------


def test_the_ai_section_appears_after_the_assessment_and_asks_nothing():
    app = refreshed(start())
    assert REASONING_HEADING in [s.value for s in app.subheader]
    order = [s.value for s in app.subheader]
    assert order.index("Research assessment") < order.index(REASONING_HEADING)
    assert service_of(app).explain_calls == []
    assert not explain_button(app).disabled
    assert not is_rendered(app)


def test_an_explicit_click_asks_once_and_renders_the_trusted_explanation():
    app = refreshed(start())
    app = press(app, BUTTON)
    assert not app.exception, app.exception
    service = service_of(app)
    assert len(service.explain_calls) == 1
    assert service.explain_calls[0] is app.session_state["snapshot"]
    retained = app.session_state["reasoning_snapshot"]
    assert isinstance(retained, ReasoningSnapshot)
    assert app.session_state["reasoning_failure"] is None
    assert is_rendered(app)
    text = rendered_text(app)
    assert "What the evidence shows" in text
    assert "What the evidence does not establish" in text
    for evidence_id in retained.cited_evidence_ids:
        assert evidence_id in text
    assert not app.error and not warnings(app)


def test_the_explanation_is_labelled_as_an_explanation_not_a_recommendation():
    app = press(refreshed(start()), BUTTON)
    text = rendered_text(app).lower()
    for forbidden in ("ai recommendation", "ai prediction", "ai signal",
                      "trade recommendation", "target price", "stop loss",
                      "position size", "expected return"):
        assert forbidden not in text, forbidden
    assert "not a trading recommendation" in text


# -- 49: no assessment ------------------------------------------------------


def test_no_assessment_disables_the_button_and_asks_nothing():
    app = refreshed(start(0))
    assert app.session_state["snapshot"].assessment is None
    service = service_of(app)
    assert service.availability_calls, "eligibility must be the service's answer"
    assert explain_button(app).disabled
    assert REASONING_NO_ASSESSMENT in [i.value for i in app.info]
    assert service.explain_calls == []
    # A disabled control cannot be pressed: AppTest refuses exactly as a
    # browser would. Rerunning changes nothing either.
    with pytest.raises(Exception, match="disabled"):
        press(app, BUTTON)
    app.run()
    assert service_of(app).explain_calls == []
    assert app.session_state["reasoning_snapshot"] is None
    assert app.session_state["reasoning_failure"] is None


# -- 50: insufficient data --------------------------------------------------


def test_insufficient_data_is_still_explainable():
    app = refreshed(start(1))
    snapshot = app.session_state["snapshot"]
    assert snapshot.assessment is not None
    assert snapshot.assessment.state.value == "insufficient_data"
    assert not explain_button(app).disabled
    app = press(app, BUTTON)
    assert not app.exception, app.exception
    assert len(service_of(app).explain_calls) == 1
    assert isinstance(app.session_state["reasoning_snapshot"], ReasoningSnapshot)


# -- 51: unconfigured -------------------------------------------------------


def test_unconfigured_ai_leaves_research_working_and_the_button_disabled(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    app = refreshed(start(seed_service=False))
    assert app.session_state["reasoning_service"] is None
    assert app.session_state["snapshot"].symbol == "AAPL"
    subheaders = [s.value for s in app.subheader]
    for expected in ("Market", "Research assessment", REASONING_HEADING):
        assert expected in subheaders
    assert explain_button(app).disabled
    guidance = [i.value for i in app.info if "AI explanation is unavailable" in i.value]
    assert len(guidance) == 1
    assert "ANTHROPIC_API_KEY is not configured" in guidance[0]
    assert "Everything else on this dashboard works without it" in guidance[0]
    assert app.session_state["reasoning_snapshot"] is None
    assert app.session_state["reasoning_failure"] is None
    # The disabled control cannot be pressed, and a rerun composes nothing.
    with pytest.raises(Exception, match="disabled"):
        press(app, BUTTON)
    app.run()
    assert not app.exception
    assert app.session_state["reasoning_service"] is None


def test_unconfigured_ai_is_information_not_a_provider_or_validation_failure(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    app = refreshed(start(seed_service=False))
    assert not app.error
    assert not warnings(app)
    assert app.session_state["reasoning_failure"] is None


# -- 52, 53: provider failures ----------------------------------------------


def test_a_rate_limited_provider_is_reported_safely():
    error = ReasoningProviderError(ReasoningFailureCode.RATE_LIMITED, SECRET_MARKER)
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    assert not app.exception, app.exception
    assert len(service_of(app).explain_calls) == 1
    assert app.session_state["reasoning_snapshot"] is None
    failure = app.session_state["reasoning_failure"]
    assert isinstance(failure, ReasoningFailureView)
    assert failure.is_provider_failure
    assert any("slower request rate" in e.value for e in app.error)
    assert SECRET_MARKER not in rendered_text(app)
    assert not is_rendered(app)


def test_an_authentication_failure_never_shows_the_credential(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_MARKER)
    monkeypatch.setenv("ANTHROPIC_MODEL", "model-y")
    error = ReasoningProviderError(
        ReasoningFailureCode.AUTHENTICATION_FAILED, f"rejected {SECRET_MARKER}"
    )
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    assert any("rejected the configured credential" in e.value for e in app.error)
    text = rendered_text(app)
    assert SECRET_MARKER not in text
    assert "model-y" not in text
    failure = app.session_state["reasoning_failure"]
    assert SECRET_MARKER not in repr(failure)
    assert app.session_state["reasoning_snapshot"] is None


@pytest.mark.parametrize("code", [
    ReasoningFailureCode.PROVIDER_UNAVAILABLE,
    ReasoningFailureCode.REQUEST_INVALID,
    ReasoningFailureCode.UNEXPECTED,
], ids=lambda c: c.value)
def test_every_other_provider_failure_is_an_error_without_detail(code):
    error = ReasoningProviderError(code, SECRET_MARKER)
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    assert app.error
    assert not warnings(app)
    assert SECRET_MARKER not in rendered_text(app)
    assert app.session_state["reasoning_failure"].code == code.value


# -- 54, 55, 56: validation failures ----------------------------------------


def test_a_grounding_failure_is_a_distinct_rejection_with_no_answer_shown():
    error = ReasoningValidationError(
        ReasoningFailureCode.GROUNDING_FAILED, MODEL_TEXT_MARKER
    )
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    assert not app.exception, app.exception
    assert app.session_state["reasoning_snapshot"] is None
    failure = app.session_state["reasoning_failure"]
    assert failure.is_validation_failure
    assert not app.error, "a refused answer is not an outage"
    assert any("evidence it was not given" in w for w in warnings(app))
    assert any("returned an answer" in w for w in warnings(app))
    text = rendered_text(app)
    assert MODEL_TEXT_MARKER not in text
    assert "What the evidence shows" not in text
    assert not is_rendered(app)


def test_an_output_schema_failure_renders_nothing_partial():
    error = ReasoningValidationError(
        ReasoningFailureCode.OUTPUT_SCHEMA_FAILED, MODEL_TEXT_MARKER
    )
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    assert any("required structure" in w for w in warnings(app))
    text = rendered_text(app)
    assert MODEL_TEXT_MARKER not in text
    assert "What the evidence shows" not in text
    assert "What the evidence does not establish" not in text
    assert "Diagnostics" not in text
    assert app.session_state["reasoning_snapshot"] is None


def test_a_boundary_violation_shows_no_prohibited_text():
    error = ReasoningValidationError(
        ReasoningFailureCode.BOUNDARY_VIOLATION, MODEL_TEXT_MARKER
    )
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    assert any("explanation boundary" in w for w in warnings(app))
    assert MODEL_TEXT_MARKER not in rendered_text(app)
    assert app.session_state["reasoning_snapshot"] is None
    assert not app.error


def test_provider_and_validation_failures_read_differently():
    rate = ReasoningProviderError(ReasoningFailureCode.RATE_LIMITED, "x")
    grounding = ReasoningValidationError(ReasoningFailureCode.GROUNDING_FAILED, "x")
    rate_app = press(refreshed(start(service=FakeReasoningService(failure=rate))), BUTTON)
    grounding_app = press(
        refreshed(start(service=FakeReasoningService(failure=grounding))), BUTTON
    )
    assert rate_app.error and not warnings(rate_app)
    assert warnings(grounding_app) and not grounding_app.error
    assert [e.value for e in rate_app.error] != warnings(grounding_app)


# -- 57: defensive unavailable ----------------------------------------------


def test_an_unavailable_raised_past_the_gate_is_the_local_state_not_an_outage():
    service = FakeReasoningService(
        failure=ReasoningUnavailable("nothing to ground in"),
        availability=ReasoningAvailability.AVAILABLE,
    )
    app = refreshed(start(0, service=service))
    assert not explain_button(app).disabled
    app = press(app, BUTTON)
    assert not app.exception, app.exception
    assert len(service_of(app).explain_calls) == 1
    failure = app.session_state["reasoning_failure"]
    assert failure.is_unavailable
    assert not app.error
    assert not warnings(app)
    assert REASONING_NO_ASSESSMENT in [i.value for i in app.info]
    assert app.session_state["reasoning_snapshot"] is None


# -- 58, 59: rerun protection and explicit second click ---------------------


def test_a_rerun_and_a_widget_change_never_ask_again():
    app = press(refreshed(start()), BUTTON)
    assert len(service_of(app).explain_calls) == 1
    app.run()
    assert len(service_of(app).explain_calls) == 1
    assert is_rendered(app)
    # An unrelated widget: the paper form's symbol box.
    app.text_input(key="open_symbol").set_value("MSFT").run()
    assert len(service_of(app).explain_calls) == 1
    assert is_rendered(app)
    # The research symbol box, without pressing Refresh.
    app.sidebar.text_input(key="symbol_input").set_value("MSFT").run()
    assert len(service_of(app).explain_calls) == 1
    assert is_rendered(app), "the retained explanation is still about the research on screen"


def test_a_second_deliberate_click_asks_again():
    app = press(refreshed(start()), BUTTON)
    first = app.session_state["reasoning_snapshot"]
    app = press(app, BUTTON)
    assert len(service_of(app).explain_calls) == 2
    second = app.session_state["reasoning_snapshot"]
    assert isinstance(second, ReasoningSnapshot)
    assert second is not first


def test_nothing_is_asked_on_load_refresh_or_scan():
    app = refreshed(start())
    assert service_of(app).explain_calls == []
    app = press(app, "refresh_button")
    assert service_of(app).explain_calls == []
    app = press(app, "refresh_news_button")
    assert service_of(app).explain_calls == []
    assert app.session_state["reasoning_snapshot"] is None


# -- 60: refresh invalidation -----------------------------------------------


def test_a_successful_refresh_discards_the_explanation_and_keeps_the_service():
    app = press(refreshed(start()), BUTTON)
    service = service_of(app)
    assert app.session_state["reasoning_snapshot"] is not None
    app = press(app, "refresh_button")
    assert not app.exception
    assert app.session_state["reasoning_snapshot"] is None
    assert app.session_state["reasoning_failure"] is None
    assert app.session_state["reasoning_service"] is service
    assert len(service.explain_calls) == 1
    assert not is_rendered(app)


def test_a_successful_refresh_discards_a_failure_too():
    error = ReasoningProviderError(ReasoningFailureCode.RATE_LIMITED, "x")
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    assert app.session_state["reasoning_failure"] is not None
    app = press(app, "refresh_button")
    assert app.session_state["reasoning_failure"] is None
    assert not app.error


def test_a_failed_refresh_keeps_the_explanation_of_the_snapshot_still_on_screen():
    app = press(refreshed(start()), BUTTON)

    class Broken(RecordingProvider):
        def get_bars(self, *args, **kwargs):
            from src.data.provider import ProviderUnavailableError

            raise ProviderUnavailableError("upstream down")

    app.session_state["provider"] = Broken()
    app = press(app, "refresh_button")
    assert any("Refresh failed at" in e.value for e in app.error)
    assert app.session_state["reasoning_snapshot"] is not None
    assert is_rendered(app)


# -- 61: the render-time staleness guard ------------------------------------


def test_a_retained_explanation_of_another_symbol_is_not_rendered():
    app = refreshed(start())
    app.session_state["reasoning_snapshot"] = trusted_for("MSFT")
    app.run()
    assert not app.exception
    assert app.session_state["reasoning_snapshot"].symbol == "MSFT"
    assert app.session_state["snapshot"].symbol == "AAPL"
    assert not is_rendered(app)
    assert service_of(app).explain_calls == []


def test_a_retained_explanation_of_another_build_is_not_rendered():
    app = refreshed(start())
    stale = trusted_for("AAPL", now=lambda: CLOCK_NOW - timedelta(hours=1))
    assert stale.symbol == app.session_state["snapshot"].symbol
    assert stale.data_cutoff != app.session_state["snapshot"].built_at
    app.session_state["reasoning_snapshot"] = stale
    app.run()
    assert not app.exception
    assert not is_rendered(app)
    assert service_of(app).explain_calls == []


def test_a_retained_explanation_of_this_build_is_rendered():
    app = refreshed(start())
    current = trusted_for("AAPL")
    assert current.data_cutoff == app.session_state["snapshot"].built_at
    app.session_state["reasoning_snapshot"] = current
    app.run()
    assert is_rendered(app)
    assert service_of(app).explain_calls == []


# -- 62, 63: one outcome at a time ------------------------------------------


def test_a_failed_re_explanation_clears_the_previous_success():
    app = press(refreshed(start()), BUTTON)
    assert is_rendered(app)
    service_of(app).failure = ReasoningProviderError(
        ReasoningFailureCode.PROVIDER_UNAVAILABLE, "x"
    )
    app = press(app, BUTTON)
    assert app.session_state["reasoning_snapshot"] is None
    assert app.session_state["reasoning_failure"] is not None
    assert not is_rendered(app)
    assert app.error


def test_a_successful_re_explanation_clears_the_previous_failure():
    error = ReasoningValidationError(ReasoningFailureCode.GROUNDING_FAILED, "x")
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    assert warnings(app)
    service_of(app).failure = None
    app = press(app, BUTTON)
    assert app.session_state["reasoning_failure"] is None
    assert isinstance(app.session_state["reasoning_snapshot"], ReasoningSnapshot)
    assert not warnings(app)
    assert is_rendered(app)


# -- 41, 42: service lifetime and configuration ------------------------------


def test_the_service_is_composed_lazily_once_and_retained(monkeypatch):
    import src.application

    fake = FakeReasoningService()
    composed: list[int] = []

    def factory(*args, **kwargs):
        composed.append(1)
        return fake

    monkeypatch.setattr(src.application, "build_reasoning_service", factory)
    app = start(seed_service=False)
    assert composed == [], "nothing is composed before the Research tab needs it"
    app = refreshed(app)
    assert composed == [1]
    assert app.session_state["reasoning_service"] is fake
    app.run()
    app = press(app, BUTTON)
    assert composed == [1], "the retained service is reused across reruns"
    assert app.session_state["reasoning_service"] is fake
    assert len(fake.explain_calls) == 1


def test_an_absent_configuration_is_not_remembered_as_permanent(monkeypatch):
    """Session behaviour only: no hot reload is built. The lazy composition
    simply asks again on a later run, so configuring the process and rerunning
    -- which is how a restart looks to a session -- takes effect."""
    import src.application

    answers: list = [None, None]
    calls: list[int] = []

    def factory(*args, **kwargs):
        calls.append(1)
        return answers.pop(0) if answers else FakeReasoningService()

    monkeypatch.setattr(src.application, "build_reasoning_service", factory)
    app = refreshed(start(seed_service=False))
    assert app.session_state["reasoning_service"] is None
    assert explain_button(app).disabled
    app.run()
    assert app.session_state["reasoning_service"] is None
    app.run()
    assert isinstance(app.session_state["reasoning_service"], FakeReasoningService)
    assert not explain_button(app).disabled


def test_the_real_composition_from_the_dashboard_holds_no_separate_secret(monkeypatch):
    """The genuine ``build_reasoning_service`` runs, with the vendor constructor
    replaced, so the composed service is real and the client is a recorder.
    The button is never pressed, and a socket would fail if anything tried."""
    import socket

    import anthropic

    built: list[dict] = []

    class Recorded:
        def __init__(self, **kwargs):
            built.append(kwargs)

        def with_options(self, **kwargs):  # pragma: no cover - never reached
            raise AssertionError("no request may be made")

    def no_network(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the dashboard reached the network")

    monkeypatch.setattr(anthropic, "Anthropic", Recorded)
    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET_MARKER)
    monkeypatch.setenv("ANTHROPIC_MODEL", "model-y")

    app = refreshed(start(seed_service=False))
    assert built == [{"api_key": SECRET_MARKER}]
    service = app.session_state["reasoning_service"]
    assert isinstance(service, ReasoningService)
    assert not explain_button(app).disabled
    assert not any("AI explanation is unavailable" in i.value for i in app.info)
    text = rendered_text(app)
    assert SECRET_MARKER not in text
    assert "model-y" not in text
    for key in session_keys(app):
        for fragment in ("client", "api_key", "credential", "raw_response",
                         "request", "packet", "payload"):
            assert fragment not in key, key
    app.run()
    assert built == [{"api_key": SECRET_MARKER}], "composed once, not per rerun"


# -- 64, 72: what session state may hold ------------------------------------


def test_session_state_holds_the_service_the_snapshot_and_nothing_raw():
    app = press(refreshed(start()), BUTTON)
    state = app.session_state
    keys = session_keys(app)
    assert {"reasoning_service", "reasoning_snapshot", "reasoning_failure"} <= keys
    for key in keys:
        for fragment in ("client", "api_key", "credential", "raw_response",
                         "request", "packet", "payload", "exception"):
            assert fragment not in key, key
    assert isinstance(state["reasoning_snapshot"], ReasoningSnapshot)
    assert state["reasoning_failure"] is None
    for key in keys:
        value = state[key]
        name = type(value).__name__
        assert name not in {"ProviderReasoningResponse", "ReasoningRequest",
                            "EvidencePacket"}, key
        assert not isinstance(value, BaseException), key


def test_a_failure_in_session_state_is_the_view_not_the_exception():
    error = ReasoningProviderError(ReasoningFailureCode.RATE_LIMITED, SECRET_MARKER)
    app = press(refreshed(start(service=FakeReasoningService(failure=error))), BUTTON)
    failure = app.session_state["reasoning_failure"]
    assert isinstance(failure, ReasoningFailureView)
    assert not isinstance(failure, BaseException)
    assert SECRET_MARKER not in repr(failure)
    for key in session_keys(app):
        assert not isinstance(app.session_state[key], BaseException), key


# -- 68: the privacy disclosure ----------------------------------------------


def test_the_privacy_disclosure_sits_with_the_action_whenever_it_is_present():
    app = refreshed(start())
    captions = [c.value for c in app.caption]
    assert REASONING_PRIVACY_NOTE in captions
    low = REASONING_PRIVACY_NOTE.lower()
    assert "bounded view" in low and "research evidence" in low
    assert "symbol" in low and "interval" in low
    assert "sends" in low
    assert "external ai provider" in low
    assert "generated locally" in low and "deterministic" in low
    for not_sent in ("raw market history", "news", "external feeds",
                     "scanner results", "paper positions"):
        assert not_sent in low
    text = rendered_text(app).lower()
    for misleading in ("no data leaves", "nothing leaves your", "never leaves your",
                       "stays on your machine"):
        assert misleading not in text


def test_the_privacy_disclosure_is_shown_when_unconfigured_too(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    app = refreshed(start(seed_service=False))
    assert REASONING_PRIVACY_NOTE in [c.value for c in app.caption]


# -- 44, 45, 46: paper, scanner, news/feed boundaries -------------------------


def test_an_explanation_changes_nothing_about_paper_actions():
    app = press(refreshed(start()), BUTTON)
    assert is_rendered(app)
    session = app.session_state["paper"]
    assert session.portfolio.positions == ()
    assert app.session_state["paper_error"] is None
    keys = {b.key for b in app.button}
    assert "FormSubmitter:open_long_form-Open long (paper)" in keys
    # The paper symbol box is empty: nothing was prefilled from the explanation.
    assert app.text_input(key="open_symbol").value == ""


def test_the_explanation_is_scoped_to_one_research_snapshot():
    app = press(refreshed(start()), BUTTON)
    (asked,) = service_of(app).explain_calls
    assert asked is app.session_state["snapshot"]
    assert type(asked).__name__ == "ResearchSnapshot"
    assert app.session_state["reasoning_snapshot"].symbol == asked.symbol


def test_there_is_exactly_one_ai_control_and_it_is_on_research():
    app = refreshed(start())
    ai_keys = [b.key for b in app.button
               if any(f in b.key for f in ("explain", "ai", "reason"))]
    assert ai_keys == [BUTTON]


def test_the_ai_section_receives_no_news_feed_or_scanner_state():
    tree = ast.parse(APP_PATH.read_text())
    for name in ("explain_with_ai", "render_reasoning_section", "reasoning_service"):
        function = next(
            n for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef) and n.name == name
        )
        used = {n.attr for n in ast.walk(function) if isinstance(n, ast.Attribute)}
        used |= {n.id for n in ast.walk(function) if isinstance(n, ast.Name)}
        for forbidden in ("news_snapshot", "feed_snapshot", "scan_snapshot",
                          "news_service", "feed_service", "paper", "portfolio",
                          "open_long", "close_position", "scan_universes"):
            assert forbidden not in used, f"{name} touches {forbidden}"


# -- 40: loading UX, and no background work ------------------------------------


def test_the_single_call_is_wrapped_in_a_spinner_and_nothing_else():
    tree = ast.parse(APP_PATH.read_text())
    function = next(
        n for n in ast.walk(tree)
        if isinstance(n, ast.FunctionDef) and n.name == "explain_with_ai"
    )
    withs = [n for n in ast.walk(function) if isinstance(n, ast.With)]
    assert len(withs) == 1
    (block,) = withs
    context = block.items[0].context_expr
    assert isinstance(context, ast.Call) and context.func.attr == "spinner"
    calls = [n for n in ast.walk(block) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute) and n.func.attr == "explain"]
    assert len(calls) == 1
    source = APP_PATH.read_text()
    for forbidden in ("threading", "asyncio", "concurrent", "st.status(",
                      "run_in_executor", "st.fragment", "st_autorefresh"):
        assert forbidden not in source, forbidden


# -- the two pinning tests, and that they still bite ---------------------------

SMOKE = REPO / "tests" / "test_dashboard_smoke.py"
BOUNDARIES = REPO / "tests" / "test_dashboard_boundaries.py"
SCANNER_PINS = REPO / "tests" / "test_scanner_dashboard_boundaries.py"


def _set_literal_in(path: pathlib.Path, function: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == function)
    sets = [n for statement in ast.walk(node) if isinstance(statement, ast.Assert)
            for n in ast.walk(statement) if isinstance(n, ast.Set)]
    return {e.value for e in sets[0].elts
            if isinstance(e, ast.Constant) and isinstance(e.value, str)}


EXPECTED_BUTTONS = {
    "refresh_button", "refresh_news_button", "refresh_feeds_button",
    "reload_universes_button", "scan_market_button", BUTTON,
}
EXPECTED_SESSION = {
    "snapshot", "failure", "paper", "paper_error", "provider", "clock",
    "news_snapshot", "news_service", "news_failure",
    "feed_snapshot", "feed_service", "feed_failure",
    "scan_snapshot", "scan_failure", "scan_universes",
    "scan_universe_id", "pending_research_symbol",
    "reasoning_service", "reasoning_snapshot", "reasoning_failure",
}


def test_the_smoke_allowlist_admits_exactly_the_approved_controls():
    allowed = _set_literal_in(SMOKE, "test_the_research_panel_offers_no_paper_action_control")
    assert allowed == EXPECTED_BUTTONS
    assert "second_ai_button" not in allowed
    ai_related = {k for k in allowed if any(f in k for f in ("explain", "ai", "reason"))}
    assert ai_related == {BUTTON}


def test_the_smoke_allowlist_still_rejects_an_unapproved_button():
    """The approved set plus any other key must fail the ``<=`` the smoke test
    makes -- the guard has been extended by one name, not disabled."""
    allowed = _set_literal_in(SMOKE, "test_the_research_panel_offers_no_paper_action_control")
    assert not ({"another_ai_button"} | allowed) <= allowed
    assert not {"explain_scanner_button"} <= allowed


def test_the_scanner_button_pin_matches_the_smoke_allowlist_exactly():
    pinned = _set_literal_in(SCANNER_PINS, "test_the_legacy_button_allowlist_is_exactly_this")
    assert pinned == EXPECTED_BUTTONS
    smoke = _set_literal_in(SMOKE, "test_the_research_panel_offers_no_paper_action_control")
    assert pinned == smoke, "the pin and the allowlist it pins must agree"


def test_the_session_pin_matches_the_boundaries_allowlist_exactly():
    pinned = _set_literal_in(SCANNER_PINS, "test_the_legacy_session_allowlist_is_exactly_this")
    allowed = _set_literal_in(BOUNDARIES, "test_the_dashboard_holds_only_whole_snapshots_between_runs")
    assert pinned == allowed == EXPECTED_SESSION
    reasoning_keys = {k for k in pinned if "reasoning" in k}
    assert reasoning_keys == {"reasoning_service", "reasoning_snapshot", "reasoning_failure"}
    for fragment in ("client", "api_key", "credential", "raw_response",
                     "request", "packet", "exception", "payload"):
        assert not [k for k in pinned if fragment in k], fragment


def _pin_operator(path: pathlib.Path, function: str) -> type:
    """The comparison operator the pin's first set-literal assert uses."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    node = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == function)
    for statement in ast.walk(node):
        if isinstance(statement, ast.Assert) and isinstance(statement.test, ast.Compare):
            if any(isinstance(n, ast.Set) for n in ast.walk(statement.test)):
                (op,) = statement.test.ops
                return type(op)
    raise AssertionError(f"{function} has no set-literal comparison")


def test_the_pins_compare_for_equality_not_containment():
    """``==`` is what makes a pin a pin. ``>=`` or ``<=`` would let the
    allowlists grow unnoticed, which is the failure these tests exist for."""
    assert _pin_operator(SCANNER_PINS, "test_the_legacy_button_allowlist_is_exactly_this") is ast.Eq
    assert _pin_operator(SCANNER_PINS, "test_the_legacy_session_allowlist_is_exactly_this") is ast.Eq
    assert _pin_operator(SCANNER_PINS, "test_the_legacy_import_allowlist_is_exactly_this") is ast.Eq


def test_every_button_key_the_app_declares_is_approved():
    tree = ast.parse(APP_PATH.read_text())
    keys = {kw.value.value for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute) and node.func.attr == "button"
            for kw in node.keywords
            if kw.arg == "key" and isinstance(kw.value, ast.Constant)}
    # open_in_research_button only exists after a scan, so the smoke test's
    # render-time allowlist never sees it; it is Phase 10's and not AI-related.
    assert keys == EXPECTED_BUTTONS | {"open_in_research_button"}
    ai_related = {k for k in keys if any(f in k for f in ("explain", "ai", "reason"))}
    assert ai_related == {BUTTON}


def test_the_explain_control_is_not_a_paper_or_trading_control():
    for forbidden in ("buy", "sell", "open_long", "close_position", "trade", "order"):
        assert forbidden not in BUTTON
    app = refreshed(start())
    assert explain_button(app).label == "Explain with AI"
