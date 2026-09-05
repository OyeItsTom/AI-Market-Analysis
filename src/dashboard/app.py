"""Local research dashboard — Streamlit entrypoint.

Run it, on this machine only::

    streamlit run src/dashboard/app.py --server.address=127.0.0.1

This module is layout and dispatch. It owns no research rule, no risk rule and
no formatting: it reads widgets, calls one application-layer function, stores
the result, and hands view models to the two render modules.

Three behaviours here are load-bearing rather than incidental.

**Nothing fetches until a human asks.** The symbol starts empty and the provider
is called only inside the ``Refresh`` branch, so starting the dashboard, typing,
or changing any widget performs no network call. Streamlit re-runs this script
top to bottom on every interaction; a fetch written at module level would run on
every keystroke.

**A rerun re-renders, it never re-acts.** Both paper forms are ``st.form``, so
their submit branch is entered on the submitting run and not on the reruns that
follow. The identifiers a submission will use are minted *before* the form
renders and held across reruns, and they are passed explicitly into the
application layer, so a submission that somehow arrived twice would reach Phase
5 with the same ``intent_id`` and be refused as a replay rather than applied
again.

**A failed refresh changes nothing.** The new snapshot is built into a local
variable and only assigned into session state once the whole build succeeded, so
a provider outage leaves the previous complete snapshot on screen instead of a
half-updated one.
"""

from __future__ import annotations

import traceback

import streamlit as st

from src.application import (
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    SUPPORTED_INTERVALS,
    ApplicationError,
    FailureKind,
    FailureReport,
    PaperSession,
    build_provenance,
    build_snapshot,
    default_provider,
    display_names,
)
from src.application.view_models import (
    RESEARCH_DISCLAIMER,
    assessment_view,
    decision_view,
    feature_rows,
    market_view,
    observation_views,
    portfolio_view,
    provenance_choices,
)
from src.dashboard.paper_view import (
    render_close_form,
    render_decision,
    render_open_form,
    render_portfolio,
)
from src.dashboard.research_view import (
    render_assessment,
    render_features,
    render_market,
    render_observations,
)

SYMBOL_HELP = (
    "The placeholder is an example of the format, not a suggestion to research "
    "or trade that company. Nothing is fetched until you press Refresh."
)


def init_session() -> None:
    """Create session state once. Deliberately starts empty.

    No symbol, no snapshot, and therefore no company assessment on first
    launch: a dashboard that pre-loaded an example would be presenting research
    nobody asked for.
    """
    state = st.session_state
    if "snapshot" not in state:
        state.snapshot = None
    if "failure" not in state:
        state.failure = None
    if "paper" not in state:
        state.paper = PaperSession()
    if "paper_error" not in state:
        state.paper_error = None
    if "provider" not in state:
        # Injectable: a test seeds this before the script runs, so the smoke
        # tests exercise the real render path without touching a network.
        state.provider = default_provider()
    if "clock" not in state:
        state.clock = None


def refresh(symbol: str, interval) -> None:
    """Fetch, compute, assess, and publish — all or nothing.

    The single place the provider is called. The assignment to
    ``st.session_state.snapshot`` happens only after ``build_snapshot`` has
    returned a complete record, so there is no window in which the UI could
    render new bars beside an older assessment.
    """
    state = st.session_state
    clock = state.clock
    try:
        built = (
            build_snapshot(state.provider, symbol, interval)
            if clock is None
            else build_snapshot(state.provider, symbol, interval, now=clock)
        )
    except ApplicationError as exc:
        if exc.kind is FailureKind.UNEXPECTED:
            # Detail goes to the terminal; the UI gets one safe sentence.
            traceback.print_exc()
        state.failure = FailureReport(exc.kind, exc.step, exc.message)
        return
    except Exception as exc:  # pragma: no cover - build_snapshot classifies
        traceback.print_exc()
        state.failure = FailureReport(
            FailureKind.UNEXPECTED, "refresh", f"{type(exc).__name__}: {exc}"
        )
        return

    # Atomic publication: previous snapshot replaced only on full success.
    state.snapshot = built
    state.failure = None


def apply_open_long(request) -> None:
    """The one place an OPEN_LONG is applied. Never called while rendering."""
    state = st.session_state
    session: PaperSession = state.paper
    ids = session.pending_open_ids()
    provenance = None
    if request.provenance is not None:
        choice = request.provenance
        provenance = build_provenance(
            hypothesis_id=choice.hypothesis_id,
            hypothesis_version=choice.hypothesis_version,
            hypothesis_fingerprint=choice.hypothesis_fingerprint,
            observation_timestamp=choice.observation_timestamp,
        )
    try:
        session.open_long(
            request.symbol, request.notional, provenance=provenance, ids=ids
        )
        state.paper_error = None
    except ApplicationError as exc:
        # A structural refusal (replay, recycled id) or invalid input. The
        # portfolio was not mutated.
        state.paper_error = exc.message


