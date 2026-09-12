"""Render a grounded AI explanation, and render why there is not one.

Drawing only. Everything here arrives as a view model that the application
layer has already formatted: a trusted explanation that the reasoning domain
validated, or a failure that was classified before it got here. This module
calls no service, reads no configuration, touches no session state and imports
no reasoning type -- it cannot ask for an explanation, and it cannot show one
that was not trusted, because there is no type here through which either could
happen.

**No action control lives here.** The ``Explain with AI`` button, the
availability check and the single call that asks a provider all live in
``app.py`` with the other dispatch. A render module with a button would be a
render module that could act, and the research panel's rule -- information
here, actions elsewhere -- applies to an explanation of research as much as to
the research itself.

**A rejected answer is rendered as its rejection.** When validation refused a
response, what appears is the category of refusal and nothing the model wrote:
no partial claim, no salvaged summary. Showing "the parts that were fine" would
hand a reader exactly the text the validator decided they should not see.
"""

from __future__ import annotations

import streamlit as st

from src.application.view_models import (
    LABEL_SNAPSHOT_BUILT,
    ReasoningExplanationView,
    ReasoningFailureView,
)


def render_reasoning(view: ReasoningExplanationView) -> None:
    """A trusted explanation: summary, claims, uncertainties, diagnostics."""
    st.info(view.disclaimer)

    st.markdown(f"**{view.summary}**")
    st.caption(view.summary_citation)

    if view.claims:
        st.markdown("**What the evidence shows**")
        for claim in view.claims:
            with st.container(border=True):
                st.write(claim.text)
                st.caption(claim.citation)

    if view.uncertainties:
        st.markdown("**What the evidence does not establish**")
        for note in view.uncertainties:
            st.write(f"- {note}")

    st.caption(
        f"Explanation of {view.symbol} · {LABEL_SNAPSHOT_BUILT} (evidence cutoff): "
        f"{view.data_cutoff} · explanation generated: {view.generated_at}"
    )

    with st.expander("Diagnostics", expanded=False):
        st.caption(
            "About the call, not about what it said: no prompt, no evidence text "
            "and no credential appears here."
        )
        st.dataframe(
            [{"Field": label, "Value": value} for label, value in view.diagnostics],
            width="stretch",
            hide_index=True,
        )


def render_reasoning_failure(view: ReasoningFailureView) -> None:
    """Why there is nothing to show, in the words the application chose.

    Three treatments for three different facts. A provider that did not answer
    is an error; an answer that was refused is a warning, worded so the reader
    knows something came back and was declined; research with nothing to
    explain is ordinary information, exactly as the assessment panel treats it.
    """
    if view.is_validation_failure:
        st.warning(view.message)
    elif view.is_provider_failure:
        st.error(view.message)
    else:
        st.info(view.message)
    st.caption(view.guidance)


__all__ = ["render_reasoning", "render_reasoning_failure"]
