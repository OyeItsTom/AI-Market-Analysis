"""Yahoo Finance (yfinance) adapter.

Status: **development / fallback data source only.**

yfinance scrapes an undocumented public Yahoo endpoint.  It is convenient and
free, and it is good enough to develop and test the rest of the pipeline
against.  It is *not* a production market-data feed.  Known limitations are
documented in ``docs/market_data.md`` and summarised on
:class:`YahooFinanceProvider`.

The adapter deliberately takes an injectable ``download_fn`` so that every
test in this repository runs offline.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, tzinfo
from typing import Any, Callable, Sequence

from ..adjustment import AdjustmentData
from ..corporate_actions import ActionType, CorporateAction
from ..models import Interval, MarketBar
from ..normalization import bars_from_records, coerce_timestamp, is_missing
from ..provider import MarketDataProvider, ProviderConfigurationError, ProviderUnavailableError
from ..series import PriceBasis

#: Our interval vocabulary -> yfinance's.  Only intervals we have verified
#: are listed; anything else is rejected rather than passed through blindly.
_YF_INTERVALS: dict[Interval, str] = {
    Interval.MINUTE_1: "1m",
    Interval.MINUTE_5: "5m",
    Interval.MINUTE_15: "15m",
    Interval.MINUTE_30: "30m",
    Interval.HOUR_1: "1h",
    Interval.DAY_1: "1d",
    Interval.WEEK_1: "1wk",
    Interval.MONTH_1: "1mo",
}

DownloadFn = Callable[[str, datetime, datetime, str], Any]


def _default_download(symbol: str, start: datetime, end: datetime, yf_interval: str) -> Any:
    """Fetch a price history DataFrame from yfinance (imported lazily)."""
    try:
        import yfinance  # noqa: PLC0415 - optional/heavy dependency, imported on use
    except ImportError as exc:  # pragma: no cover - depends on environment
        raise ProviderConfigurationError(
            "yfinance is not installed; `pip install yfinance` or inject a download_fn"
        ) from exc

    try:
        # auto_adjust=False keeps Open/High/Low/Close as RAW traded prices --
        # the Phase 1 contract -- while additionally returning "Adj Close".
        # actions=True adds "Dividends" and "Stock Splits" to the SAME response,
        # so corporate-action capture costs no extra request. The extra columns
        # are consumed only by get_adjustment_data(); the raw bar path ignores
        # them, so MarketBar keeps exactly its Phase 1 meaning.
        return yfinance.Ticker(symbol).history(
            start=start,
            end=end,
            interval=yf_interval,
            auto_adjust=False,
            actions=True,
        )
    except Exception as exc:  # pragma: no cover - network failure path
        raise ProviderUnavailableError(f"yfinance request for {symbol!r} failed: {exc}") from exc


class YahooFinanceProvider(MarketDataProvider):
    """Normalizes yfinance price history into :class:`MarketBar` objects.

    Prices are RAW / UNADJUSTED
    ---------------------------
    This adapter requests ``auto_adjust=False`` and ``actions=False``, so the
    OHLC values it produces are the **raw, unadjusted** prices as traded.
    ``Adj Close`` is not requested, not consumed and not stored.

    Consequences you must understand before using this data:

    * corporate actions are **not represented by** :class:`MarketBar` at all --
      there is no split ratio, no dividend, no adjustment factor in the model;
    * a 4:1 split therefore appears as a ~-75% single-day return, and a large
      dividend as an unexplained gap down;
    * dedicated corporate-action handling is required before this source can
      support long-horizon strategy research;
    * the adjustment policy (raw vs. back-adjusted, and where adjustment
      happens) must be decided before any serious backtesting. It is
      deliberately out of scope for Phase 1.

    Other limitations (see also ``docs/market_data.md``):

    * unofficial, unsupported endpoint -- schema and availability can change
      without notice, and it is rate-limited;
    * intraday history is short (roughly 30 days for 1m bars) and delayed;
    * no exchange-official volume guarantees, occasional NaN/holiday padding;
    * volume is likewise unadjusted for splits;
    * not suitable for live trading decisions.

    Parameters
    ----------
    download_fn:
        ``(symbol, start, end, yfinance_interval) -> DataFrame``.  Defaults to
        a lazy yfinance call.  Injected in tests so nothing touches the network.
    assume_timezone:
        Timezone to attach if yfinance returns a naive index.  Left ``None``
        by default: a naive index raises instead of being guessed.
    skip_incomplete_rows:
        Drop (never fill) rows containing NaN/missing values.  Off by default.
    """

    name = "yfinance"
    supported_intervals = frozenset(_YF_INTERVALS)

    def __init__(
        self,
        *,
        download_fn: DownloadFn | None = None,
        assume_timezone: tzinfo | None = None,
        skip_incomplete_rows: bool = False,
    ) -> None:
        self._download = download_fn or _default_download
        self._assume_timezone = assume_timezone
        self._skip_incomplete_rows = skip_incomplete_rows

    # -- MarketDataProvider hook ----------------------------------------

    def _fetch_bars(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: Interval,
    ) -> Sequence[MarketBar]:
        # yfinance indexes each row by the bar's OPEN time, which is already
        # the canonical convention (see src.data.models), so the index is
        # carried across unchanged. An adapter for a vendor that stamps bars at
        # close time would have to subtract the interval here.
        frame = self._download(symbol, start, end, _YF_INTERVALS[interval])
        records = self._frame_to_records(frame, symbol)
        if not records:
            # No data for this window is a legitimate answer (delisted symbol,
            # market holiday, window before IPO). Never fabricate bars.
            return []

        bars = bars_from_records(
            records,
            symbol=symbol,
            interval=interval,
            source=self.name,
            assume_timezone=self._assume_timezone,
            skip_incomplete=self._skip_incomplete_rows,
        )
        # yfinance treats `end` as exclusive for some intervals and inclusive
        # for others; clip deterministically to the requested closed window.
        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)
        return [bar for bar in bars if start_utc <= bar.timestamp <= end_utc]

    # -- yfinance-specific unpacking ------------------------------------

    @staticmethod
    def _flatten_columns(frame: Any, symbol: str) -> Any:
        """Collapse ticker-keyed MultiIndex columns to a single level."""
        columns = frame.columns
        if getattr(columns, "nlevels", 1) <= 1:
            return frame
        levels_with_symbol = [
            level
            for level in range(columns.nlevels)
            if symbol in set(columns.get_level_values(level))
        ]
        if levels_with_symbol:
            return frame.xs(symbol, axis=1, level=levels_with_symbol[0])
        return frame.droplevel(list(range(1, columns.nlevels)), axis=1)

    @staticmethod
    def _frame_to_records(frame: Any, symbol: str) -> list[dict[str, Any]]:
        """Turn a yfinance DataFrame into plain records.

        Handles the two shapes yfinance emits: flat columns
        (``Ticker.history``) and ticker-keyed MultiIndex columns
        (``yfinance.download``).
        """
        if frame is None:
            return []
        if getattr(frame, "empty", False):
            return []
        if not hasattr(frame, "columns") or not hasattr(frame, "index"):
            raise ProviderUnavailableError(
                f"yfinance returned an unexpected object for {symbol!r}: {type(frame).__name__}"
            )

        frame = YahooFinanceProvider._flatten_columns(frame, symbol)

        wanted = {"open", "high", "low", "close", "volume"}
        selected: dict[str, Any] = {}
        for column in frame.columns:
            field = str(column).strip().lower()
            if field not in wanted:
                continue
            if field in selected:
                # Two columns normalize to the same field (e.g. "Close" and
                # "close"). Picking one would be an arbitrary choice between
                # two different price series, so refuse instead.
                raise ProviderUnavailableError(
                    f"yfinance response for {symbol!r} has more than one {field!r} column "
                    f"({selected[field]!r} and {column!r}); refusing to choose between them"
                )
            selected[field] = column
        missing = wanted - selected.keys()
        if missing:
            raise ProviderUnavailableError(
                f"yfinance response for {symbol!r} is missing column(s) {sorted(missing)}; "
                f"got {[str(c) for c in frame.columns]}"
            )

        records: list[dict[str, Any]] = []
        for timestamp, row in frame.iterrows():
            record: dict[str, Any] = {"timestamp": timestamp}
            for field, column in selected.items():
                record[field] = row[column]
            records.append(record)
        return records


    # -- corporate actions / adjustment ----------------------------------

    def get_adjustment_data(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: Interval | str = Interval.DAY_1,
    ) -> AdjustmentData:
        """Return the adjustment factors and corporate actions for a window.

        Uses the *same* response shape as :meth:`get_bars` -- Yahoo returns
        ``Adj Close``, ``Dividends`` and ``Stock Splits`` alongside the raw
        OHLCV -- so no additional request is made.

        The per-bar factor is ``Adj Close / Close``. That ratio was verified
        against the installed yfinance implementation to move across dividend
        dates as well as splits, so it produces a
        ``SPLIT_AND_DIVIDEND_ADJUSTED`` basis, not a split-only one. See
        ``docs/adr/0001-price-basis-and-corporate-actions.md``.

        Bars whose ``Adj Close`` is missing are skipped here rather than
        defaulted; :func:`~src.data.adjustment.adjust` will then refuse the
        series outright rather than adjust it partially.
        """
        symbol = self._normalize_symbol(symbol)
        interval = Interval.parse(interval)
        self._check_window(start, end)

        frame = self._download(symbol, start, end, _YF_INTERVALS[interval])
        rows = self._extra_columns(frame, symbol)

        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)

        factors: dict[datetime, float] = {}
        actions: list[CorporateAction] = []
        for row in rows:
            timestamp = coerce_timestamp(row["timestamp"], assume_timezone=self._assume_timezone)
            if not (start_utc <= timestamp <= end_utc):
                continue

            close, adj_close = row.get("close"), row.get("adj close")
            if not is_missing(close) and not is_missing(adj_close) and float(close) != 0:
                candidate = float(adj_close) / float(close)
                if math.isfinite(candidate) and candidate > 0:
                    factors[timestamp] = candidate

            split = row.get("stock splits")
            if not is_missing(split) and float(split) > 0:
                actions.append(
                    CorporateAction(
                        symbol=symbol,
                        effective_time=timestamp,
                        action_type=ActionType.SPLIT,
                        value=float(split),
                        source=self.name,
                    )
                )

            dividend = row.get("dividends")
            if not is_missing(dividend) and float(dividend) > 0:
                actions.append(
                    CorporateAction(
                        symbol=symbol,
                        effective_time=timestamp,
                        action_type=ActionType.CASH_DIVIDEND,
                        value=float(dividend),
                        source=self.name,
                    )
                )

        return AdjustmentData(
            symbol=symbol,
            source=self.name,
            interval=interval,
            produces_basis=PriceBasis.SPLIT_AND_DIVIDEND_ADJUSTED,
            factors=factors,
            actions=tuple(actions),
        )

    @staticmethod
    def _extra_columns(frame: Any, symbol: str) -> list[dict[str, Any]]:
        """Pull the adjustment-related columns out of a yfinance frame.

        Tolerant by design: a response without ``Adj Close`` or without the
        action columns yields fewer factors/actions rather than an exception,
        because the caller (``adjust``) is the layer that decides whether the
        resulting coverage is good enough.
        """
        if frame is None or getattr(frame, "empty", False):
            return []
        if not hasattr(frame, "columns") or not hasattr(frame, "index"):
            raise ProviderUnavailableError(
                f"yfinance returned an unexpected object for {symbol!r}: {type(frame).__name__}"
            )

        frame = YahooFinanceProvider._flatten_columns(frame, symbol)
        wanted = {"close", "adj close", "dividends", "stock splits"}
        selected: dict[str, Any] = {}
        for column in frame.columns:
            field = str(column).strip().lower()
            if field in wanted:
                if field in selected:
                    raise ProviderUnavailableError(
                        f"yfinance response for {symbol!r} has more than one {field!r} column"
                    )
                selected[field] = column

        rows: list[dict[str, Any]] = []
        for timestamp, row in frame.iterrows():
            record: dict[str, Any] = {"timestamp": timestamp}
            for field, column in selected.items():
                record[field] = row[column]
            rows.append(record)
        return rows


__all__ = ["YahooFinanceProvider"]
