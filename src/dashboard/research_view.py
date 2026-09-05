"""Render the research half of the dashboard.

Market, features, individual observations, and the combined assessment.

**This module contains no action controls.** There is no button here that
creates a paper position, and there is nothing to click that would. That is not
an oversight to be tidied up later -- it is the interface expression of the
project's central rule: research is information, and acting on it is a separate
human decision made on a separate panel.

Everything rendered arrives as a pre-formatted view model. Nothing here reads a
domain object or recomputes a state.
"""

from __future__ import annotations

import streamlit as st

from src.application.view_models import (
    LABEL_ASSESSMENT_AS_OF,
    LABEL_BAR_OPENED,
    LABEL_EVALUABLE_FROM,
    LABEL_SNAPSHOT_BUILT,
    TOOLTIP_ASSESSMENT_AS_OF,
    TOOLTIP_BAR_OPENED,
    TOOLTIP_EVALUABLE_FROM,
    AssessmentView,
    FeatureRow,
    MarketView,
    ObservationView,
)


def render_market(view: MarketView, closes: list[float]) -> None:
    st.subheader("Market")
    st.caption(view.source_note)
    if view.pit_warning:
        st.warning(view.pit_warning)

    columns = st.columns(4)
    columns[0].metric("Symbol", view.symbol)
    columns[1].metric("Interval", view.interval)
    columns[2].metric("Price basis", view.basis)
    columns[3].metric("Settled bars", f"{view.bar_count:,}")

    st.caption(
        f"History requested: {view.history_label}. Only completed bars are used, "
        "so the bar currently forming is deliberately absent."
    )

    stamps = st.columns(2)
    stamps[0].metric(f"{LABEL_BAR_OPENED} (latest)", view.latest_bar_opened)
    stamps[0].caption(TOOLTIP_BAR_OPENED)
    stamps[1].metric(LABEL_SNAPSHOT_BUILT, view.snapshot_built)
    stamps[1].caption("When this dashboard assembled the snapshot.")

    if closes:
        # st.line_chart is built into Streamlit; Phase 7 adds no chart library.
        # The x-axis is bar order rather than a date scale, and is labelled as
        # such so it cannot be misread as a continuous calendar axis.
        st.line_chart(
            {"close": closes},
            x_label="Settled bars (oldest to newest)",
            y_label=f"Close ({view.basis})",
        )
    if view.rows:
        st.dataframe(
            [dict(zip(view.columns, row)) for row in view.rows],
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No data for this symbol and interval.")


def render_features(rows: tuple[FeatureRow, ...]) -> None:
    st.subheader("Features")
    if not rows:
        st.info("No features yet — there are no bars to compute them from.")
        return
    st.caption(
        "The indicators the hypotheses actually asked for. Shared requests are "
        "computed once."
    )
    st.dataframe(
        [
            {"Feature": r.name, "Latest value": r.value, "Specification": r.key}
            for r in rows
        ],
        width="stretch",
        hide_index=True,
    )
    if any(r.is_warming_up for r in rows):
        st.caption(
            "‘warming up’ means the indicator does not have enough bars yet. It is "
            "not zero and not missing data."
        )


def render_observations(views: tuple[ObservationView, ...]) -> None:
    st.subheader("Research observations")
    if not views:
        st.info("No observations — there are no bars to classify.")
        return
    st.caption("What each hypothesis classified at the most recent settled bar.")

    for view in views:
        with st.container(border=True):
            head = st.columns([3, 2])
            head[0].markdown(f"**{view.display_name}**")
            head[1].markdown(f"**{view.state}**")
            st.caption(view.label)
            if view.reasons:
                st.write("Reasons: " + ", ".join(view.reasons))
            if view.evidence:
                st.caption(
                    "Evidence: "
                    + ", ".join(f"{name} = {value}" for name, value in view.evidence)
                )
            st.caption(f"{LABEL_EVALUABLE_FROM}: {view.evaluable_from}")
            st.caption(TOOLTIP_EVALUABLE_FROM)


def render_assessment(view: AssessmentView | None) -> None:
    st.subheader("Research assessment")

    if view is None:
        st.info(
            "No assessment — there are no bars to assess. Enter a symbol and press "
            "Refresh."
        )
        return

    st.markdown(f"## {view.state}")
    st.info(view.disclaimer)

    if view.is_conflicted:
        st.warning(view.conflict_explanation)
        if view.bullish_names:
            st.write("Bullish: " + ", ".join(view.bullish_names))
        if view.bearish_names:
            st.write("Bearish: " + ", ".join(view.bearish_names))
    elif view.is_insufficient:
        # Deliberately st.info, not st.error: this is a normal research state.
        st.info(view.insufficient_explanation)
    elif view.short_history_note:
        # Enough hypotheses classified to reach a state, but the series is
        # still below the ensemble's warm-up floor. Say so rather than let the
        # headline imply the full ensemble spoke.
        st.caption(view.short_history_note)

    counts = st.columns(4)
    counts[0].metric("Bullish", view.bullish)
    counts[1].metric("Bearish", view.bearish)
    counts[2].metric("Neutral", view.neutral)
    counts[3].metric("Not enough history", view.insufficient)
    st.caption(
        f"{view.sufficient} of {view.total} hypotheses classified; this policy needs "
        f"at least {view.minimum_required}. These are counts of classifications, not "
        "a confidence or a probability — and the hypotheses are related, so agreement "
        "is not independent confirmation."
    )

    if view.reasons:
        st.write("Reasons: " + ", ".join(view.reasons))
    st.caption(f"{LABEL_ASSESSMENT_AS_OF}: {view.assessment_as_of}")
    st.caption(TOOLTIP_ASSESSMENT_AS_OF)
    st.caption(f"Assessment policy: {view.policy_fingerprint}")


__all__ = [
    "render_market",
    "render_features",
    "render_observations",
    "render_assessment",
]
