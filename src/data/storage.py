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
from .series import BarSeries, PriceBasis
from .validation import validate_bars

#: Repository root, i.e. the parent of ``src/``.
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_ROOT = REPO_ROOT / "data" / "raw"
DEFAULT_PROCESSED_ROOT = REPO_ROOT / "data" / "processed"

#: Columns written to every new file. ``price_basis`` makes a stored file
#: self-describing, so its basis is verifiable after it has been moved or
#: renamed -- the filename alone is never trusted for correctness.
CSV_COLUMNS = (
    "timestamp", "open", "high", "low", "close", "volume",
    "symbol", "interval", "source", "price_basis",
)

#: Columns a file MUST have to be readable. Phase 1 wrote files before
#: ``PriceBasis`` existed, so ``price_basis`` is deliberately absent here: a
#: file without it is a legacy raw file (see ``_basis_of_row``).
REQUIRED_CSV_COLUMNS = tuple(column for column in CSV_COLUMNS if column != "price_basis")


class StorageError(RuntimeError):
    """Raised when stored data cannot be read, written or reconciled."""


@dataclass(frozen=True)
class SeriesKey:
    """Identifies one stored series: symbol + interval + provider + price basis.

    ``basis`` defaults to :attr:`~src.data.series.PriceBasis.RAW`, which is what
    makes this backward compatible: every Phase 1 call site
    (``SeriesKey("AAPL", Interval.DAY_1, "yfinance")``) keeps working and now
    means "the raw series", explicitly rather than by omission.

    Two keys differing only in basis are **unequal** (frozen dataclass equality
    covers every field) and resolve to different paths, so a raw and an
    adjusted series for the same instrument can never overwrite one another.
    """

    symbol: str
    interval: Interval
    source: str
    basis: PriceBasis = PriceBasis.RAW

    @classmethod
    def from_bar(cls, bar: MarketBar) -> "SeriesKey":
        """Infer a key from a bar, assuming RAW.

        A :class:`MarketBar` deliberately carries no price basis (see ADR
        0001), so this cannot detect a derived series. Use
        :meth:`CsvBarStore.write_series` for anything that is not raw.
        """
        return cls(symbol=bar.symbol, interval=bar.interval, source=bar.source)

    @classmethod
    def from_series(cls, series: BarSeries) -> "SeriesKey":
        """Infer a key from a :class:`BarSeries`, including its basis."""
        return cls(
            symbol=series.symbol,
            interval=series.interval,
            source=series.source,
            basis=series.basis,
        )

    def normalized(self) -> "SeriesKey":
        return SeriesKey(
            symbol=self.symbol.strip().upper(),
            interval=Interval.parse(self.interval),
            source=self.source.strip(),
            basis=PriceBasis(self.basis),
        )


