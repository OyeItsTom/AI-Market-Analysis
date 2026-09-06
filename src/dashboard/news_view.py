"""Render the news panel.

**No action controls, and no research state.** This panel shows what sources
published; it has no button that opens a position and is never handed an
assessment. It is the third separate panel for the same reason the first two
are separate: reading information and acting on it are different decisions, and
the interface should not blur them by putting them side by side.

**Nothing here interprets anything.** There is no sentiment, no score, no
"positive for the stock", no summary this system wrote. Every string rendered
came from a source or from a formatting view model.
"""

from __future__ import annotations

import streamlit as st

from src.application.view_models import (
    LABEL_RETRIEVED,
    TOOLTIP_RETRIEVED,
    TOOLTIP_SOURCE_EVENT,
    NewsView,
)


def render_sources(view: NewsView) -> None:
    """Per-source outcomes, so a partial refresh cannot read as a full one."""
    st.markdown("**Sources**")
    if view.all_failed:
        st.error(view.status_note)
    elif view.is_partial:
        st.warning(view.status_note)
    else:
        st.caption(view.status_note)

    st.dataframe(
        [
            {
                "Source": row.source,
                "Outcome": row.outcome,
                "Detail": row.detail,
                "Counters": row.counters,
            }
            for row in view.sources
        ],
        width="stretch",
        hide_index=True,
    )


def render_news(view: NewsView | None) -> None:
    """The news panel. Official filings and reported news, in time order."""
    st.subheader("News and company announcements")

    if view is None:
        st.info(
            "Enter a symbol in the sidebar and press Refresh news. Nothing is "
            "fetched until you do."
        )
        return

    st.info(view.disclaimer)

    columns = st.columns(3)
    columns[0].metric("Symbol", view.symbol)
    columns[1].metric("Official filings", view.official_count)
    columns[2].metric("News reports", view.secondary_count)
    st.caption(f"Snapshot built: {view.built_at}")

    if view.integrity_warning:
        # Stored records could not be read. Said plainly, and nothing was
        # repaired or discarded to make the panel look tidy.
        st.error(view.integrity_warning)

    render_sources(view)

    if view.cik_map_note:
        st.caption(view.cik_map_note)

    st.divider()

    if not view.rows:
        st.info("No records for this symbol yet.")
        return

    st.caption(
        "Newest first. Official filings and news reports are shown in one "
        "timeline — being official does not move a record up the list."
    )

    for row in view.rows:
        with st.container(border=True):
            head = st.columns([5, 2])
            head[0].markdown(f"**{row.headline}**")
            head[1].markdown(
                f"**{row.source_class}**" if row.is_official else row.source_class
            )

            if row.form:
                detail = f"Form {row.form}"
                if row.items:
                    detail += f" · items {row.items}"
                st.caption(detail)
            if row.summary:
                st.caption(row.summary)

            st.caption(f"{row.publisher} · via {row.source}")
            # The association wording is the honest one: for Yahoo this says
            # "returned for AAPL", because the payload names no ticker.
            st.caption(row.association)

            stamps = st.columns(2)
            stamps[0].caption(f"{row.source_time_label}: {row.source_time}")
            stamps[1].caption(f"{LABEL_RETRIEVED}: {row.retrieved_at}")
            st.caption(
                TOOLTIP_SOURCE_EVENT if row.is_official else TOOLTIP_RETRIEVED
            )

            if row.url:
                # Rendered as a link, never fetched by this application.
                st.markdown(f"[Open at source]({row.url})")


__all__ = ["render_news", "render_sources"]
