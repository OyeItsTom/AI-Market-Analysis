"""Vendor-agnostic normalization helpers.

Provider adapters convert whatever their vendor returns (a pandas DataFrame,
a JSON payload, a CSV row) into plain Python mappings, then hand them to
:func:`bars_from_records`, which produces canonical
:class:`~src.data.models.MarketBar` objects.

Keeping this step here means:

* vendor column names (``"Open"``, ``"o"``, ``"t"``, ``"Date"``) are
  translated in exactly one place;
* the rest of the system never learns those names;
* nothing is invented -- a record missing a field is an error, never a zero,
  a forward-fill or an interpolation.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone, tzinfo
from typing import Any, Iterable, Mapping, Sequence

from .models import Interval, MarketBar

#: Canonical field name -> accepted source keys (compared case-insensitively).
DEFAULT_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "timestamp": ("timestamp", "time", "date", "datetime", "t"),
    "open": ("open", "o"),
    "high": ("high", "h"),
    "low": ("low", "l"),
    "close": ("close", "c"),
    "volume": ("volume", "vol", "v"),
}

_REQUIRED_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")


class NormalizationError(ValueError):
    """Raised when a vendor record cannot be turned into a :class:`MarketBar`."""


def _lookup(record: Mapping[str, Any], field: str, aliases: Mapping[str, Sequence[str]]) -> Any:
    lowered = {str(key).strip().lower(): value for key, value in record.items()}
    for alias in aliases.get(field, (field,)):
        if alias.lower() in lowered:
            return lowered[alias.lower()]
    raise NormalizationError(
        f"record is missing required field {field!r} "
        f"(looked for {list(aliases.get(field, (field,)))}, got {sorted(record)})"
    )


def is_missing(value: Any) -> bool:
    """``True`` if ``value`` represents an absent measurement.

    Covers ``None`` and every flavour of NaN/NaT we may receive (Python
    floats, numpy scalars, pandas ``NaT``) without importing a vendor library:
    those values are all unequal to themselves.  A value whose comparison is
    itself undefined (e.g. ``pandas.NA``) is *not* treated as missing — it
    falls through to the strict path and fails loudly, which is the safe
    direction for a value we do not understand.
    """
    if value is None:
        return True
    if isinstance(value, float):
        return math.isnan(value)
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        return False


def _localize(value: datetime, assume_timezone: tzinfo) -> datetime:
    """Attach ``assume_timezone`` to a naive ``value``, refusing DST edge cases.

    Around a daylight-saving transition a naive local time is either
    ambiguous (it happens twice, at two different UTC instants) or nonexistent
    (the clock jumps over it).  ``datetime.replace`` answers both silently and
    arbitrarily, which is exactly the "quietly guess the exchange timezone"
    behaviour this module exists to prevent — and an hour of silent error in
    an intraday series is very hard to spot later.

    Detection is standard library only: an ambiguous time has two different
    UTC offsets depending on ``fold``; a nonexistent time does not survive a
    round trip through UTC.
    """
    earlier = value.replace(tzinfo=assume_timezone, fold=0)
    later = value.replace(tzinfo=assume_timezone, fold=1)

    # Nonexistence is checked first: PEP 495 gives the two folds different UTC
    # offsets for a gap time as well as for an ambiguous one, so the ambiguity
    # test alone cannot tell them apart. A gap time is the one that does not
    # survive a round trip through UTC.
    if earlier.astimezone(timezone.utc).astimezone(assume_timezone).replace(tzinfo=None) != value:
        raise NormalizationError(
            f"local time {value.isoformat()} does not exist in {assume_timezone}: the clock "
            "jumps over it at a daylight-saving transition, so this timestamp cannot be a "
            "real market instant"
        )

    if earlier.utcoffset() != later.utcoffset():
        raise NormalizationError(
            f"local time {value.isoformat()} is ambiguous in {assume_timezone}: it occurs "
            f"twice (at {earlier.astimezone(timezone.utc).isoformat()} and "
            f"{later.astimezone(timezone.utc).isoformat()}) around a daylight-saving "
            "transition; refusing to guess which one the vendor meant"
        )

    return earlier


def coerce_timestamp(value: Any, *, assume_timezone: tzinfo | None = None) -> datetime:
    """Return a timezone-aware UTC datetime for ``value``.

    Accepts ``datetime`` objects and ISO-8601 strings.  A naive value is only
    accepted when ``assume_timezone`` is supplied by the caller: guessing the
    timezone of market data is how off-by-one-session bugs are born, so the
    default is to refuse.
    """
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise NormalizationError(f"cannot parse timestamp {value!r}: {exc}") from None
    if not isinstance(value, datetime):
        # pandas.Timestamp and friends expose to_pydatetime()
        to_pydatetime = getattr(value, "to_pydatetime", None)
        if callable(to_pydatetime):
            value = to_pydatetime()
        else:
            raise NormalizationError(
                f"timestamp must be a datetime or ISO-8601 string, got {type(value).__name__}"
            )

    if value.tzinfo is None or value.utcoffset() is None:
        if assume_timezone is None:
            raise NormalizationError(
                f"timestamp {value.isoformat()} is timezone-naive and no assume_timezone "
                "was configured; refusing to guess the exchange timezone"
            )
        value = _localize(value, assume_timezone)
    return value.astimezone(timezone.utc)


def bars_from_records(
    records: Iterable[Mapping[str, Any]],
    *,
    symbol: str,
    interval: Interval | str,
    source: str,
    field_aliases: Mapping[str, Sequence[str]] | None = None,
    assume_timezone: tzinfo | None = None,
    skip_incomplete: bool = False,
) -> list[MarketBar]:
    """Convert vendor records into :class:`MarketBar` objects.

    Parameters
    ----------
    records:
        Iterable of mappings, one per bar.
    symbol, interval, source:
        Applied to every produced bar.
    field_aliases:
        Overrides for :data:`DEFAULT_FIELD_ALIASES`.
    assume_timezone:
        Timezone to attach to naive timestamps.  Must be set deliberately by
        the adapter; otherwise naive timestamps are rejected.
    skip_incomplete:
        When ``True``, a row whose required values are **present but missing**
        (``None``/NaN/NaT) is dropped instead of raising.  Rows are only ever
        dropped, never filled -- opt in only when the vendor is known to pad
        non-trading periods.

        This is the *only* condition it suppresses.  It deliberately does not
        cover a missing column, an unparseable or timezone-less timestamp, an
        unexpected type, or any other failure: those mean the vendor's schema
        or our assumptions have changed, and dropping those rows would turn an
        infrastructure fault into an empty result indistinguishable from "the
        market was closed". Everything except a genuinely absent measurement
        raises.
    """
    aliases = dict(DEFAULT_FIELD_ALIASES)
    if field_aliases:
        aliases.update(field_aliases)

    bars: list[MarketBar] = []
    for index, record in enumerate(records):
        # Outside the try: a missing field is a schema change, never a skippable row.
        values = {field: _lookup(record, field, aliases) for field in _REQUIRED_FIELDS}

        absent = sorted(field for field, value in values.items() if is_missing(value))
        if absent:
            if skip_incomplete:
                continue
            raise NormalizationError(
                f"{source}: record {index} for {symbol!r} has no value for {absent}; "
                "pass skip_incomplete=True to drop such rows (they are never filled in)"
            )

        try:
            timestamp = coerce_timestamp(values["timestamp"], assume_timezone=assume_timezone)
            bar = MarketBar(
                symbol=symbol,
                timestamp=timestamp,
                open=float(values["open"]),
                high=float(values["high"]),
                low=float(values["low"]),
                close=float(values["close"]),
                volume=float(values["volume"]),
                interval=interval,
                source=source,
            )
        except (NormalizationError, TypeError, ValueError) as exc:
            # Re-raised with context, never suppressed -- see skip_incomplete above.
            raise NormalizationError(
                f"{source}: cannot normalize record {index} for {symbol!r}: {exc}"
            ) from exc
        bars.append(bar)
    return bars


__all__ = [
    "DEFAULT_FIELD_ALIASES",
    "NormalizationError",
    "bars_from_records",
    "coerce_timestamp",
    "is_missing",
]