def apply_close(request) -> None:
    """The one place a CLOSE is applied. Never called while rendering."""
    state = st.session_state
    session: PaperSession = state.paper
    intent_id = session.pending_close_intent_id()
    try:
        session.close_position(request.position_id, intent_id=intent_id)
        state.paper_error = None
    except ApplicationError as exc:
        state.paper_error = exc.message


def render_controls() -> None:
    """Symbol, interval and Refresh. The only way a fetch is ever started."""
    st.sidebar.header("Research controls")
    symbol = st.sidebar.text_input(
        "Symbol",
        value="",
        placeholder="e.g. AAPL",
        help=SYMBOL_HELP,
        key="symbol_input",
    )
    st.sidebar.caption(SYMBOL_HELP)

    interval = st.sidebar.selectbox(
        "Interval",
        SUPPORTED_INTERVALS,
        format_func=lambda value: value.value,
        key="interval_input",
    )
    st.sidebar.caption(
        "The amount of history is chosen automatically for the interval, so "
        "every hypothesis has enough bars to warm up. There is no start-date "
        "control."
    )

    if st.sidebar.button("Refresh", key="refresh_button", type="primary"):
        refresh(symbol, interval)

    st.sidebar.caption(
        "Refresh fetches settled bars only — the bar currently forming is never "
        "included, and there is no control to include it."
    )


def render_failure() -> None:
    """Explain a failed refresh without discarding what is already on screen."""
    failure: FailureReport | None = st.session_state.failure
    if failure is None:
        return

    snapshot = st.session_state.snapshot
    message = f"{failure.headline}: {failure.detail}"
    if snapshot is not None:
        built = market_view(snapshot).snapshot_built
        message += f" Showing the previous snapshot from {built}."
    st.error(message)
    st.caption(failure.guidance)
    if failure.is_bug:
        st.caption("Technical detail was written to the terminal, not shown here.")


def render_research() -> None:
    snapshot = st.session_state.snapshot
    if snapshot is None:
        st.info(
            "Enter a symbol in the sidebar and press Refresh. Nothing is fetched "
            "until you do."
        )
        st.caption(RESEARCH_DISCLAIMER)
        return

    names = display_names()
    closes = [bar.close for bar in snapshot.series.bars]

    render_market(market_view(snapshot), closes)
    st.divider()
    render_features(feature_rows(snapshot))
    st.divider()
    render_observations(observation_views(snapshot.observations, names))
    st.divider()
    render_assessment(
        None
        if snapshot.assessment is None
        else assessment_view(
            snapshot.assessment,
            snapshot.observations,
            MINIMUM_SUFFICIENT_OBSERVATIONS,
            names,
            bar_count=snapshot.bar_count,
            warmup_bars=snapshot.warmup_bars,
        )
    )


def render_paper() -> None:
    state = st.session_state
    session: PaperSession = state.paper
    snapshot = state.snapshot

    render_portfolio(portfolio_view(session.portfolio, session.policy))
    st.divider()

    # Minted before the form renders and held across reruns, so a resubmission
    # carries the same identifiers rather than freshly generated ones.
    ids = session.pending_open_ids()
    options = (
        provenance_choices(snapshot.observations, display_names())
        if snapshot is not None
        else ()
    )
    open_request = render_open_form(ids.position_id, ids.intent_id, options)

    st.divider()
    close_request = render_close_form(
        session.closable_ids, session.pending_close_intent_id()
    )

    st.divider()
    render_decision(
        None if session.last_decision is None else decision_view(session.last_decision),
        state.paper_error,
    )

    # Dispatch last: mutation happens after the panel has been described, in
    # exactly one call, and only on the run that carried a submission.
    if open_request is not None:
        apply_open_long(open_request)
        st.rerun()
    if close_request is not None:
        apply_close(close_request)
        st.rerun()


def main() -> None:
    st.set_page_config(page_title="Local research dashboard", layout="wide")
    init_session()

    st.title("Local research dashboard")
    st.caption(
        "Runs on this machine only. Research information and manual paper "
        "positions — no broker, no orders, no real money."
    )

    render_controls()
    render_failure()

    research_tab, paper_tab = st.tabs(["Research", "Paper portfolio"])
    with research_tab:
        render_research()
    with paper_tab:
        render_paper()


# Streamlit executes this file as the ``__main__`` module (it installs the
# script under that name in ``sys.modules``), so the guard still runs the app
# under ``streamlit run`` and under ``AppTest``. What it stops is an ordinary
# ``import src.dashboard.app`` building a provider, writing session state and
# rendering every widget as a side effect of being imported.
if __name__ == "__main__":
    main()
