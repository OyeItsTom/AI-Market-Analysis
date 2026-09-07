"""Records and vocabulary for scanning a configured universe of symbols.

The scanner **orders research attention**. It does not rate securities. That
distinction is carried in the types rather than left to the reader: there is no
score field, no confidence, no probability and no rating anywhere in this
module, because Phase 6 established that a handful of integer classifications
cannot honestly produce one.

Three separations do most of the work here.

**Eligibility is not merit.** :class:`EligibilityStatus` answers *can this
symbol be researched?* -- nothing more. A symbol with no bars and a symbol with
a unanimous assessment differ in eligibility, not in desirability.

**A research shortage is not an operational failure.** ``NO_DATA`` and
``INSUFFICIENT_EVIDENCE`` are successful scans of symbols that had little to
say. Only :class:`ScanErrorCode` marks something that went wrong, and only that
feeds :class:`ScanStatus`. A scan of fifty symbols that all lacked history
succeeded; reporting it as failure would be false.

**Category describes evidence structure.** :class:`StructuralCategory` says how
the hypotheses stood in relation to one another -- unanimous, split by
abstentions, in conflict -- and never which outcome a reader should prefer.
``BULLISH`` and ``BEARISH`` map to the same categories and sort identically.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Mapping

from src.assessments.assessment import (
    AssessmentCounts,
    AssessmentReasonCode,
    AssessmentState,
)
from src.data.models import Interval
from src.data.series import PriceBasis

# -- limits --------------------------------------------------------------

#: Slug bound for a universe id. It is short because it is an identifier, not
#: a description; the description is ``display_name``.
MAX_UNIVERSE_ID = 64

MAX_DISPLAY_NAME = 200
MAX_SOURCE_REFERENCE = 500
MAX_SYMBOL = 32

#: A hard safety ceiling, **not** a performance recommendation. Nothing here
#: claims a 100-symbol scan is quick; that question belongs to measurement.
MAX_SYMBOLS_PER_UNIVERSE = 100

MAX_UNIVERSES = 50
MAX_UNIVERSE_CONFIG_BYTES = 256 * 1024

#: Diagnostic text is truncated rather than trusted: it comes from a provider
#: exception and must never be long enough to dominate a record -- or be
#: mistaken for something the ranking consulted.
MAX_ERROR_DETAIL_CHARS = 300


class ScannerError(Exception):
    """Base class for every scanner failure."""


# -- vocabulary ----------------------------------------------------------


class UniverseSourceKind(str, Enum):
    """Where a universe's membership came from.

    Deliberately only two members. A kind such as ``VERIFIED_INDEX`` would be
    unconstructible: nothing in this repository can verify index membership, so
    offering the word would let a configuration file make a claim the system
    cannot support.
    """

    #: A fixed list kept in local configuration.
    LOCAL_STATIC = "local_static"

    #: A list the user assembled themselves.
    USER_DEFINED = "user_defined"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class EligibilityStatus(str, Enum):
    """Whether a symbol could be researched. Never whether it is attractive."""

    #: An assessment was produced.
    ELIGIBLE = "eligible"

    #: The provider returned no bars at all.
    NO_DATA = "no_data"

    #: Bars existed, but too few hypotheses classified for a finding.
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value

    @property
    def is_assessable(self) -> bool:
        return self is EligibilityStatus.ELIGIBLE


class StructuralCategory(str, Enum):
    """The shape of the evidence, not a judgement about it.

    Ordering between members is research-inspection order -- how much structure
    there is to look at -- and carries no claim about expected return, quality
    or desirability.
    """

    #: Every hypothesis that classified agreed on a direction.
    UNANIMOUS_DIRECTIONAL = "unanimous_directional"

    #: A direction among abstentions: some classified neutral.
    DIRECTIONAL_WITH_NEUTRAL = "directional_with_neutral"

    #: Hypotheses disagreed on direction. Often the most informative case,
    #: which is why it sorts above unanimous agreement that nothing is
    #: happening rather than being filed away as uninteresting.
    CONFLICTED = "conflicted"

    #: Everything that classified agreed there is no direction.
    NEUTRAL = "neutral"

    #: No assessment to describe: no data, too little evidence, or an error.
    NOT_ASSESSABLE = "not_assessable"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: Research-inspection order. Index 0 is examined first.
CATEGORY_ORDER: tuple[StructuralCategory, ...] = (
    StructuralCategory.UNANIMOUS_DIRECTIONAL,
    StructuralCategory.DIRECTIONAL_WITH_NEUTRAL,
    StructuralCategory.CONFLICTED,
    StructuralCategory.NEUTRAL,
    StructuralCategory.NOT_ASSESSABLE,
)

#: Categories a result may carry while still being ELIGIBLE.
ASSESSABLE_CATEGORIES: frozenset[StructuralCategory] = frozenset(
    CATEGORY_ORDER[:-1]
)


class ScanStatus(str, Enum):
    """How a completed scan went, judged only by operational errors.

    There is deliberately no ``NOTHING_CONFIGURED``: a snapshot describes a
    completed scan of a real universe, so "no universes configured" is a
    configuration state with no scan to describe. Manufacturing a snapshot for
    it would be inventing a record of something that never ran.
    """

    ALL_OK = "all_ok"
    PARTIAL = "partial"
    ALL_FAILED = "all_failed"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


class ScanErrorCode(str, Enum):
    """Operational failures, at the granularity the error layer supports.

    Each member maps to a distinct failure kind from the application error
    layer, matched by name rather than by import so this package stays a leaf.
    There is no ``PROVIDER_TIMEOUT`` or ``SYMBOL_NOT_FOUND`` because the
    application layer cannot tell them from an unavailable provider without
    parsing exception text -- and a taxonomy built on message strings would be
    wrong the first time a message changed.
    """

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    DATA_QUALITY = "data_quality"
    SYMBOL_MISMATCH = "symbol_mismatch"
    REQUEST_INVALID = "request_invalid"
    UNEXPECTED = "unexpected"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


# -- helpers -------------------------------------------------------------


def require_aware(value: object, label: str) -> datetime:
    """A timezone-aware datetime in UTC. Naive input is refused, not assumed."""
    if not isinstance(value, datetime):
        raise ScannerError(f"{label} must be a datetime, got {type(value).__name__}")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ScannerError(f"{label} must be timezone-aware")
    return value.astimezone(timezone.utc)


def require_text(value: object, label: str, *, maximum: int) -> str:
    """Non-empty, bounded, control-character-free text."""
    if not isinstance(value, str):
        raise ScannerError(f"{label} must be a str, got {type(value).__name__}")
    cleaned = value.strip()
    if not cleaned:
        raise ScannerError(f"{label} must not be empty")
    if len(cleaned) > maximum:
        raise ScannerError(f"{label} exceeds {maximum} characters")
    if any(ord(character) < 32 or ord(character) == 127 for character in cleaned):
        raise ScannerError(f"{label} contains control characters")
    return cleaned


def _require_count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ScannerError(f"{label} must be an int, got {type(value).__name__}")
    if value < 0:
        raise ScannerError(f"{label} must not be negative")
    return value


# -- universe ------------------------------------------------------------


@dataclass(frozen=True)
class UniverseDefinition:
    """One configured universe. Membership is a claim, dated and attributed.

    ``as_of`` and ``source_reference`` exist so a universe cannot masquerade as
    current index membership. A list captured today and scanned across two years
    of history is survivorship-biased, and the record has to say when the list
    was taken and where it came from for that to be visible.
    """

    universe_id: str
    display_name: str
    symbols: tuple[str, ...]
    source_kind: UniverseSourceKind
    source_reference: str
    as_of: date
    enabled: bool = True
    fingerprint: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "universe_id", require_universe_id(self.universe_id))
        set_(self, "display_name",
             require_text(self.display_name, "display_name", maximum=MAX_DISPLAY_NAME))
        set_(self, "source_kind", UniverseSourceKind(self.source_kind))
        set_(self, "source_reference",
             require_text(self.source_reference, "source_reference",
                          maximum=MAX_SOURCE_REFERENCE))
        if not isinstance(self.as_of, date) or isinstance(self.as_of, datetime):
            raise ScannerError("as_of must be a date (not a datetime)")
        if not isinstance(self.enabled, bool):
            raise ScannerError("enabled must be a boolean")

        symbols = tuple(self.symbols)
        if not symbols:
            raise ScannerError(f"{self.universe_id}: a universe must name at least one symbol")
        if len(symbols) > MAX_SYMBOLS_PER_UNIVERSE:
            raise ScannerError(
                f"{self.universe_id}: at most {MAX_SYMBOLS_PER_UNIVERSE} symbols, "
                f"got {len(symbols)}"
            )
        if len(set(symbols)) != len(symbols):
            raise ScannerError(f"{self.universe_id}: duplicate symbols")
        if list(symbols) != sorted(symbols):
            raise ScannerError(f"{self.universe_id}: symbols must be sorted")
        set_(self, "symbols", symbols)

        if self.fingerprint and len(self.fingerprint) != 64:
            raise ScannerError("fingerprint must be a full 64-character SHA-256 digest")

    @property
    def symbol_count(self) -> int:
        return len(self.symbols)


@dataclass(frozen=True)
class UniverseLoadReport:
    """What loading the configuration observed.

    These counts live here, not in :class:`ScanCounters`, because the loader is
    the component that saw them. A scanner handed an already-normalized
    universe cannot truthfully say how many duplicates were removed.
    """

    raw_symbol_count: int = 0
    normalized_symbol_count: int = 0
    duplicates_removed: int = 0
    universes_loaded: int = 0
    universes_enabled: int = 0

    def __post_init__(self) -> None:
        for f in dataclass_fields(self):
            object.__setattr__(self, f.name, _require_count(getattr(self, f.name), f.name))

    def describe(self) -> str:
        return (
            f"{self.universes_loaded} universes ({self.universes_enabled} enabled), "
            f"{self.raw_symbol_count} symbols read, "
            f"{self.normalized_symbol_count} kept, "
            f"{self.duplicates_removed} duplicates removed"
        )


@dataclass(frozen=True)
class UniverseConfiguration:
    """Every configured universe, plus how loading went.

    The report is embedded rather than returned separately so a caller holding
    a configuration always holds its diagnostics too -- there is no way to keep
    one and lose the other.
    """

    universes: tuple[UniverseDefinition, ...] = ()
    load_report: UniverseLoadReport = field(default_factory=UniverseLoadReport)
    schema_version: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "universes", tuple(self.universes))
        ids = [u.universe_id for u in self.universes]
        duplicates = sorted({name for name in ids if ids.count(name) > 1})
        if duplicates:
            raise ScannerError(f"duplicate universe_id: {duplicates}")
        if len(self.universes) > MAX_UNIVERSES:
            raise ScannerError(f"at most {MAX_UNIVERSES} universes, got {len(self.universes)}")

    @property
    def enabled(self) -> tuple[UniverseDefinition, ...]:
        return tuple(u for u in self.universes if u.enabled)

    @property
    def is_empty(self) -> bool:
        return not self.universes

    def get(self, universe_id: str) -> UniverseDefinition | None:
        for universe in self.universes:
            if universe.universe_id == universe_id:
                return universe
        return None


# -- counters ------------------------------------------------------------


@dataclass(frozen=True)
class ScanCounters:
    """What one scan did. Local counts, never telemetry."""

    symbols_total: int = 0
    symbols_attempted: int = 0
    symbols_completed: int = 0
    symbols_eligible: int = 0
    symbols_no_data: int = 0
    symbols_insufficient_evidence: int = 0
    symbols_failed: int = 0
    rows_ordered: int = 0
    provider_failures: int = 0

    def __post_init__(self) -> None:
        for f in dataclass_fields(self):
            object.__setattr__(self, f.name, _require_count(getattr(self, f.name), f.name))

    @classmethod
    def from_results(
        cls, results: "Sequence[SymbolScanResult]", *, symbols_total: int
    ) -> "ScanCounters":
        """Count a finished scan's results. The only correct way to build these.

        Offered because a caller assembling nine counters by hand will
        eventually get one wrong, and a snapshot carrying counters that
        disagree with its own results would be a record that lies about itself.
        """
        eligible = sum(1 for r in results if r.eligibility is EligibilityStatus.ELIGIBLE)
        return cls(
            symbols_total=symbols_total,
            symbols_attempted=len(results),
            symbols_completed=len(results),
            symbols_eligible=eligible,
            symbols_no_data=sum(
                1 for r in results
                if r.eligibility is EligibilityStatus.NO_DATA
            ),
            symbols_insufficient_evidence=sum(
                1 for r in results
                if r.eligibility is EligibilityStatus.INSUFFICIENT_EVIDENCE
            ),
            symbols_failed=sum(1 for r in results if r.is_operational_failure),
            rows_ordered=eligible,
            provider_failures=sum(
                1 for r in results
                if r.error_code is ScanErrorCode.PROVIDER_UNAVAILABLE
            ),
        )

    @property
    def terminal_total(self) -> int:
        """Symbols that reached exactly one terminal bucket."""
        return (
            self.symbols_eligible
            + self.symbols_no_data
            + self.symbols_insufficient_evidence
            + self.symbols_failed
        )

    @property
    def is_consistent(self) -> bool:
        """Whether the counters can all be true at once."""
        return (
            self.symbols_completed == self.terminal_total
            and self.symbols_attempted == self.symbols_completed
            and self.provider_failures <= self.symbols_failed
            and self.rows_ordered == self.symbols_eligible
            and self.symbols_attempted <= self.symbols_total
        )

    def describe(self) -> str:
        return (
            f"total={self.symbols_total} completed={self.symbols_completed} "
            f"eligible={self.symbols_eligible} no_data={self.symbols_no_data} "
            f"insufficient={self.symbols_insufficient_evidence} "
            f"failed={self.symbols_failed} rows={self.rows_ordered} "
            f"provider_failures={self.provider_failures}"
        )


# -- results -------------------------------------------------------------


@dataclass(frozen=True)
class SymbolScanResult:
    """One symbol's outcome. A summary, never the research itself.

    The full ``ResearchSnapshot`` and its ``BarSeries`` are deliberately not
    retained: a hundred of them would be hundreds of megabytes, and the symbol
    plus interval is enough to rebuild the deep view on demand.

    Invalid combinations are refused rather than merely discouraged. A result
    claiming ``ELIGIBLE`` with no assessment, or carrying both an error and an
    assessment, would be a record that cannot be true, and every consumer would
    have to defend against it.
    """

    symbol: str
    eligibility: EligibilityStatus | None
    category: StructuralCategory
    data_cutoff: datetime
    state: AssessmentState | None = None
    counts: AssessmentCounts | None = None
    reason_codes: tuple[AssessmentReasonCode, ...] = ()
    bar_count: int = 0
    latest_bar_open: datetime | None = None
    error_code: ScanErrorCode | None = None
    error_detail: str = ""

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "symbol", require_text(self.symbol, "symbol", maximum=MAX_SYMBOL))
        if self.eligibility is not None:
            set_(self, "eligibility", EligibilityStatus(self.eligibility))
        set_(self, "category", StructuralCategory(self.category))
        set_(self, "data_cutoff", require_aware(self.data_cutoff, "data_cutoff"))
        set_(self, "bar_count", _require_count(self.bar_count, "bar_count"))
        set_(self, "reason_codes",
             tuple(AssessmentReasonCode(code) for code in self.reason_codes))
        if self.state is not None:
            set_(self, "state", AssessmentState(self.state))
        if self.error_code is not None:
            set_(self, "error_code", ScanErrorCode(self.error_code))
        if self.latest_bar_open is not None:
            set_(self, "latest_bar_open",
                 require_aware(self.latest_bar_open, "latest_bar_open"))
        if not isinstance(self.error_detail, str):
            raise ScannerError("error_detail must be a str")
        set_(self, "error_detail", self.error_detail[:MAX_ERROR_DETAIL_CHARS])

        _check_result_combination(self)

    @property
    def is_eligible(self) -> bool:
        return self.eligibility is EligibilityStatus.ELIGIBLE

    @property
    def is_operational_failure(self) -> bool:
        """The only thing that makes a scan less than fully successful."""
        return self.error_code is not None

    @property
    def classifying_count(self) -> int:
        """Hypotheses that actually classified. Zero when nothing was assessed."""
        if self.counts is None:
            return 0
        return self.counts.bullish + self.counts.bearish + self.counts.neutral


def _check_result_combination(result: "SymbolScanResult") -> None:
    """Refuse records that cannot be true.

    Kept as a function so each rule reads as the sentence it enforces.
    """
    if result.is_operational_failure:
        # Eligibility is *undetermined*, not NO_DATA. "Can this symbol be
        # researched?" was never answered, because the attempt failed before it
        # could be. Recording a failure as NO_DATA would also make counting by
        # eligibility disagree with ScanCounters, which buckets failures
        # separately -- the same symbol would land in two buckets.
        if result.eligibility is not None:
            raise ScannerError(
                "a failed symbol has no determined eligibility; "
                f"got {result.eligibility.value!r}"
            )
        if result.state is not None or result.counts is not None:
            raise ScannerError("a failed symbol has no assessment to report")
        if result.reason_codes:
            raise ScannerError("a failed symbol has no reason codes")
        if result.category is not StructuralCategory.NOT_ASSESSABLE:
            raise ScannerError("a failed symbol is NOT_ASSESSABLE")
        if result.bar_count:
            raise ScannerError("a failed symbol reports no bars")
        return

    if result.eligibility is EligibilityStatus.ELIGIBLE:
        if result.state is None or result.counts is None:
            raise ScannerError("ELIGIBLE requires a state and counts")
        if result.state is AssessmentState.INSUFFICIENT_DATA:
            raise ScannerError(
                "an INSUFFICIENT_DATA assessment is INSUFFICIENT_EVIDENCE, not ELIGIBLE"
            )
        if not result.reason_codes:
            raise ScannerError("ELIGIBLE requires at least one reason code")
        if result.category not in ASSESSABLE_CATEGORIES:
            raise ScannerError(
                f"ELIGIBLE must carry an assessable category, got {result.category.value!r}"
            )
        return

    if result.eligibility is EligibilityStatus.INSUFFICIENT_EVIDENCE:
        if result.state is not AssessmentState.INSUFFICIENT_DATA:
            raise ScannerError("INSUFFICIENT_EVIDENCE requires state INSUFFICIENT_DATA")
        if result.category is not StructuralCategory.NOT_ASSESSABLE:
            raise ScannerError("INSUFFICIENT_EVIDENCE is NOT_ASSESSABLE")
        return

    if result.eligibility is None:
        raise ScannerError("a symbol that did not fail must carry an eligibility")

    # NO_DATA without an error code.
    if result.state is not None or result.counts is not None:
        raise ScannerError("NO_DATA has no assessment to report")
    if result.reason_codes:
        raise ScannerError("NO_DATA has no reason codes")
    if result.category is not StructuralCategory.NOT_ASSESSABLE:
        raise ScannerError("NO_DATA is NOT_ASSESSABLE")
    if result.bar_count:
        raise ScannerError("NO_DATA reports no bars")


@dataclass(frozen=True)
class MarketScanSnapshot:
    """One completed scan. Immutable, and never partially updated.

    There is deliberately **no global market cutoff**. A scan of many symbols
    takes minutes, and the first and last symbols were fetched at different
    moments; a single "as of" would assert a simultaneous market state that
    never existed. Each result carries its own ``data_cutoff`` instead.

    The snapshot is self-describing while it is held, which is enough to explain
    the scan on screen. It is **not** a durable reproduction: nothing is
    persisted and the underlying market data may be revised by the provider, so
    re-running tomorrow may legitimately differ.
    """

    universe_id: str
    universe_fingerprint: str
    universe_display_name: str
    universe_as_of: date
    interval: Interval
    basis: PriceBasis
    policy_fingerprint: str
    warmup_bars: int
    minimum_sufficient_observations: int
    scan_started_at: datetime
    scan_completed_at: datetime
    results: tuple[SymbolScanResult, ...]
    counters: ScanCounters
    status: ScanStatus

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "universe_id", require_universe_id(self.universe_id))
        set_(self, "universe_display_name",
             require_text(self.universe_display_name, "universe_display_name",
                          maximum=MAX_DISPLAY_NAME))
        set_(self, "interval", Interval.parse(self.interval))
        set_(self, "basis", PriceBasis(self.basis))
        set_(self, "status", ScanStatus(self.status))
        set_(self, "results", tuple(self.results))
        set_(self, "warmup_bars", _require_count(self.warmup_bars, "warmup_bars"))
        set_(self, "minimum_sufficient_observations",
             _require_count(self.minimum_sufficient_observations,
                            "minimum_sufficient_observations"))
        started = require_aware(self.scan_started_at, "scan_started_at")
        completed = require_aware(self.scan_completed_at, "scan_completed_at")
        if completed < started:
            raise ScannerError("scan_completed_at must not precede scan_started_at")
        set_(self, "scan_started_at", started)
        set_(self, "scan_completed_at", completed)
        if len(self.universe_fingerprint) != 64:
            raise ScannerError("universe_fingerprint must be a full SHA-256 digest")
        if not isinstance(self.universe_as_of, date) or isinstance(self.universe_as_of, datetime):
            raise ScannerError("universe_as_of must be a date")

        symbols = [result.symbol for result in self.results]
        if len(set(symbols)) != len(symbols):
            raise ScannerError("each symbol may appear at most once in a scan")

        # A snapshot is the whole truth about one scan, so it may not contradict
        # itself. Status and counters are *derived* from the results rather than
        # taken on trust: helpers a caller can forget to call are not invariants,
        # and Stage E would otherwise be able to publish a snapshot that lies.
        _check_agrees_with_results(self)

    @property
    def duration_seconds(self) -> float:
        return (self.scan_completed_at - self.scan_started_at).total_seconds()

    @property
    def failures(self) -> tuple[SymbolScanResult, ...]:
        return tuple(r for r in self.results if r.is_operational_failure)

    @property
    def is_partial(self) -> bool:
        return self.status is ScanStatus.PARTIAL


def _check_agrees_with_results(snapshot: "MarketScanSnapshot") -> None:
    """Refuse a snapshot whose summary disagrees with its own results."""
    expected_status = status_for(snapshot.results)
    if snapshot.status is not expected_status:
        raise ScannerError(
            f"status {snapshot.status.value!r} contradicts the results "
            f"({expected_status.value!r} follows from "
            f"{len(snapshot.failures)} operational failures of "
            f"{len(snapshot.results)})"
        )

    expected = ScanCounters.from_results(
        snapshot.results, symbols_total=snapshot.counters.symbols_total
    )
    if snapshot.counters != expected:
        raise ScannerError(
            f"counters disagree with the results: expected "
            f"{expected.describe()}, got {snapshot.counters.describe()}"
        )
    if snapshot.counters.symbols_total < snapshot.counters.symbols_completed:
        raise ScannerError(
            "symbols_total must not be fewer than the symbols completed"
        )


def require_universe_id(value: object) -> str:
    """A bounded lower-case slug. Never a path.

    A universe id may one day name a directory, so path separators, traversal
    and control characters are refused here rather than escaped later.
    """
    if not isinstance(value, str):
        raise ScannerError(f"universe_id must be a str, got {type(value).__name__}")
    slug = value.strip().lower()
    if not slug:
        raise ScannerError("universe_id must not be empty")
    if len(slug) > MAX_UNIVERSE_ID:
        raise ScannerError(f"universe_id exceeds {MAX_UNIVERSE_ID} characters")
    if not all(character.isalnum() or character in "-_" for character in slug):
        raise ScannerError(
            f"universe_id {value!r} may contain only letters, digits, '-' and '_'"
        )
    return slug


def status_for(results: "tuple[SymbolScanResult, ...]") -> ScanStatus:
    """Scan status from operational errors alone.

    A shortage of research evidence is not a failed scan: fifty symbols that
    all lacked history were scanned perfectly well, and reporting that as
    failure would be untrue.
    """
    if not results:
        raise ScannerError("a completed scan has at least one result")
    failed = sum(1 for result in results if result.is_operational_failure)
    if failed == 0:
        return ScanStatus.ALL_OK
    if failed == len(results):
        return ScanStatus.ALL_FAILED
    return ScanStatus.PARTIAL


__all__ = [
    "MAX_UNIVERSE_ID", "MAX_DISPLAY_NAME", "MAX_SOURCE_REFERENCE", "MAX_SYMBOL",
    "MAX_SYMBOLS_PER_UNIVERSE", "MAX_UNIVERSES", "MAX_UNIVERSE_CONFIG_BYTES",
    "MAX_ERROR_DETAIL_CHARS",
    "ScannerError",
    "UniverseSourceKind", "EligibilityStatus", "StructuralCategory",
    "CATEGORY_ORDER", "ASSESSABLE_CATEGORIES",
    "ScanStatus", "ScanErrorCode",
    "UniverseDefinition", "UniverseLoadReport", "UniverseConfiguration",
    "ScanCounters", "SymbolScanResult", "MarketScanSnapshot",
    "require_aware", "require_text", "require_universe_id", "status_for",
]
