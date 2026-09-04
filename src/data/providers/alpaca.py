"""Alpaca adapter -- ARCHITECTURAL STUB. Not implemented in Phase 1.

Why this file exists with no implementation
-------------------------------------------
The point of Phase 1 is that the rest of the system depends on
:class:`~src.data.provider.MarketDataProvider`, never on a vendor.  This stub
proves that a second provider slots in without touching anything downstream,
and records exactly what finishing it will require -- without adding an SDK
dependency or credentials to the repository today.

What a real implementation needs (Phase 2+)
-------------------------------------------
1. **Dependency**: ``alpaca-py`` (``pip install alpaca-py``), added to
   ``requirements.txt``.  Not installed yet -- deliberately.
2. **Credentials**: ``ALPACA_API_KEY_ID`` / ``ALPACA_API_SECRET_KEY`` read from
   the environment (see ``.env.example``).  Keys are never hard-coded, never
   logged, never printed, and ``.env`` stays git-ignored.
3. **Endpoint choice**: paper endpoints only for this project
   (``https://paper-api.alpaca.markets``, data at
   ``https://data.alpaca.markets``).  This system is educational and must not
   place real-money orders.
4. **Mapping work**:
   - interval -> ``TimeFrame`` (``1m`` -> ``TimeFrame.Minute``, ``1d`` ->
     ``TimeFrame.Day``, ...);
   - response fields ``t/o/h/l/c/v`` -> :class:`~src.data.models.MarketBar`
     (:data:`~src.data.normalization.DEFAULT_FIELD_ALIASES` already covers
     these short keys);
   - timestamps arrive as RFC-3339 UTC and stay UTC;
   - pagination via ``next_page_token``;
   - ``feed`` selection (``iex`` on the free tier vs. ``sip``) recorded in
     ``source`` so datasets from different feeds are never mixed silently.
5. **Error mapping**: HTTP/auth/rate-limit failures ->
   :class:`~src.data.provider.ProviderUnavailableError`; missing config ->
   :class:`~src.data.provider.ProviderConfigurationError`.
6. **Tests**: same offline pattern as the Yahoo adapter -- inject a fake
   fetch function returning canned payloads; no live API calls in CI.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Sequence

from ..models import Interval, MarketBar
from ..provider import MarketDataProvider, ProviderConfigurationError

#: Environment variables a future implementation will read.  Names only --
#: values are never stored in, or printed by, this codebase.
ALPACA_KEY_ENV = "ALPACA_API_KEY_ID"
ALPACA_SECRET_ENV = "ALPACA_API_SECRET_KEY"
ALPACA_PAPER_BASE_URL = "https://paper-api.alpaca.markets"


def credentials_present() -> bool:
    """Report whether Alpaca credentials exist in the environment.

    Returns a bool only.  It never returns, logs or prints the values.
    """
    return bool(os.environ.get(ALPACA_KEY_ENV)) and bool(os.environ.get(ALPACA_SECRET_ENV))


class AlpacaProvider(MarketDataProvider):
    """Placeholder for the future Alpaca market-data provider.

    Constructing it is allowed (so the class can be introspected and tested);
    every data request raises :class:`NotImplementedError`.  It is wired to
    Alpaca's **paper** environment by design -- this project never executes
    real-money trades.
    """

    name = "alpaca"
    supported_intervals = frozenset(
        {
            Interval.MINUTE_1,
            Interval.MINUTE_5,
            Interval.MINUTE_15,
            Interval.MINUTE_30,
            Interval.HOUR_1,
            Interval.DAY_1,
            Interval.WEEK_1,
            Interval.MONTH_1,
        }
    )

    #: Paper trading only. Do not point this at a live endpoint.
    base_url = ALPACA_PAPER_BASE_URL

    def _fetch_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: Interval,
    ) -> Sequence[MarketBar]:
        raise NotImplementedError(
            "AlpacaProvider is an architectural stub. Implementing it requires the "
            "alpaca-py SDK and paper-trading API credentials supplied via the "
            f"{ALPACA_KEY_ENV}/{ALPACA_SECRET_ENV} environment variables. "
            "Use YahooFinanceProvider for development. See this module's docstring."
        )

    def check_configuration(self) -> None:
        """Raise if the provider could not run even once implemented."""
        if not credentials_present():
            raise ProviderConfigurationError(
                f"Alpaca credentials not configured; set {ALPACA_KEY_ENV} and "
                f"{ALPACA_SECRET_ENV} in your environment (see .env.example)"
            )


__all__ = ["AlpacaProvider", "credentials_present", "ALPACA_KEY_ENV", "ALPACA_SECRET_ENV"]
