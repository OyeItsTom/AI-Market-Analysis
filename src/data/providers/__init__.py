"""Concrete market-data provider adapters.

Each adapter implements :class:`~src.data.provider.MarketDataProvider` and is
the *only* place that knows about its vendor's schema.

* :class:`~src.data.providers.yahoo.YahooFinanceProvider` -- development /
  fallback source, backed by yfinance.
* :class:`~src.data.providers.alpaca.AlpacaProvider` -- architectural stub for
  Phase 2; raises ``NotImplementedError`` on use.
"""

from .alpaca import AlpacaProvider
from .yahoo import YahooFinanceProvider

__all__ = ["YahooFinanceProvider", "AlpacaProvider"]
