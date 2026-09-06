"""Render the external feeds panel.

**No action controls, and no research state.** This panel shows what feeds
published; it has no button that opens a position and is never handed an
assessment. It is a fourth separate panel for the same reason the others are
separate: reading information and acting on it are different decisions.

**Nothing here interprets anything.** There is no sentiment, no score, no
ranking, no summary this system wrote. Every string rendered came from a
publisher or from a formatting view model.

**Trust is quoted, never asserted.** A feed reads "Official feed (configured by
you)" because a line in a local JSON file says so. The panel keeps saying
"configured" and "unverified" precisely where a UI would normally start
sounding authoritative, because the difference between "the SEC said this" and
"a feed I labelled SEC said this" is the whole safety story of this phase.

**Links are rendered, never followed.** A feed URL is fetched only because it
is in configuration. Nothing linked *from inside* an entry is ever requested by
this application; the entry's link is displayed for the human to click.
"""

from __future__ import annotations

import streamlit as st

from src.application.view_models import (
    LABEL_RETRIEVED,
    TOOLTIP_FEED_TRUST,
    TOOLTIP_FEED_UPDATED,
    FeedsView,
)


def render_feed_sources(view: FeedsView) -> None:
    """Per-feed outcomes, so a partial refresh cannot read as a full one."""
    st.markdown("**Feeds**")
    if view.all_failed:
        st.error(view.status_note)
    elif view.is_partial:
        st.warning(view.status_note)
    else:
        st.caption(view.status_note)

    if not view.sources:
        return

    st.dataframe(
        [
            {
                "Feed": row.source_name,
                "Declared as": row.trust_label,
                "Host": row.url_host,
                "Outcome": row.outcome,
                "Detail": row.detail,
                "Counters": row.counters,
            }
            for row in view.sources
        ],
        width="stretch",
        hide_index=True,
    )


def render_feeds(view: FeedsView | None) -> None:
    """The external feeds panel. Configured RSS and Atom feeds, in time order."""
    st.subheader("External feeds")

    if view is None:
        st.info(
            "Press Refresh feeds to fetch the feeds in your configuration file. "
            "Nothing is fetched until you do."
        )
        return

    st.info(view.disclaimer)

    if not view.is_configured:
        # Not an error: a fresh checkout has no feeds, and that is correct.
        st.info(view.unconfigured_message)
        return

    st.warning(view.trust_disclaimer)

    columns = st.columns(2)
    columns[0].metric("Entries stored", view.item_count)
    columns[1].metric("Feeds configured", len(view.sources))
    st.caption(f"Snapshot built: {view.built_at}")

    if view.integrity_warning:
        # Stored entries could not be read. Said plainly, and nothing was
        # repaired or discarded to make the panel look tidy.
        st.error(view.integrity_warning)

    render_feed_sources(view)
    st.divider()

    if not view.rows:
        st.info("No entries stored yet.")
        return

    st.caption(
        "Newest first. All feeds share one timeline — how you labelled a feed "
        "does not move its entries up the list."
    )

    for row in view.rows:
        with st.container(border=True):
            head = st.columns([5, 2])
            # st.markdown escapes the text it is given, so a title containing
            # markup shows as the literal characters the publisher wrote.
            head[0].markdown(f"**{row.title}**")
            head[1].caption(row.trust_label)

            if row.excerpt:
                st.caption(row.excerpt)

            st.caption(f"{row.publisher} · via {row.source_name}")
            st.caption(row.association)

            if row.is_revision:
                # A changed entry is announced rather than quietly swapped in.
                st.caption(row.revision_note)

            stamps = st.columns(2)
            stamps[0].caption(f"{row.source_time_label}: {row.source_time}")
            stamps[1].caption(f"{LABEL_RETRIEVED}: {row.retrieved_at}")
            if row.availability_basis == "source_updated":
                st.caption(TOOLTIP_FEED_UPDATED)

            if row.url and row.is_safe_url:
                # Rendered as a link, never fetched by this application.
                st.markdown(f"[Open at source]({row.url})")
            elif row.url:
                # Defence in depth: a link that failed display validation is
                # shown as text so it cannot become a click target.
                st.caption(f"Link not shown as a link: {row.url}")

    st.caption(TOOLTIP_FEED_TRUST)


__all__ = ["render_feeds", "render_feed_sources"]
