"""Local research dashboard — Streamlit entrypoint.

Run it, on this machine only::

    streamlit run src/dashboard/app.py --server.address=127.0.0.1

This module is layout and dispatch. It owns no research rule, no risk rule and
no formatting: it reads widgets, calls one application-layer function, stores
the result, and hands view models to the two render modules.

Four behaviours here are load-bearing rather than incidental.

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

**An AI explanation is asked for, never assumed.** Phase 11A adds one explicit
control, ``Explain with AI``, and the single call that asks a provider lives in
its branch and nowhere else: not at load, not on a rerun, not when a symbol or
interval changes, not when research is refreshed. What the provider returns is
kept only once the reasoning domain has validated it, and it is discarded the
moment the research it explained is replaced. When no provider is configured
the control is disabled and everything else on this dashboard is unchanged.
"""

from __future__ import annotations

import time
import traceback

import streamlit as st

from src.application import (
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    SUPPORTED_INTERVALS,
    ApplicationError,
    FailureKind,
    FailureReport,
    PaperSession,
    ReasoningAvailability,
    ReasoningService,
    ReasoningUnavailable,
    build_provenance,
    build_reasoning_service,
    build_snapshot,
    default_provider,
    describe_reasoning_configuration,
    display_names,
)
# The two failure classes the explanation action has to tell apart. Stage E
# re-exports them for exactly this purpose; the reasoning domain itself is not
# imported here, and the boundary suite checks that it never is.
from src.application.reasoning import ReasoningProviderError, ReasoningValidationError
from src.application.feeds import FeedService, build_service as build_feed_service
from src.application.scanner import (
    MarketScanner,
    ScanProgress,
    load_universes as load_universe_configuration,
)
from src.application.news import NewsService, SymbolNotSupported, build_service
from src.application.view_models import (
    REASONING_HEADING,
    REASONING_NO_ASSESSMENT,
    REASONING_PRIVACY_NOTE,
    RESEARCH_DISCLAIMER,
    SCANNER_INTERVAL_NOTE,
    explanation_is_current,
    reasoning_explanation_view,
    reasoning_failure_view,
    feeds_view,
    scanner_view,
    universe_option_label,
    news_view,
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
from src.dashboard.feeds_view import render_feeds
from src.dashboard.scanner_view import render_market_overview
from src.dashboard.news_view import render_news
from src.dashboard.reasoning_view import render_reasoning, render_reasoning_failure
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
    if "news_service" not in state:
        # Injectable, like the provider: a test seeds a service whose sources
        # are fakes, so the news panel is exercised without a network.
        state.news_service = None
    if "news_snapshot" not in state:
        state.news_snapshot = None
    if "news_failure" not in state:
        state.news_failure = None
    if "feed_service" not in state:
        # Injectable, like the provider and the news service: a test seeds a
        # service whose fetch is a fake, so the feeds panel is exercised
        # without a network.
        state.feed_service = None
    if "feed_snapshot" not in state:
        state.feed_snapshot = None
    if "feed_failure" not in state:
        state.feed_failure = None
    if "scan_snapshot" not in state:
        # One whole MarketScanSnapshot, replaced only when a scan completes.
        state.scan_snapshot = None
    if "scan_failure" not in state:
        # A *global* scan failure only. Per-symbol errors live inside the
        # snapshot and never set this.
        state.scan_failure = None
    if "scan_universes" not in state:
        # The whole UniverseConfiguration, including its load report. Loaded
        # lazily the first time Market Overview needs it.
        state.scan_universes = None
    if "scan_universe_id" not in state:
        state.scan_universe_id = None
    if "pending_research_symbol" not in state:
        # The safe handoff key. Never a widget key: assigning symbol_input
        # after its widget exists raises StreamlitWidgetAlreadyInstantiatedError.
        state.pending_research_symbol = None
    if "reasoning_service" not in state:
        # The composed ReasoningService, or None. Injectable like the provider:
        # a test seeds a fake so the explanation path runs without a network.
        # Composed lazily the first time the Research tab needs it, never here.
        state.reasoning_service = None
    if "reasoning_snapshot" not in state:
        # One whole trusted ReasoningSnapshot, or None. Never a raw provider
        # response, a request, a packet or anything the validator refused.
        state.reasoning_snapshot = None
    if "reasoning_failure" not in state:
        # One whole ReasoningFailureView, or None. Never the exception.
        state.reasoning_failure = None


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
    # An explanation describes the research it was built from, and that
    # research has just been replaced. Both outcomes go; the service stays.
    state.reasoning_snapshot = None
    state.reasoning_failure = None


def refresh_news(symbol: str) -> None:
    """Fetch every configured news source. All or nothing at snapshot level.

    Per-source failure is *not* a global failure: the snapshot reports PARTIAL
    and keeps whatever did arrive. Only an inability to build a coherent
    snapshot at all leaves the previous one in place.
    """
    state = st.session_state
    if not symbol or not symbol.strip():
        state.news_failure = "Enter a symbol before refreshing news."
        return

    service: NewsService | None = state.news_service
    if service is None:
        # Built on the first explicit refresh, never at start-up: constructing
        # it may load the SEC ticker map, and nothing should reach the network
        # because the app was opened.
        try:
            service = build_service()
            state.news_service = service
        except Exception as exc:
            traceback.print_exc()
            state.news_failure = f"Could not start the news service: {type(exc).__name__}"
            return

    try:
        built = service.refresh(symbol)
    except SymbolNotSupported as exc:
        state.news_failure = str(exc)
        return
    except Exception as exc:
        traceback.print_exc()
        state.news_failure = f"News refresh failed: {type(exc).__name__}"
        return

    state.news_snapshot = built
    state.news_failure = None


def load_universes(force: bool = False) -> str | None:
    """Load the scan universes, returning an error message rather than raising.

    Called lazily so opening the app reads no file, and on demand from Reload.
    A failed reload deliberately leaves the last-good configuration in place: a
    typo in a local file must not destroy a working selector. The error is
    returned for this render only -- it is not stored, because a stale
    configuration error would outlive the problem it described.
    """
    state = st.session_state
    if state.scan_universes is not None and not force:
        return None
    try:
        loaded = load_universe_configuration()
    except Exception as exc:
        traceback.print_exc()
        return f"Could not read the universe configuration: {exc}"
    state.scan_universes = loaded
    return None


def selected_universe():
    """The chosen universe, falling back deterministically after a reload."""
    state = st.session_state
    configuration = state.scan_universes
    if configuration is None:
        return None
    enabled = configuration.enabled
    if not enabled:
        state.scan_universe_id = None
        return None
    chosen = configuration.get(state.scan_universe_id) if state.scan_universe_id else None
    if chosen is None or not chosen.enabled:
        # The stored id vanished or was switched off in a reload. Fall back to
        # the first enabled universe rather than leaving a dangling selection.
        chosen = enabled[0]
        state.scan_universe_id = chosen.universe_id
    return chosen


def scan_market(universe) -> None:
    """Run one manual serial scan and publish it only if it completes.

    The previous snapshot is left untouched until a new coherent one exists, so
    a failed scan never costs the user the results they were reading.
    """
    state = st.session_state
    progress = st.progress(0.0, text=f"Scanning 0 of {universe.symbol_count}…")
    status = st.empty()
    started = time.perf_counter()

    def report(event: ScanProgress) -> None:
        # Transient only: nothing about progress is stored in session state.
        progress.progress(
            event.completed / max(1, event.total),
            text=f"Scanning {event.completed} of {event.total} — {event.symbol}",
        )
        status.caption(
            f"{event.completed}/{event.total} · {time.perf_counter() - started:.1f}s "
            f"elapsed · {event.failures} could not be scanned"
        )

    try:
        built = MarketScanner(state.provider).scan(universe, progress=report)
    except Exception as exc:
        traceback.print_exc()
        state.scan_failure = f"Market scan failed: {type(exc).__name__}: {exc}"[:300]
        return
    finally:
        progress.empty()
        status.empty()

    # A PARTIAL or ALL_FAILED snapshot is a coherent result, not a global
    # failure: those states describe the symbols, not the scan.
    state.scan_snapshot = built
    state.scan_failure = None


def open_in_research(symbol: str) -> None:
    """Hand a scanned symbol to the Research control, fetching nothing.

    The value cannot be written to ``symbol_input`` here: that widget was built
    earlier in this run and Streamlit refuses a later assignment. It is parked
    on a non-widget key and applied at the top of the next run, before the
    widget exists.
    """
    st.session_state.pending_research_symbol = symbol
    st.rerun()


def apply_pending_research_symbol() -> None:
    """Apply a parked symbol *before* ``render_controls`` builds the widget.

    This ordering is load-bearing. Assigning ``symbol_input`` after the widget
    is instantiated raises ``StreamlitWidgetAlreadyInstantiatedError``.
    """
    state = st.session_state
    pending = state.pending_research_symbol
    if pending:
        state["symbol_input"] = pending
        state.pending_research_symbol = None


def render_market_panel() -> None:
    """Market Overview: universe controls, the scan action, and the results.

    Every widget lives here; ``scanner_view`` only draws. Nothing on this panel
    opens or closes a paper position -- selecting a result and opening it in
    Research is the only action available.
    """
    state = st.session_state
    st.caption(SCANNER_INTERVAL_NOTE)

    reload_error = load_universes()
    if st.button("Reload universes", key="reload_universes_button"):
        reload_error = load_universes(force=True)
    if reload_error:
        # Shown for this render only; the last-good configuration is retained.
        st.error(reload_error)

    configuration = state.scan_universes
    enabled = configuration.enabled if configuration is not None else ()

    if not enabled:
        st.info(
            "No scan universes are configured. Copy "
            "config/universes.example.json to config/universes.local.json and "
            "edit your research universe."
        )
    else:
        labels = {universe_option_label(u): u.universe_id for u in enabled}
        current = selected_universe()
        options = list(labels)
        index = next(
            (i for i, label in enumerate(options) if labels[label] == current.universe_id),
            0,
        )
        chosen_label = st.selectbox(
            "Universe", options, index=index, key="universe_select",
            help="Only enabled universes from your local configuration are listed.",
        )
        state.scan_universe_id = labels[chosen_label]

    universe = selected_universe()
    if st.button("Scan Market", key="scan_market_button", type="primary",
                 disabled=universe is None):
        if universe is not None:
            scan_market(universe)

    if state.scan_failure:
        st.error(state.scan_failure)

    snapshot = state.scan_snapshot
    view = scanner_view(snapshot) if snapshot is not None else None
    render_market_overview(view)

    if snapshot is not None and universe is not None:
        if snapshot.universe_id != universe.universe_id:
            st.warning(
                f"Showing results for {snapshot.universe_display_name}. Press "
                f"Scan Market to scan {universe.display_name}."
            )
        elif snapshot.universe_fingerprint != universe.fingerprint:
            st.warning(
                "The configuration for this universe has changed since this scan."
            )

    if view is not None and view.has_rows:
        symbols = list(view.eligible_symbols)
        # A selection that survived the new scan is kept; a stale one is reset.
        previous = state.get("scan_symbol_select")
        index = symbols.index(previous) if previous in symbols else 0
        chosen = st.selectbox(
            "Open a research candidate", symbols, index=index,
            key="scan_symbol_select",
            help="Assessable results only. Symbols with no data are not listed.",
        )
        if st.button("Open selected in Research", key="open_in_research_button"):
            open_in_research(chosen)
        if state.get("symbol_input"):
            st.caption(
                f"Research symbol set to {state['symbol_input']}. Open the "
                "Research tab and press Refresh."
            )


def refresh_feeds() -> None:
    """Fetch every configured feed. Symbol-independent by design.

    Feeds are configured, not searched: a feed covers whatever its publisher
    puts in it, so this refresh takes no symbol and the panel is not scoped to
    the one in the sidebar. Per-feed failure is not a global failure -- the
    snapshot reports PARTIAL and keeps whatever did arrive.
    """
    state = st.session_state

    service: FeedService | None = state.feed_service
    if service is None:
        # Built on the first explicit refresh, never at start-up: nothing
        # should reach the network because the app was opened.
        try:
            service = build_feed_service()
            state.feed_service = service
        except Exception as exc:
            traceback.print_exc()
            state.feed_failure = (
                f"Could not start the feeds service: {type(exc).__name__}. "
                "Check config/external_feeds.local.json."
            )
            return

    try:
        built = service.refresh()
    except Exception as exc:
        traceback.print_exc()
        state.feed_failure = f"Feed refresh failed: {type(exc).__name__}"
        return

    state.feed_snapshot = built
    state.feed_failure = None


def render_feeds_panel() -> None:
    state = st.session_state
    if state.feed_failure:
        st.warning(state.feed_failure)
    snapshot = state.feed_snapshot
    render_feeds(None if snapshot is None else feeds_view(snapshot))


def render_news_panel() -> None:
    state = st.session_state
    if state.news_failure:
        st.warning(state.news_failure)
    snapshot = state.news_snapshot
    render_news(None if snapshot is None else news_view(snapshot))


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


def reasoning_service() -> ReasoningService | None:
    """The composed service, built the first time it is needed and then kept.

    Composition reads two environment variables and, when both are present,
    builds a client -- no request is made. ``None`` means the feature is not
    configured, and nothing is stored in that case, so a later run asks again
    rather than remembering an absence. That costs two variable reads and
    matches how the news and feed services are started on demand.

    This is dependency retention, not a cache: what is kept is the thing that
    asks, never anything it answered.
    """
    state = st.session_state
    if state.reasoning_service is None:
        service = build_reasoning_service()
        if service is not None:
            state.reasoning_service = service
    return state.reasoning_service


def explain_with_ai(service: ReasoningService, snapshot) -> None:
    """The one place a provider is asked. Entered only from the button branch.

    Both previous outcomes are cleared first, so exactly one of them is set on
    the way out and a stale explanation can never sit beside a fresh failure.
    Every failure the application layer defines is turned into words by the
    view-model mapper and the exception itself is dropped; anything else is a
    programming error and propagates as one.
    """
    state = st.session_state
    state.reasoning_snapshot = None
    state.reasoning_failure = None
    try:
        with st.spinner("Asking the AI provider to explain this research…"):
            explained = service.explain(snapshot)
    except (ReasoningProviderError, ReasoningValidationError, ReasoningUnavailable) as exc:
        state.reasoning_failure = reasoning_failure_view(exc)
        return
    state.reasoning_snapshot = explained


def render_reasoning_section(snapshot) -> None:
    """The AI explanation of one research snapshot: disclosure, action, result.

    Eligibility is the service's answer and nobody else's. The button is
    enabled by ``availability`` and the branch checks it again, exactly as the
    scan control does with its universe; nothing here reads the assessment to
    decide.
    """
    state = st.session_state
    st.subheader(REASONING_HEADING)
    st.caption(REASONING_PRIVACY_NOTE)

    service = reasoning_service()
    if service is None:
        st.info(describe_reasoning_configuration())
        st.button(
            "Explain with AI", key="explain_with_ai_button", disabled=True,
            help="Configure an AI provider to enable this. Nothing else needs it.",
        )
        return

    eligible = service.availability(snapshot) is ReasoningAvailability.AVAILABLE
    if not eligible:
        st.info(REASONING_NO_ASSESSMENT)
    if st.button(
        "Explain with AI", key="explain_with_ai_button", disabled=not eligible,
        help="Sends the evidence described above to the configured AI provider.",
    ):
        if eligible:
            explain_with_ai(service, snapshot)

    failure = state.reasoning_failure
    if failure is not None:
        render_reasoning_failure(failure)

    retained = state.reasoning_snapshot
    if retained is not None and explanation_is_current(retained, snapshot):
        render_reasoning(reasoning_explanation_view(retained))


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

    if st.sidebar.button("Refresh news", key="refresh_news_button"):
        refresh_news(symbol)
    st.sidebar.caption(
        "News is fetched only when you press this. There is no scheduler and "
        "nothing runs in the background."
    )

    if st.sidebar.button("Refresh feeds", key="refresh_feeds_button"):
        refresh_feeds()
    st.sidebar.caption(
        "Only the feeds listed in your configuration file are fetched, and only "
        "when you press this. Feeds are not tied to the symbol above."
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
    # Last, and after a divider: the deterministic assessment stays primary,
    # and the explanation is of it.
    st.divider()
    render_reasoning_section(snapshot)


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

    # Before render_controls builds symbol_input: a handoff parked on the
    # previous run is applied here, or Streamlit refuses the assignment.
    apply_pending_research_symbol()

    render_controls()
    render_failure()

    market_tab, research_tab, news_tab, feeds_tab, paper_tab = st.tabs(
        ["Market Overview", "Research", "News", "External feeds", "Paper portfolio"]
    )
    with market_tab:
        render_market_panel()
    with research_tab:
        render_research()
    with news_tab:
        render_news_panel()
    with feeds_tab:
        render_feeds_panel()
    with paper_tab:
        render_paper()


# Streamlit executes this file as the ``__main__`` module (it installs the
# script under that name in ``sys.modules``), so the guard still runs the app
# under ``streamlit run`` and under ``AppTest``. What it stops is an ordinary
# ``import src.dashboard.app`` building a provider, writing session state and
# rendering every widget as a side effect of being imported.
if __name__ == "__main__":
    main()
