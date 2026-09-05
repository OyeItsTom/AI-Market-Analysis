"""Local Streamlit dashboard — research display and manual paper actions.

Run it with::

    streamlit run src/dashboard/app.py --server.address=127.0.0.1

This package renders; it computes nothing. It imports :mod:`src.application`
and never a domain module directly, so no research or risk rule can be
reimplemented here by accident.

Two panels, deliberately separate. The research panel has no action controls,
and the paper panel shows no assessment state: nothing in the interface turns
"the research says bullish" into a paper position. A human reads one and
decides the other.
"""
