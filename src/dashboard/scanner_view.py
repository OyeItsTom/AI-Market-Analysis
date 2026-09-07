"""Render the Market Overview panel.

**No controls at all.** Every widget on this tab -- the universe selector, Scan
Market, the result selector, Open in Research -- lives in ``app.py``. This module
receives one formatted view model and draws it. That is the same rule the news
and feeds panels follow, and it is what keeps orchestration out of the view.

**Nothing here interprets anything.** There is no score, no confidence, no
ranking rule and no summary this module wrote. Ordering arrives already decided
by the scanner; re-sorting here would be a second, disagreeing implementation of
the ranking rules.

**A research classification is not an instruction.** ``Bullish`` and ``Bearish``
are rendered as the classifications they are and never as Buy or Sell. The
panel's ordering note says plainly that position means how much there is to
inspect, not which security is better.

**A shortage of evidence is not a failure.** Symbols with no bars or too little
history appear in their own section, worded as what they are. The live benchmark
made this concrete: a symbol whose provider returned nothing must read "No data",
not "Provider error" -- the scan itself succeeded.
"""

from __future__ import annotations

import streamlit as st

from src.application.view_models import (
    SCANNER_EMPTY_HELP,
    SCANNER_INTERVAL_NOTE,
    ScannerView,
)


def render_scan_summary(view: ScannerView) -> None:
    """Headline counts for one completed scan."""
    summary = view.summary

    st.markdown(f"**{summary.universe_display_name}**")
    st.caption(
        f"Membership as of {summary.universe_as_of} · universe "
        f"{summary.fingerprint_prefix}… · daily bars · research policy "
        f"{summary.policy_fingerprint_prefix}…"
    )

    top = st.columns(4)
    top[0].metric("Symbols", summary.symbols_total)
    top[1].metric("Completed", summary.symbols_completed)
    top[2].metric("Assessable", summary.symbols_eligible)
    top[3].metric("Scan status", summary.status)

    bottom = st.columns(4)
    bottom[0].metric("No data", summary.symbols_no_data)
    bottom[1].metric("Insufficient evidence", summary.symbols_insufficient_evidence)
    bottom[2].metric("Operational failures", summary.operational_failures)
    bottom[3].metric("Duration", f"{summary.duration_seconds:.1f}s")

    if summary.operational_failures == summary.symbols_completed:
        st.error(view.status_note)
    elif summary.operational_failures:
        st.warning(view.status_note)
    else:
        st.caption(view.status_note)

    # Deliberately a window, not a single "market data as of". A scan spanning
    # minutes never observed one simultaneous market state, and each row carries
    # its own data cutoff instead.
    st.caption(
        f"Scan ran from {summary.scan_started_at} to {summary.scan_completed_at}. "
        "Each row shows the moment its own data was observed."
    )


def render_candidate_table(view: ScannerView) -> None:
    """The assessable rows, in the order the scanner decided."""
    st.markdown("**Research candidates**")
    if not view.has_rows:
        st.info("No symbol in this universe produced an assessment in this scan.")
        return

    st.caption(view.ordering_note)
    st.dataframe(
        [
            {
                "Symbol": row.symbol,
                "Evidence structure": row.category_label,
                "Assessment": row.assessment,
                "Bullish": row.bullish,
                "Bearish": row.bearish,
                "Neutral": row.neutral,
                "Why it surfaced": row.why_surfaced,
                "Latest bar": row.latest_bar,
                "Data cutoff": row.data_cutoff,
            }
            for row in view.rows
        ],
        width="stretch",
        hide_index=True,
    )


def render_issue_table(view: ScannerView) -> None:
    """Symbols with nothing to assess, and symbols that failed operationally.

    One table, but the status column keeps the two apart. Calling a symbol the
    provider had no bars for a "failure" would misreport a scan that worked.
    """
    if not view.issues:
        return

    st.markdown("**Not assessable this scan**")
    failures = sum(1 for issue in view.issues if issue.is_operational_failure)
    quiet = len(view.issues) - failures
    st.caption(
        f"{quiet} symbol(s) had nothing to assess and {failures} could not be "
        "scanned. Only the second group is an operational failure."
    )
    st.dataframe(
        [
            {
                "Symbol": issue.symbol,
                "Status": issue.status,
                "Operational failure": "yes" if issue.is_operational_failure else "no",
                "Detail": issue.detail,
                "Latest bar": issue.latest_bar,
                "Data cutoff": issue.data_cutoff,
            }
            for issue in view.issues
        ],
        width="stretch",
        hide_index=True,
    )


def render_empty_state() -> None:
    """Shown before any scan has completed. Never a blank tab."""
    st.info(SCANNER_EMPTY_HELP)
    st.markdown(
        "1. Choose a configured universe.\n"
        "2. Press **Scan Market**.\n"
        "3. Open a result in Research for the full single-symbol view."
    )
    st.caption(SCANNER_INTERVAL_NOTE)


def render_market_overview(view: ScannerView | None) -> None:
    """The Market Overview panel. Ordering and wording come from the view model."""
    st.subheader("Market Overview")

    if view is None:
        render_empty_state()
        return

    st.info(view.disclaimer)
    render_scan_summary(view)
    st.divider()
    render_candidate_table(view)
    st.divider()
    render_issue_table(view)


__all__ = [
    "render_market_overview",
    "render_scan_summary",
    "render_candidate_table",
    "render_issue_table",
    "render_empty_state",
]
