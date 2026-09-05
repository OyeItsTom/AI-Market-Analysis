"""Render the paper half of the dashboard.

Portfolio, the two manual action forms, and the risk decision.

**No research state is rendered here.** This module never receives an
``AssessmentView`` and has nothing to display one with, so the interface cannot
present "the research says bullish" as a reason to open a position. The two
panels are separate because the decision is: a human reads research on one and
decides here on the other.

**Nothing in this module mutates anything.** The forms *collect* what the human
typed and hand it back as a plain request; applying it is
:mod:`src.application.paper`'s job, called once from :mod:`src.dashboard.app`.
Rendering code that could apply an intent would be re-run on every Streamlit
rerun, which is exactly the duplicate-action bug the form/id/replay design
exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass

import streamlit as st

from src.application.view_models import (
    PROVENANCE_HELP,
    PROVENANCE_LABEL,
    DecisionView,
    PortfolioView,
    ProvenanceChoice,
)


@dataclass(frozen=True)
class OpenLongRequest:
    """What the human typed into the open form. Not an intent, and not applied."""

    symbol: str
    notional: str
    provenance: ProvenanceChoice | None


@dataclass(frozen=True)
class CloseRequest:
    """Which open position the human chose to close."""

    position_id: str


def render_portfolio(view: PortfolioView) -> None:
    """Show only what Phase 5 actually models.

    There is deliberately no quantity, price, cash, market value or P&L: Phase 5
    has no price semantics, so any of those would be a number this system never
    computed.
    """
    st.subheader("Paper portfolio")
    st.warning(view.session_warning)

    totals = st.columns(2)
    totals[0].metric("Total open notional", view.total_open_notional)
    totals[1].metric("Open positions", view.open_position_count)

    st.markdown("**Open positions**")
    if view.open_rows:
        st.dataframe(
            [
                {
                    "Position": row.position_id,
                    "Symbol": row.symbol,
                    "Notional": row.notional,
                    "Opened at": row.opened_at,
                }
                for row in view.open_rows
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No open paper positions.")

    st.markdown("**Closed positions**")
    if view.closed_rows:
        st.dataframe(
            [
                {
                    "Position": row.position_id,
                    "Symbol": row.symbol,
                    "Notional": row.notional,
                    "Opened at": row.opened_at,
                    "Closed at": row.closed_at,
                }
                for row in view.closed_rows
            ],
            width="stretch",
            hide_index=True,
        )
    else:
        st.caption("No closed paper positions.")

    with st.expander("Risk limits in force"):
        st.write(f"Maximum notional per position: {view.max_notional_per_position}")
        st.write(f"Maximum total open notional: {view.max_total_notional}")
        st.write(f"Maximum open positions: {view.max_open_positions}")
        st.write(
            "Duplicate symbol allowed: "
            + ("yes" if view.allow_duplicate_symbol else "no")
        )
        st.caption("These limits are fixed in Phase 7 and are not editable here.")


def render_open_form(
    position_id: str,
    intent_id: str,
    provenance_options: tuple[ProvenanceChoice, ...],
) -> OpenLongRequest | None:
    """Collect a manual OPEN_LONG. Returns the request only on submission.

    ``position_id`` and ``intent_id`` were minted before this form rendered and
    are stable across reruns, so they are shown rather than generated here.

    Nothing about the current research pre-fills any field. The notional
    default in particular is a fixed placeholder: deriving it from an
    assessment would be the automatic research-to-action path this project
    refuses to build.
    """
    st.markdown("**Open a paper position (manual)**")
    with st.form("open_long_form", clear_on_submit=False):
        symbol = st.text_input(
            "Symbol",
            value="",
            placeholder="e.g. AAPL",
            help="An example of the format, not a suggestion to trade it.",
            key="open_symbol",
        )
        notional = st.text_input(
            "Notional",
            value="",
            placeholder="e.g. 1000",
            help=(
                "The hypothetical size of the position. Phase 5 records exposure "
                "only — there is no price, no quantity and no cash."
            ),
            key="open_notional",
        )

        attach = False
        selected: ProvenanceChoice | None = None
        if provenance_options:
            attach = st.checkbox(PROVENANCE_LABEL, value=False, key="open_attach_prov")
            st.caption(PROVENANCE_HELP)
            if attach:
                labels = [option.label for option in provenance_options]
                chosen = st.selectbox(
                    "Which hypothesis were you reading?",
                    labels,
                    key="open_prov_choice",
                )
                selected = provenance_options[labels.index(chosen)]

        st.caption(f"Intent id {intent_id} · position id {position_id}")
        submitted = st.form_submit_button("Open long (paper)")

    if not submitted:
        return None
    return OpenLongRequest(
        symbol=symbol,
        notional=notional,
        provenance=selected if attach else None,
    )


def render_close_form(closable_ids: tuple[str, ...], intent_id: str) -> CloseRequest | None:
    """Collect a manual CLOSE. Only currently open positions are offered."""
    st.markdown("**Close a paper position (manual)**")
    if not closable_ids:
        st.caption("Nothing to close — there are no open paper positions.")
        return None

    with st.form("close_form", clear_on_submit=False):
        target = st.selectbox("Open position", closable_ids, key="close_target")
        st.caption(
            f"Intent id {intent_id}. Closing records the close time only — there "
            "is no close price and no profit or loss."
        )
        submitted = st.form_submit_button("Close position (paper)")

    if not submitted:
        return None
    return CloseRequest(position_id=target)


def render_decision(view: DecisionView | None, error: str | None = None) -> None:
    """Show the last risk decision, or the last structural refusal.

    A rejection is a normal policy outcome and is styled as information, not as
    a crash.
    """
    st.markdown("**Risk decision**")

    if error:
        # A structural refusal from Phase 5 (an unknown or already-closed
        # target, a replayed intent). Nothing was mutated.
        st.error(error)
        st.caption("The paper portfolio was not changed.")

    if view is None:
        if not error:
            st.caption("No paper action has been submitted yet.")
        return

    if view.approved:
        st.success(f"{view.outcome} — {view.note}")
    else:
        st.info(f"{view.outcome} — {view.note}")

    st.caption(f"Intent id: {view.intent_id}")
    st.caption(f"Risk policy: {view.policy_fingerprint}")
    if view.reasons:
        st.write("Reasons: " + ", ".join(view.reasons))


__all__ = [
    "OpenLongRequest",
    "CloseRequest",
    "render_portfolio",
    "render_open_form",
    "render_close_form",
    "render_decision",
]
