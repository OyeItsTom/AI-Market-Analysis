"""Orchestration for the market scanner: one universe, many symbols, one snapshot.

    universe -> for each symbol -> build_snapshot -> eligibility -> category
             -> SymbolScanResult -> one MarketScanSnapshot

This module **orchestrates**; it decides nothing about research. Every value it
records comes from the existing Phase 1-6 pipeline through ``build_snapshot``,
which is reused unchanged. No feature is computed here, no hypothesis is
evaluated here, and no ranking rule is re-implemented here -- a second,
disagreeing copy of the research rules is the failure this layer exists to avoid.

Three separations shape the code.

**Symbols are independent.** One symbol failing must not discard the rest. Each
is built, mapped and recorded on its own, and the scan reports a per-symbol
outcome. What it never does is turn a *research* shortage into an execution
failure: fifty symbols that all lacked history were scanned perfectly well.

**Per-symbol failure is not global failure.** A provider outage for one ticker
produces an error row. An unusable request, an unsupported interval or a broken
invariant raises, because those are faults in the scan itself and hiding them
inside a result row would make a programming bug look like a market condition.

**Nothing is published half-built.** Results accumulate locally and a snapshot is
returned only once the loop finishes. This module knows nothing about session
state; whether to replace a previous snapshot is the caller's decision.

Policy metadata is read from the research configuration directly rather than
from whichever symbol happened to succeed first, so an all-failed scan is still
fully described.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol

from src.application.errors import ApplicationError, FailureKind
from src.application.snapshot import (
    BASIS,
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    WARMUP_BARS,
    ResearchSnapshot,
    build_ensemble,
    build_policy,
    build_snapshot,
)
from src.data.models import Interval
from src.data.provider import MarketDataProvider
from src.scanner.config import load_configuration
from src.scanner.eligibility import eligibility_for, error_for
from src.scanner.models import (
    MAX_ERROR_DETAIL_CHARS,
    EligibilityStatus,
    MarketScanSnapshot,
    ScanCounters,
    ScannerError,
    ScanErrorCode,
    StructuralCategory,
    SymbolScanResult,
    UniverseConfiguration,
    UniverseDefinition,
    status_for,
)
from src.scanner.ranking import category_for, ordered_rows

#: V1 scans daily bars only. Research supports weekly and monthly too, but the
#: scanner's freshness and history assumptions have only been reasoned through
#: for daily; accepting the others silently would ship an untested claim.
SCANNER_INTERVALS: tuple[Interval, ...] = (Interval.DAY_1,)

Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ScanRequestError(ScannerError):
    """The scan itself is unusable. Raised instead of producing a snapshot.

    Distinct from a per-symbol error: there is no partial truth to report when
    the request was never valid.
    """


@dataclass(frozen=True)
class ScanProgress:
    """One completed symbol. Reporting only -- never part of a snapshot."""

    completed: int
    total: int
    symbol: str
    failures: int


class SnapshotBuilder(Protocol):
    """``build_snapshot``'s shape, injected so tests stay offline."""

    def __call__(
        self,
        provider: MarketDataProvider,
        symbol: str,
        interval: Interval,
        *,
        now: Clock = ...,
    ) -> ResearchSnapshot: ...


ProgressCallback = Callable[[ScanProgress], None]


def load_universes(path: str | None = None) -> UniverseConfiguration:
    """Read the configured universes through the scanner's config adapter.

    Re-exported here so the dashboard reaches configuration the same way it
    reaches everything else -- through the application layer. It keeps
    ``src.dashboard`` free of any scanner-domain import, and keeps the file read
    where it belongs: inside the adapter, never in a view or in ``app.py``.
    """
    return load_configuration(path)


def research_policy_fingerprint() -> str:
    """The ensemble's policy identity, read from the research configuration.

    Deliberately *not* taken from the first successful symbol: a scan where
    every symbol failed still has a policy, and metadata that appears only when
    something succeeds would make two scans of the same universe describe
    themselves differently.
    """
    return build_policy(build_ensemble()).fingerprint


