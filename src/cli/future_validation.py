"""FUTURE_VALIDATION_V1: blind status, and the one explicit run.

    python -m src.cli.future_validation status
    python -m src.cli.future_validation run

Nothing is a flag. The symbols, hypothesis, state, horizon, benchmark,
thresholds, minimum episodes, cutoff rule, metrics and root are the frozen
``FUTURE_VALIDATION_V1`` and the prospective collection's own root; tests
inject a temporary root, a clock and test definitions through :func:`main`'s
keyword arguments, never through the command line.

``status`` is Level 1 and reads no clock: identities, provenance status, the
evidence clock (the settlement time of the latest legitimate claim bar), the
stop-rule due dates and per-symbol matured-claim counts, and whether an unlock or a result
exists -- never a state, a price, a return, a sign, an episode count or a
category. ``run`` writes the unlock once, then the result and the report
once, and prints the per-symbol categories; it refuses, writing nothing,
until the stop rule is met with valid provenance.

Exit codes: ``0`` status printed / run completed (now or earlier); ``1``
status found the evidence invalid or unknown; ``2`` usage error or a run
refusal.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from typing import Callable, Sequence, TextIO

from src.application.future_validation import RunReport, StatusReport, run, status
from src.application.prospective import build_prospective_store, default_repository_probe
from src.cli.outcome_refresh import format_line

Clock = Callable[[], datetime]

PROG = "python -m src.cli.future_validation"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_REFUSED = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "FUTURE_VALIDATION_V1 over the frozen prospective collection. No research "
            "parameter and no location can be changed from the command line."
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")
    commands.add_parser("status", help="blind Level-1 status and stop-rule readiness")
    commands.add_parser("run", help="the one explicit unlock and analysis (write-once)")
    return parser


def _time(value: datetime | None) -> str:
    return "none" if value is None else value.isoformat()


def _flag(value: bool | None) -> str:
    return "none" if value is None else ("yes" if value else "no")


def format_status(report: StatusReport) -> list[str]:
    lines = [format_line({
        "validation_id": report.validation_id,
        "validation_fingerprint": report.validation_fingerprint,
        "definition_identity": report.definition_identity,
        "activation": report.activation,
        "integrity": report.integrity,
        "identity_mismatches": ",".join(report.identity_mismatches) or "none",
        "provenance": report.provenance_status,
        "provenance_reasons": ",".join(f"{reason}:{count}" for reason, count
                                       in report.provenance_reasons) or "none",
        "excluded_artifact_keys": report.excluded_artifact_keys,
        "excluded_outcome_keys": report.excluded_outcome_keys,
        "validity": report.validity,
    })]
    lines.append(format_line({
        "activated_at": _time(report.activated_at),
        "evidence_through": _time(report.evidence_through),
        "e1_due": _time(report.e1_due),
        "e1_met": _flag(report.e1_met),
        "forced_due": _time(report.forced_due),
        "f_met": _flag(report.f_met),
    }))
    for symbol, count in report.e2_counts:
        lines.append(format_line({"symbol": symbol, "matured_eligible_h20_claims": count,
                                  "e2_minimum": report.e2_minimum}))
    lines.append(format_line({
        "e2_met": _flag(report.e2_met),
        "unlockable": _flag(report.unlockable),
        "unlock_exists": _flag(report.unlock_exists),
        "result_exists": _flag(report.result_exists),
    }))
    return lines


def status_exit_code(report: StatusReport) -> int:
    if report.activation == "collect_in_progress":
        return EXIT_REFUSED
    if report.activation == "not_activated":
        return EXIT_OK
    return EXIT_OK if report.validity == "ok" else EXIT_FAILED


def format_run(report: RunReport) -> list[str]:
    fields: dict[str, object] = {"run": report.outcome}
    if report.detail:
        fields["detail"] = ",".join(report.detail)
    if report.unlock_sha256 is not None:
        fields["unlock_sha256"] = report.unlock_sha256
    if report.result_sha256 is not None:
        fields["result_sha256"] = report.result_sha256
    lines = [format_line(fields)]
    for symbol, category in report.categories:
        lines.append(format_line({"symbol": symbol, "category": category}))
    return lines


def main(
    argv: Sequence[str] | None = None,
    *,
    root=None,
    now: Clock | None = None,
    repository=None,
    definition=None,
    pinned_fingerprint: str | None = None,
    collection=None,
    stdout: TextIO | None = None,
) -> int:
    """Parse and run one command. Keyword arguments are test injection points only."""
    stdout = sys.stdout if stdout is None else stdout
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse has already printed usage or help
        return int(exc.code or 0)

    store = build_prospective_store(root)
    kwargs: dict[str, object] = {}
    for name, value in (("definition", definition),
                        ("pinned_fingerprint", pinned_fingerprint), ("collection", collection)):
        if value is not None:
            kwargs[name] = value
    if args.command == "status":
        report = status(store, **kwargs)
        for line in format_status(report):
            print(line, file=stdout)
        return status_exit_code(report)
    if now is not None:  # host metadata only; E1 and F use the evidence clock
        kwargs["now"] = now
    outcome = run(store, repository=(repository if repository is not None
                                     else default_repository_probe()), **kwargs)
    for line in format_run(outcome):
        print(line, file=stdout)
    return EXIT_OK if outcome.completed else EXIT_REFUSED


__all__ = ["main", "build_parser", "format_status", "format_run", "status_exit_code",
           "EXIT_OK", "EXIT_FAILED", "EXIT_REFUSED"]


if __name__ == "__main__":
    raise SystemExit(main())
