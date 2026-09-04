"""Local historical-bar storage.

Deliberately boring: CSV files on disk, written with the standard library.
No database in Phase 1 -- there is no query pattern yet that a directory of
CSV files cannot serve, and a schema chosen before the access patterns are
known is a liability.  The abstraction below is the seam to swap in Parquet
or SQLite later without touching callers.

Layout::

    <root>/<source>/<SYMBOL>/<interval>.csv

so provenance is visible from the path and bars from different providers can
never be silently mixed into one file.

``root`` defaults to ``data/raw/`` in the repository, which ``.gitignore``
already excludes -- downloaded market data must not be committed.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Sequence

from .models import Interval, MarketBar
from .validation import validate_bars

#: Repository root, i.e. the parent of ``src/``.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_ROOT = REPO_ROOT / "data" / "raw"
DEFAULT_PROCESSED_ROOT = REPO_ROOT / "data" / "processed"

CSV_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "symbol", "interval", "source")


class StorageError(RuntimeError):
    """Raised when stored data cannot be read, written or reconciled."""


@dataclass(frozen=True)
class SeriesKey:
    """Identifies one stored series: symbol + interval + provider."""

    symbol: str
    interval: Interval
    source: str

    @classmethod
    def from_bar(cls, bar: MarketBar) -> "SeriesKey":
        return cls(symbol=bar.symbol, interval=bar.interval, source=bar.source)

    def normalized(self) -> "SeriesKey":
        return SeriesKey(
            symbol=self.symbol.strip().upper(),
            interval=Interval.parse(self.interval),
            source=self.source.strip(),
        )


class CsvBarStore:
    """A local, file-backed cache of validated :class:`MarketBar` series."""

    def __init__(self, root: str | Path = DEFAULT_RAW_ROOT) -> None:
        self.root = Path(root)

    # -- paths -----------------------------------------------------------

    def path_for(self, key: SeriesKey) -> Path:
        key = key.normalized()
        safe_symbol = _safe_path_component(key.symbol)
        safe_source = _safe_path_component(key.source)
        return self.root / safe_source / safe_symbol / f"{key.interval.value}.csv"

    def exists(self, key: SeriesKey) -> bool:
        return self.path_for(key).is_file()

    # -- write -----------------------------------------------------------

    def write(self, bars: Sequence[MarketBar], *, key: SeriesKey | None = None) -> Path:
        """Validate ``bars`` and write them, replacing any existing file.

        Writing an empty sequence requires an explicit ``key`` (there is
        nothing to infer it from) and produces a header-only file.
        """
        bars = list(bars)
        if key is None:
            if not bars:
                raise StorageError("cannot infer a series key from an empty bar list; pass key=")
            key = SeriesKey.from_bar(bars[0])
        key = key.normalized()

        validate_bars(
            bars,
            expected_symbol=key.symbol,
            expected_interval=key.interval,
            require_sorted=True,
        )
        for index, bar in enumerate(bars):
            if bar.source != key.source:
                raise StorageError(
                    f"bar {index} has source {bar.source!r} but series key says {key.source!r}; "
                    "series from different providers are stored separately"
                )

        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".csv.tmp")
        with tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for bar in bars:
                row = bar.to_dict()
                writer.writerow({column: row[column] for column in CSV_COLUMNS})
        tmp_path.replace(path)  # atomic-ish: never leave a half-written cache file
        return path

    def merge(self, bars: Sequence[MarketBar], *, key: SeriesKey | None = None) -> Path:
        """Combine ``bars`` with what is already stored and rewrite the file.

        Overlapping timestamps must agree exactly.  A conflict raises rather
        than picking a winner: two different prices for the same instant means
        one of them is wrong, and this layer cannot know which.
        """
        bars = list(bars)
        if key is None:
            if not bars:
                raise StorageError("cannot infer a series key from an empty bar list; pass key=")
            key = SeriesKey.from_bar(bars[0])
        key = key.normalized()

        existing = self.read(key) if self.exists(key) else []
        combined: dict[datetime, MarketBar] = {bar.timestamp: bar for bar in existing}
        for bar in bars:
            previous = combined.get(bar.timestamp)
            if previous is not None and previous != bar:
                raise StorageError(
                    f"conflicting bars for {key.symbol} at {bar.timestamp.isoformat()}: "
                    f"stored {previous.to_dict()} vs incoming {bar.to_dict()}"
                )
            combined[bar.timestamp] = bar

        ordered = [combined[timestamp] for timestamp in sorted(combined)]
        return self.write(ordered, key=key)

    # -- read ------------------------------------------------------------

    def read(
        self,
        key: SeriesKey,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> list[MarketBar]:
        """Read a stored series, optionally clipped to ``[start, end]``.

        Everything read back is re-validated: a cache file can be edited,
        truncated or corrupted between runs, and stale bad data is exactly the
        kind of thing that quietly poisons a backtest.

        Provenance is verified too.  Each row carries its own symbol, interval
        and source, and every one must match the requested :class:`SeriesKey`.
        The write path already enforces this; without the same check on read, a
        hand-edited or misplaced file could silently hand back bars attributed
        to a provider that never produced them -- and ``source`` exists
        precisely so that two providers' data is never treated as
        interchangeable evidence.
        """
        key = key.normalized()
        path = self.path_for(key)
        if not path.is_file():
            raise StorageError(f"no stored series at {path}")

        bars: list[MarketBar] = []
        with path.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            missing = set(CSV_COLUMNS) - set(reader.fieldnames or ())
            if missing:
                raise StorageError(f"{path} is missing column(s) {sorted(missing)}")
            for line_number, row in enumerate(reader, start=2):
                try:
                    bars.append(MarketBar.from_dict(row))
                except (TypeError, ValueError, KeyError) as exc:
                    raise StorageError(f"{path}:{line_number} is not a valid bar: {exc}") from exc

        for index, bar in enumerate(bars):
            mismatches = [
                f"{field} {actual!r} != {expected!r}"
                for field, actual, expected in (
                    ("symbol", bar.symbol, key.symbol),
                    ("interval", bar.interval.value, key.interval.value),
                    ("source", bar.source, key.source),
                )
                if actual != expected
            ]
            if mismatches:
                raise StorageError(
                    f"{path}: row {index + 2} does not match the requested series "
                    f"({'; '.join(mismatches)}); refusing to change a bar's provenance"
                )

        validate_bars(
            bars,
            expected_symbol=key.symbol,
            expected_interval=key.interval,
            require_sorted=True,
        )

        if start is not None:
            start = _require_aware(start, "start")
            bars = [bar for bar in bars if bar.timestamp >= start]
        if end is not None:
            end = _require_aware(end, "end")
            bars = [bar for bar in bars if bar.timestamp <= end]
        return bars

    def list_series(self) -> list[SeriesKey]:
        """Enumerate every series currently stored under ``root``."""
        keys: list[SeriesKey] = []
        if not self.root.is_dir():
            return keys
        for path in sorted(self.root.glob("*/*/*.csv")):
            interval_name = path.stem
            try:
                interval = Interval.parse(interval_name)
            except ValueError:
                continue
            keys.append(
                SeriesKey(symbol=path.parent.name, interval=interval, source=path.parent.parent.name)
            )
        return keys


def _safe_path_component(value: str) -> str:
    """Reject anything that could escape ``root`` or confuse the filesystem."""
    if not value or any(character in value for character in ("/", "\\", "..", "\0")) or value in {".", ".."}:
        raise StorageError(f"unsafe path component {value!r}")
    return value


def _require_aware(value: datetime, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise StorageError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


__all__ = [
    "CsvBarStore",
    "SeriesKey",
    "StorageError",
    "DEFAULT_RAW_ROOT",
    "DEFAULT_PROCESSED_ROOT",
    "REPO_ROOT",
]
