"""Prospective Collection v1: activate once, collect in the ET window, report health blind.

    python -m src.cli.prospective activate --collector-git-commit SHA --m2-preregistration-git-commit SHA
    python -m src.cli.prospective collect
    python -m src.cli.prospective health

Nothing research-related is a flag. The universe, interval, basis,
hypotheses, horizons, root and collection window are the frozen
``COLLECTION_V1`` and the application's own root (``data/prospective/v1``);
tests inject a temporary root and fakes through :func:`main`'s keyword
arguments, never through the command line.

``activate`` makes no provider call and creates no claim; it writes the
activation manifest once. ``collect`` refuses outside 00:30-09:00
America/New_York before any provider exists. ``health`` is offline and
read-only. Every line is ``key=value`` and Level 1: identities, clocks,
counts, bar timestamps and status classes -- never a price, a return or a
research state, and never an exception message (a message can quote a
value; only class names are printed).

Exit codes: ``0`` done; ``1`` a collection completed with at least one
symbol not collected, or health found a problem; ``2`` usage error or a
refusal (not activated, locked, outside the window, configuration
mismatch, activation refused).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Callable, Mapping, Sequence, TextIO

from src.application.prospective import (
    ActivationRefused,
    CollectionReport,
    HealthReport,
    activate,
    build_prospective_store,
    collect,
    current_dependency_versions,
    default_repository_probe,
    health,
)
from src.cli.outcome_refresh import format_line

Clock = Callable[[], datetime]

PROG = "python -m src.cli.prospective"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Prospective Collection v1 over the frozen universe. No research parameter "
            "and no location can be changed from the command line."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    activation = commands.add_parser(
        "activate",
        help="write the activation manifest once (no network, no claim)",
    )
    activation.add_argument("--collector-git-commit", required=True, metavar="SHA",
                            help="full 40-hex SHA that HEAD must equal")
    activation.add_argument("--m2-preregistration-git-commit", required=True, metavar="SHA",
                            help="full 40-hex SHA of the frozen M2 pre-registration")
    commands.add_parser("collect", help="one collection run inside 00:30-09:00 ET")
    commands.add_parser("health", help="offline, read-only Level-1 health report")
    return parser


def _time(value: datetime | None) -> str:
    return "none" if value is None else value.isoformat()


# -- activate --------------------------------------------------------------------------------


def _run_activate(args, store, *, repository, versions, now, stdout, stderr) -> int:
    kwargs = {} if now is None else {"now": now}
    try:
        manifest = activate(
            store,
            collector_git_commit=args.collector_git_commit,
            m2_preregistration_git_commit=args.m2_preregistration_git_commit,
            repository=repository if repository is not None else default_repository_probe(),
            versions=versions if versions is not None else current_dependency_versions(),
            **kwargs,
        )
    except ActivationRefused as exc:
        print(format_line({"activation": "refused", "reason": exc.reason}), file=stdout)
        print(f"{PROG}: activation refused: {exc}", file=stderr)
        return EXIT_REFUSED
    print(format_line({
        "activation": "written",
        "activated_at": _time(manifest.activated_at),
        "collection_id": manifest.collection_id,
        "collection_fingerprint": manifest.collection_fingerprint,
        "collector_git_commit": manifest.collector_git_commit,
        "m2_preregistration_git_commit": manifest.m2_preregistration_git_commit,
    }), file=stdout)
    return EXIT_OK


# -- collect ---------------------------------------------------------------------------------


def format_symbol_run(entry) -> str:
    fields: dict[str, object] = {
        "symbol": entry.symbol,
        "status": entry.status.value,
        "stage": entry.stage,
    }
    if entry.error_class is not None:
        fields["error_class"] = entry.error_class
    for name in ("built_at", "tail"):
        value = getattr(entry, name)
        if value is not None:
            fields[name] = value.isoformat()
    for name in entry.COUNTS:
        value = getattr(entry, name)
        if value is not None:
            fields[name] = value
    fields["missed_tails"] = len(entry.missed_tails)
    return format_line(fields)


def _run_collect(store, *, provider_factory, now, run_id_factory, stdout) -> int:
    kwargs: dict[str, object] = {}
    if provider_factory is not None:
        kwargs["provider_factory"] = provider_factory
    if now is not None:
        kwargs["now"] = now
    if run_id_factory is not None:
        kwargs["run_id_factory"] = run_id_factory
    report: CollectionReport = collect(store, **kwargs)
    record = report.record
    if record is None:
        print(format_line({"collect": "refused", "reason": report.outcome}), file=stdout)
        return EXIT_REFUSED
    for entry in record.symbols:
        print(format_symbol_run(entry), file=stdout)
    print(format_line({
        "run_status": record.run_status.value,
        "run_id": record.run_id,
        "started_at": _time(record.started_at),
        "finished_at": _time(record.finished_at),
        "symbols": record.symbols_attempted,
        "ok": record.symbols_ok,
        "pre_activation": record.symbols_pre_activation,
        "failed": record.symbols_failed,
    }), file=stdout)
    if report.outcome != "completed":
        return EXIT_REFUSED
    return EXIT_OK if record.symbols_failed == 0 else EXIT_FAILED


# -- health ----------------------------------------------------------------------------------


def format_health(report: HealthReport) -> list[str]:
    def flag(value: bool | None) -> str:
        return "none" if value is None else ("yes" if value else "no")

    lines = [format_line({
        "prospective_status": report.status,
        "root_exists": flag(report.root_exists),
        "ledger_exists": flag(report.ledger_exists),
        "collection_id": report.collection_id,
        "collection_fingerprint": report.collection_fingerprint,
        "manifest_fingerprint_match": flag(report.manifest_fingerprint_match),
        "live_configuration_match": flag(report.live_configuration_match),
        "activated_at": _time(report.activated_at),
        "collector_git_commit": report.collector_git_commit or "none",
        "m2_preregistration_git_commit": report.m2_preregistration_git_commit or "none",
        "universe": ",".join(report.universe),
        "interval": report.interval,
        "basis": report.basis,
    })]
    for entry in report.symbols:
        fields: dict[str, object] = {"symbol": entry.symbol,
                                     "readable": flag(entry.readable)}
        if entry.readable:
            fields.update({
                "claims_total": entry.claims_total,
                "tails_registered": entry.tails_registered,
                "claims_evaluable": entry.claims_evaluable,
                "claims_insufficient": entry.claims_insufficient,
            })
            for horizon, count in entry.outcomes_matured:
                fields[f"outcomes_matured_h{horizon}"] = count
            fields["pending"] = entry.pending
            fields["missed_collections"] = len(entry.missed_dates)
            fields["missed_dates"] = (",".join(day.isoformat() for day in entry.missed_dates)
                                      or "none")
            fields["last_tail"] = _time(entry.last_tail)
        lines.append(format_line(fields))
    if report.activated_at is not None:
        lines.append(format_line({
            "runs_total": report.runs_total,
            "runs_completed": report.runs_completed,
            "runs_outside_window": report.runs_outside_window,
            "runs_config_mismatch": report.runs_config_mismatch,
            "last_run": _time(report.last_run),
            "last_success": _time(report.last_success),
            "symbol_statuses": ",".join(f"{name}:{count}" for name, count
                                        in report.status_counts) or "none",
        }))
    integrity: dict[str, object] = {"integrity": report.integrity}
    if report.corrupt_component is not None:
        integrity["corrupt_component"] = report.corrupt_component
    if report.corrupt_line is not None:
        integrity["corrupt_line"] = report.corrupt_line
    lines.append(format_line(integrity))
    return lines


def _run_health(store, *, stdout) -> int:
    report = health(store)
    for line in format_health(report):
        print(line, file=stdout)
    return EXIT_OK if report.status in ("active", "not_activated") else EXIT_FAILED


# -- entry point -----------------------------------------------------------------------------


def main(
    argv: Sequence[str] | None = None,
    *,
    root=None,
    provider_factory=None,
    now: Clock | None = None,
    repository=None,
    versions: Mapping[str, str] | None = None,
    run_id_factory=None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse and run one command. Keyword arguments are test injection points only."""
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse has already printed usage or help
        return int(exc.code or 0)

    store = build_prospective_store(root)
    if args.command == "activate":
        return _run_activate(args, store, repository=repository, versions=versions, now=now,
                             stdout=stdout, stderr=stderr)
    if args.command == "collect":
        return _run_collect(store, provider_factory=provider_factory, now=now,
                            run_id_factory=run_id_factory, stdout=stdout)
    return _run_health(store, stdout=stdout)


__all__ = ["main", "build_parser", "format_symbol_run", "format_health",
           "EXIT_OK", "EXIT_FAILED", "EXIT_REFUSED"]


if __name__ == "__main__":
    raise SystemExit(main())
