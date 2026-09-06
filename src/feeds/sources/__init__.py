"""Feed format adapters.

One adapter module covers both dialects because RSS and Atom differ only in
element names and timestamp formats once the document is safely parsed. What
they do *not* share is timing semantics, and that difference is expressed
inside :mod:`src.feeds.sources.rss` rather than smoothed over.
"""

from .rss import NormalizedEntry, normalize_feed

__all__ = ["NormalizedEntry", "normalize_feed"]