class CsvBarStore:
    """A local, file-backed cache of validated :class:`MarketBar` series."""

    def __init__(self, root: str | Path = DEFAULT_RAW_ROOT) -> None:
        self.root = Path(root)

    # -- paths -----------------------------------------------------------

    def path_for(self, key: SeriesKey) -> Path:
        """Resolve a key to its file.

        RAW series keep the exact Phase 1 filename (``1d.csv``), so files
        written before price basis existed remain in place and readable.
        Derived series get a basis-qualified name
        (``1d.split_and_dividend_adjusted.csv``), so the two can never collide.

        The filename is a *routing* device, not the authority on basis: the
        file's own ``price_basis`` column is what :meth:`read` verifies.
        """
        key = key.normalized()
        safe_symbol = _safe_path_component(key.symbol)
        safe_source = _safe_path_component(key.source)
        stem = key.interval.value
        if key.basis is not PriceBasis.RAW:
            stem = f"{stem}.{key.basis.value}"
        return self.root / safe_source / safe_symbol / f"{stem}.csv"

    def exists(self, key: SeriesKey) -> bool:
        return self.path_for(key).is_file()

    # -- write -----------------------------------------------------------

    def write(
        self, bars: Sequence[MarketBar] | BarSeries, *, key: SeriesKey | None = None
    ) -> Path:
        """Validate ``bars`` and write them, replacing any existing file.

        Accepts a :class:`~src.data.series.BarSeries`, in which case its price
        basis is used automatically. A bare sequence of :class:`MarketBar`
        carries no basis (ADR 0001), so it is assumed **RAW** unless ``key``
        says otherwise.

        .. warning::
           ``store.write(adjusted_series.bars)`` -- unwrapping a derived series
           into bare bars -- discards the basis and would file adjusted values
           as raw. Pass the ``BarSeries`` itself, or an explicit ``key``.

        Writing an empty sequence requires an explicit ``key`` (there is
        nothing to infer it from) and produces a header-only file.
        """
        if isinstance(bars, BarSeries):
            key = key or SeriesKey.from_series(bars)
            bars = list(bars.bars)
        else:
            bars = list(bars)
        if key is None:
            if not bars:
                raise StorageError("cannot infer a series key from an empty bar list; pass key=")
            key = SeriesKey.from_bar(bars[0])
        key = key.normalized()

        # Provenance is checked before validation so that a storage-level
        # mismatch keeps reporting as StorageError (the Phase 1 contract, and
        # symmetrical with read()), rather than surfacing as the more general
        # ValidationError that validate_bars now also raises for mixed sources.
        for index, bar in enumerate(bars):
            if bar.source != key.source:
                raise StorageError(
                    f"bar {index} has source {bar.source!r} but series key says {key.source!r}; "
                    "series from different providers are stored separately"
                )

        validate_bars(
            bars,
            expected_symbol=key.symbol,
            expected_interval=key.interval,
            expected_source=key.source,
            require_sorted=True,
        )

        path = self.path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".csv.tmp")
        with tmp_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
            writer.writeheader()
            for bar in bars:
                row = bar.to_dict()
                row["price_basis"] = key.basis.value
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
            fieldnames = set(reader.fieldnames or ())
            missing = set(REQUIRED_CSV_COLUMNS) - fieldnames
            if missing:
                raise StorageError(f"{path} is missing column(s) {sorted(missing)}")
            # Legacy-ness is a property of the FILE (its header), not of an
            # individual cell -- see _basis_of_row.
            has_basis_column = "price_basis" in fieldnames
            for line_number, row in enumerate(reader, start=2):
                stored_basis = _basis_of_row(
                    row, path, line_number, column_present=has_basis_column
                )
                if stored_basis is not key.basis:
                    raise StorageError(
                        f"{path}:{line_number} declares price basis "
                        f"{stored_basis.value!r} but {key.basis.value!r} was requested; "
                        "refusing to return a series on a different price basis. The "
                        "file's own metadata is authoritative -- renaming a file does "
                        "not change what its numbers mean."
                    )
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
            expected_source=key.source,
            require_sorted=True,
        )

        if start is not None:
            start = _require_aware(start, "start")
            bars = [bar for bar in bars if bar.timestamp >= start]
        if end is not None:
            end = _require_aware(end, "end")
            bars = [bar for bar in bars if bar.timestamp <= end]
        return bars

    # -- BarSeries API ---------------------------------------------------
    #
    # Thin wrappers over the MarketBar core above -- no duplicated storage
    # logic. They exist because a BarSeries is the only thing that knows its
    # own price basis, so round-tripping through them is the safe path.

    def write_series(self, series: BarSeries) -> Path:
        """Persist a :class:`BarSeries`, filing it under its own price basis.

        The sanctioned way to store derived data: the basis travels with the
        series, so an adjusted series cannot be filed as raw by accident.
        """
        if not isinstance(series, BarSeries):
            raise StorageError(f"expected a BarSeries, got {type(series).__name__}")
        return self.write(series)

    def read_series(
        self,
        key: SeriesKey,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> BarSeries:
        """Read a stored series back as a :class:`BarSeries`.

        The returned series carries the basis that the **file itself**
        declares -- :meth:`read` has already refused the load if that
        disagreed with ``key``.

        Value reproducibility, not transformation reproducibility: the numbers
        come back exactly, but the adjustment factors and corporate-action
        snapshot that produced a derived series are **not** persisted, so the
        derivation cannot be re-executed from storage alone. See ADR 0001.
        """
        key = key.normalized()
        bars = self.read(key, start=start, end=end)
        note = (
            f"loaded from {self.path_for(key)}; values reproduced exactly, but the "
            "adjustment factors that produced them are not persisted "
            "(transformation reproducibility is deferred -- see ADR 0001)"
            if key.basis.is_derived
            else f"loaded from {self.path_for(key)}"
        )
        return BarSeries(
            symbol=key.symbol,
            interval=key.interval,
            source=key.source,
            basis=key.basis,
            bars=tuple(bars),
            provenance=note,
        )

    def list_series(self) -> list[SeriesKey]:
        """Enumerate every series currently stored under ``root``."""
        keys: list[SeriesKey] = []
        if not self.root.is_dir():
            return keys
        for path in sorted(self.root.glob("*/*/*.csv")):
            interval_name, _, basis_name = path.stem.partition(".")
            try:
                interval = Interval.parse(interval_name)
                basis = PriceBasis(basis_name) if basis_name else PriceBasis.RAW
            except ValueError:
                continue
            keys.append(
                SeriesKey(
                    symbol=path.parent.name,
                    interval=interval,
                    source=path.parent.parent.name,
                    basis=basis,
                )
            )
        return keys


def _basis_of_row(
    row: dict, path: Path, line_number: int, *, column_present: bool
) -> PriceBasis:
    """Read a row's declared price basis.

    Backward-compatibility policy, applied here and nowhere else, and keyed on
    the **header** rather than on the cell:

    * ``column_present is False`` -- the file has no ``price_basis`` column at
      all, so it was written by Phase 1, before the concept existed. Phase 1
      could only ever store raw data, so the file is RAW *by definition*.
    * ``column_present is True`` -- the file is self-describing, and every row
      must say what it is. A blank or unrecognised value is a corrupt modern
      file, not a legacy one, and raises.

    The distinction matters: treating a blank cell in a modern file as "legacy,
    therefore RAW" would let anyone launder an adjusted file into a raw one by
    clearing a column, defeating the point of storing the basis at all.
    """
    if not column_present:
        return PriceBasis.RAW

    raw_value = row.get("price_basis")
    text = "" if raw_value is None else str(raw_value).strip()
    if not text:
        raise StorageError(
            f"{path}:{line_number} has a price_basis column but no value for it; "
            "a file that declares the column must declare a basis on every row "
            "(an empty cell is a corrupt file, not a legacy one)"
        )
    try:
        return PriceBasis(text)
    except ValueError:
        known = ", ".join(basis.value for basis in PriceBasis)
        raise StorageError(
            f"{path}:{line_number} declares unknown price basis {raw_value!r}; "
            f"known bases: {known}"
        ) from None


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
