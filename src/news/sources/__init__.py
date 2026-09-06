"""Concrete external-information source adapters.

Each adapter is the only place that knows its source's payload shape, and each
takes an injected fetch callable so no test reaches the network -- the seam
Phase 1 established with ``download_fn``.

* :class:`~src.news.sources.edgar.EdgarFilingsSource` -- SEC filings, the
  official tier, with source-verified symbol association.
* :class:`~src.news.sources.yahoo.YahooNewsSource` -- aggregated reportage, the
  secondary tier, whose symbol association is only "returned for this query".
"""

from .edgar import EdgarFilingsSource
from .yahoo import YahooNewsSource

__all__ = ["EdgarFilingsSource", "YahooNewsSource"]
