"""Headless Phase 12 outcome collection: one finite refresh, one report, exit.

    python -m src.cli.outcome_refresh SPY QQQ --interval 1d [--outcome-root PATH]

The dashboard and this command are two callers of one application path::

    default_provider() -> build_snapshot(...) -> build_outcome_ledger(...)
                       -> refresh_outcomes(snapshot, OUTCOME_SPECS, ledger,
                                           now=snapshot.built_at)

Nothing is decided here. The history window, the settled-bars-only fetch,
the tracked horizons, artifact identity, ledger idempotency and every
measurement are the application's and Phase 12's, exactly as when Refresh
is pressed; this module chooses which symbols and which interval, in what
order, and how the result is printed.

One invocation, one interval, a few explicit symbols
----------------------------------------------------
Symbols are processed sequentially in command-line order, each in its own
ledger partition. A failure on one symbol is reported and the next symbol
is still attempted; the process then exits ``1``. Nothing is rolled back:
a refresh is a sequence of independent durable appends, not a transaction,
and every append that completed before a failure stays (see
:mod:`src.application.outcomes`). Running the command again is safe -- the
same settled tail produces the same keys, which the ledger reports as
``DUPLICATE`` / ``PRESENT`` rather than storing twice.

A snapshot with **no settled bars** is treated as a failure here even
though the application returns it as a fact: a scheduled collector that
succeeded forever on a mistyped or delisted symbol would register nothing
and say nothing. The dashboard's own handling is unchanged.

Clock
-----
This module reads no clock. ``build_snapshot`` reads one per snapshot and
the outcome refresh reuses that ``built_at``; ``now`` is accepted only so
tests can pin it, exactly as the dashboard's ``clock`` state does.

Output contract
---------------
One ``key=value`` line per symbol on stdout, fields in a fixed order, then
one totals line. Display names map onto existing fields as follows:

======================  ==============================================
display                 source
======================  ==============================================
``source``              ``ResearchSnapshot.source``
``built_at``            ``OutcomeRefreshResult.now`` (== ``built_at``)
``tail``                ``ResearchSnapshot.latest_bar_open``
``bars``                ``ResearchSnapshot.bar_count``
``artifacts``           ``OutcomeRefreshResult.artifacts_considered``
``artifacts_new``       ``OutcomeRefreshResult.artifacts_written``
``artifacts_duplicate`` ``OutcomeRefreshResult.artifact_duplicates``
``outcomes_new``        ``OutcomeRefreshResult.outcomes_written``
``outcomes_present``    ``OutcomeRefreshResult.outcomes_already_present``
``pending``, ``ineligible``, ``refused``, ``out_of_window``  -- same names
======================  ==============================================

A value containing whitespace, quotes or ``=`` is JSON-quoted so the line
stays parseable; newlines never appear. Stderr carries a traceback only
where the dashboard would print one: an unexpected snapshot failure, or
any failure inside the outcome refresh. A classified provider outage is
its one stdout line and nothing more.

Exit codes: ``0`` every symbol completed, ``1`` at least one failed,
``2`` usage or configuration error (argparse's own convention).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from datetime import datetime
from typing import Callable, Mapping, Sequence, TextIO

from src.application.errors import ApplicationError, FailureKind
from src.application.outcomes import (
    OUTCOME_SPECS,
    OutcomeRefreshResult,
    build_outcome_ledger,
    refresh_outcomes,
)
from src.application.snapshot import (
    SUPPORTED_INTERVALS,
    ResearchSnapshot,
    build_snapshot,
    default_provider,
)

Clock = Callable[[], datetime]

PROG = "python -m src.cli.outcome_refresh"

#: What each exit code means. Locked; nothing else is ever returned.
EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Register the current settled-bar research claims for each symbol and "
            "record the outcomes of earlier claims, then exit. One interval per "
            "invocation; symbols are processed in the order given."
        ),
    )
    parser.add_argument(
        "symbols",
        metavar="SYMBOL",
        nargs="+",
        help="one or more ticker symbols, processed in this order",
    )
    parser.add_argument(
        "--interval",
        required=True,
        choices=[interval.value for interval in SUPPORTED_INTERVALS],
        help="bar interval to refresh (exactly one per invocation)",
    )
    parser.add_argument(
        "--outcome-root",
        metavar="PATH",
        default=None,
        help=(
            "ledger directory; when omitted the application's default local "
            "ledger under the repository's data/outcomes is used"
        ),
    )
    return parser


def normalize_symbols(raw: Sequence[str]) -> tuple[str, ...]:
    """Strip and upper-case, the convention ``build_snapshot`` itself applies.

    Blank and duplicate entries are configuration errors rather than
    something to drop quietly: a scheduled command line should say exactly
    what it collects. Order is the caller's.
    """
    normalized: list[str] = []
    for value in raw:
        symbol = str(value).strip().upper()
        if not symbol:
            raise ValueError("a symbol must not be blank")
        if symbol in normalized:
            raise ValueError(f"symbol {symbol!r} is listed more than once")
        normalized.append(symbol)
    return tuple(normalized)


def _quote(value: object) -> str:
    text = " ".join(str(value).split())
    if text == "" or any(ch in text for ch in ' "\'=\\'):
        return json.dumps(text)
    return text


def format_line(fields: Mapping[str, object]) -> str:
    """``key=value`` pairs in the mapping's order; the whole contract is the order."""
    return " ".join(f"{key}={_quote(value)}" for key, value in fields.items())