class MarketScanner:
    """Serial, manual orchestration over one configured universe.

    Serial by decision, not by omission: the provider fetches one symbol per
    call, ordering stays deterministic, failures stay isolated, and no
    concurrency question is answered before it has been measured. Nothing here
    starts a thread, a timer or a scheduler -- a scan happens because a human
    asked for one.
    """

    def __init__(
        self,
        provider: MarketDataProvider,
        *,
        build: SnapshotBuilder = build_snapshot,
        now: Clock = _utc_now,
    ) -> None:
        self._provider = provider
        self._build = build
        self._now = now

    # -- scanning --------------------------------------------------------

    def scan(
        self,
        universe: UniverseDefinition,
        interval: Interval | str = Interval.DAY_1,
        *,
        progress: ProgressCallback | None = None,
    ) -> MarketScanSnapshot:
        """Scan every symbol in ``universe`` and return one whole snapshot.

        Raises :class:`ScanRequestError` when the request itself is unusable --
        an unsupported interval, or a universe with nothing to scan. A symbol
        failing is an outcome, not an exception: it is recorded and reported.
        """
        interval = self._require_supported(interval)
        if not isinstance(universe, UniverseDefinition):
            raise ScanRequestError(
                f"a scan needs a UniverseDefinition, got {type(universe).__name__}"
            )
        if not universe.symbols:
            # Unreachable through the model, which requires at least one symbol.
            # Checked anyway: an "successful" scan of nothing would be a
            # misleading record rather than an empty one.
            raise ScanRequestError(
                f"universe {universe.universe_id!r} names no symbols to scan"
            )

        started_at = self._require_aware(self._now(), "scan start time")

        results: list[SymbolScanResult] = []
        failures = 0
        for symbol in universe.symbols:
            result = self._scan_one(symbol, interval)
            results.append(result)
            if result.is_operational_failure:
                failures += 1
            if progress is not None:
                # Deliberately outside the per-symbol try: a callback raising is
                # a fault in the caller, not a market condition, and swallowing
                # it would hide an application bug behind a clean scan.
                progress(
                    ScanProgress(
                        completed=len(results),
                        total=len(universe.symbols),
                        symbol=symbol,
                        failures=failures,
                    )
                )

        completed_at = self._require_aware(self._now(), "scan completion time")
        frozen = tuple(results)
        return MarketScanSnapshot(
            universe_id=universe.universe_id,
            universe_fingerprint=universe.fingerprint,
            universe_display_name=universe.display_name,
            universe_as_of=universe.as_of,
            interval=interval,
            basis=BASIS,
            policy_fingerprint=research_policy_fingerprint(),
            warmup_bars=WARMUP_BARS,
            minimum_sufficient_observations=MINIMUM_SUFFICIENT_OBSERVATIONS,
            scan_started_at=started_at,
            scan_completed_at=completed_at,
            results=frozen,
            counters=ScanCounters.from_results(
                frozen, symbols_total=len(universe.symbols)
            ),
            status=status_for(frozen),
        )

    # -- one symbol ------------------------------------------------------

    def _scan_one(self, symbol: str, interval: Interval) -> SymbolScanResult:
        """One symbol's whole outcome, isolated from every other symbol.

        The ``try`` covers **only the research call**. Summarising its result is
        the scanner's own logic, so it runs outside: if ``category_for`` or a
        ``SymbolScanResult`` invariant raises, that is a bug in this module, and
        turning it into an ``UNEXPECTED`` row would make a programming defect
        indistinguishable from a provider outage -- a whole scan could report
        ``ALL_FAILED`` while the market was fine.
        """
        try:
            snapshot = self._build(self._provider, symbol, interval, now=self._now)
        except ApplicationError as exc:
            return self._error_result(symbol, error_for(exc), exc.message)
        except Exception as exc:
            return self._error_result(
                symbol, ScanErrorCode.UNEXPECTED, f"{type(exc).__name__}: {exc}"
            )
        # Outside the catch on purpose: a fault here is ours, and must be loud.
        return self._result_for(symbol, snapshot)

    def _result_for(self, symbol: str, snapshot: ResearchSnapshot) -> SymbolScanResult:
        """Summarise one research snapshot. The snapshot itself is not kept.

        Retaining a hundred ``ResearchSnapshot`` objects would mean retaining a
        hundred ``BarSeries``; the symbol and interval are enough to rebuild the
        deep view when a human asks for it.
        """
        assessment = snapshot.assessment
        eligibility = eligibility_for(snapshot)
        state = assessment.state if assessment is not None else None
        reason_codes = tuple(assessment.reason_codes) if assessment is not None else ()
        category = category_for(state, reason_codes)

        if eligibility is not EligibilityStatus.ELIGIBLE:
            # NOT_ASSESSABLE is the only honest category for a symbol with no
            # finding, whatever partial evidence exists behind it.
            category = StructuralCategory.NOT_ASSESSABLE

        return SymbolScanResult(
            symbol=snapshot.symbol,
            eligibility=eligibility,
            category=category,
            # The symbol's own observation time. There is no global cutoff,
            # because a scan spanning minutes never observed one.
            data_cutoff=snapshot.built_at,
            state=state,
            counts=assessment.counts if assessment is not None else None,
            reason_codes=reason_codes if eligibility is EligibilityStatus.ELIGIBLE else (),
            bar_count=snapshot.bar_count,
            latest_bar_open=snapshot.latest_bar_open,
        )

    def _error_result(
        self, symbol: str, code: ScanErrorCode, detail: str
    ) -> SymbolScanResult:
        """An operational failure. Eligibility was never determined.

        ``data_cutoff`` is the moment this attempt was observed to fail, not a
        market-data cutoff -- no market data was obtained, so none can be
        reported. ``error_code`` being set is what tells a reader that: a result
        carrying an error has no bars, no assessment and no eligibility, so the
        timestamp cannot be mistaken for an observation of the market.
        """
        return SymbolScanResult(
            symbol=symbol,
            eligibility=None,
            category=StructuralCategory.NOT_ASSESSABLE,
            data_cutoff=self._require_aware(self._now(), "error time"),
            error_code=code,
            error_detail=detail[:MAX_ERROR_DETAIL_CHARS],
        )

    # -- request validation ----------------------------------------------

    @staticmethod
    def _require_supported(interval: Interval | str) -> Interval:
        try:
            parsed = Interval.parse(interval)
        except Exception as exc:
            raise ScanRequestError(f"unusable interval {interval!r}: {exc}") from exc
        if parsed not in SCANNER_INTERVALS:
            supported = ", ".join(i.value for i in SCANNER_INTERVALS)
            raise ScanRequestError(
                f"the scanner does not support {parsed.value!r} yet; supported: "
                f"{supported}. Single-symbol research still offers the others."
            )
        return parsed

    @staticmethod
    def _require_aware(value: datetime, label: str) -> datetime:
        if not isinstance(value, datetime):
            raise ScanRequestError(f"{label} must be a datetime")
        if value.tzinfo is None or value.utcoffset() is None:
            raise ScanRequestError(f"{label} must be timezone-aware")
        return value.astimezone(timezone.utc)


def ranked_rows(snapshot: MarketScanSnapshot) -> tuple[SymbolScanResult, ...]:
    """The assessable rows in research-inspection order.

    Results are *stored* in universe order, which keeps the execution record
    transparent and gives failures a predictable place. Presentation ordering is
    derived here through the locked ranking helper, so scan truth and display
    order stay separate concerns.
    """
    return ordered_rows(snapshot.results)


__all__ = [
    "SCANNER_INTERVALS",
    "load_universes",
    "ScanRequestError",
    "ScanProgress",
    "ProgressCallback",
    "SnapshotBuilder",
    "MarketScanner",
    "research_policy_fingerprint",
    "ranked_rows",
]