def format_success(snapshot: ResearchSnapshot, result: OutcomeRefreshResult) -> str:
    tail = snapshot.latest_bar_open
    return format_line(
        {
            "symbol": snapshot.symbol,
            "interval": snapshot.interval.value,
            "status": "ok",
            "source": snapshot.source,
            "built_at": result.now.isoformat(),
            "tail": tail.isoformat() if tail is not None else "none",
            "bars": snapshot.bar_count,
            "artifacts": result.artifacts_considered,
            "artifacts_new": result.artifacts_written,
            "artifacts_duplicate": result.artifact_duplicates,
            "outcomes_new": result.outcomes_written,
            "outcomes_present": result.outcomes_already_present,
            "pending": result.pending,
            "ineligible": result.ineligible,
            "refused": result.refused,
            "out_of_window": result.out_of_window,
        }
    )


def _failure(symbol: str, interval: str, stage: str, **detail: object) -> str:
    return format_line(
        {"symbol": symbol, "interval": interval, "status": "failed", "stage": stage, **detail}
    )


def refresh_symbol(
    provider,
    symbol: str,
    interval,
    ledger,
    *,
    now: Clock | None,
    stdout: TextIO,
    stderr: TextIO,
) -> bool:
    """One symbol through the application path. Prints one line; True on success."""
    label = interval.value
    try:
        snapshot = (
            build_snapshot(provider, symbol, interval)
            if now is None
            else build_snapshot(provider, symbol, interval, now=now)
        )
    except Exception as exc:
        # As the dashboard's refresh: a classified failure is one line, and
        # only a defect (UNEXPECTED, or unclassified) sends its traceback to
        # stderr -- a provider outage in a scheduled log needs no stack.
        if isinstance(exc, ApplicationError):
            if exc.kind is FailureKind.UNEXPECTED:
                traceback.print_exc(file=stderr)
            detail = {"kind": exc.kind.value, "step": exc.step, "error": exc.message}
        else:
            traceback.print_exc(file=stderr)
            detail = {"error_type": type(exc).__name__, "error": str(exc)}
        print(_failure(symbol, label, "snapshot", **detail), file=stdout)
        return False

    if snapshot.bar_count == 0:
        print(_failure(symbol, label, "snapshot", reason="empty_snapshot"), file=stdout)
        return False

    try:
        result = refresh_outcomes(snapshot, OUTCOME_SPECS, ledger, now=snapshot.built_at)
    except Exception as exc:
        # Anything the refresh raises is a contradiction, a corruption or a
        # defect, never routine; the detail goes to stderr as the dashboard
        # sends it to the terminal.
        traceback.print_exc(file=stderr)
        print(
            _failure(symbol, label, "outcomes", error_type=type(exc).__name__, error=str(exc)),
            file=stdout,
        )
        return False

    print(format_success(snapshot, result), file=stdout)
    return True


def main(
    argv: Sequence[str] | None = None,
    *,
    provider=None,
    now: Clock | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse, refresh each symbol in order, print totals, return the exit code.

    ``provider``, ``now``, ``stdout`` and ``stderr`` are injection points for
    tests; production takes the application's default provider, the
    application's clock and the process streams.
    """
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse has already printed usage or help
        return int(exc.code or 0)

    try:
        symbols = normalize_symbols(args.symbols)
    except ValueError as exc:
        print(f"{PROG}: error: {exc}", file=stderr)
        return EXIT_USAGE
    interval = next(i for i in SUPPORTED_INTERVALS if i.value == args.interval)
    if args.outcome_root is not None and not args.outcome_root.strip():
        print(f"{PROG}: error: --outcome-root must not be blank", file=stderr)
        return EXIT_USAGE

    if provider is None:
        provider = default_provider()
    # ``None`` is passed through so the application resolves its default root
    # at call time; the CLI never names the location.
    ledger = build_outcome_ledger(args.outcome_root)

    succeeded = 0
    for symbol in symbols:
        if refresh_symbol(provider, symbol, interval, ledger, now=now, stdout=stdout, stderr=stderr):
            succeeded += 1
    failed = len(symbols) - succeeded
    print(format_line({"symbols": len(symbols), "ok": succeeded, "failed": failed}), file=stdout)
    return EXIT_OK if failed == 0 else EXIT_FAILED


__all__ = ["main", "build_parser", "normalize_symbols", "format_line", "format_success",
           "refresh_symbol", "EXIT_OK", "EXIT_FAILED", "EXIT_USAGE"]


if __name__ == "__main__":
    raise SystemExit(main())
