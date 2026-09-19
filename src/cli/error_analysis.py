"""Run Error Analysis v1 once against the frozen Baseline Study v1 artifacts, print, exit.

    python -m src.cli.error_analysis --git-commit <SHA> [--source DIR] [--out DIR]

One application path, one call::

    run_error_analysis_study(git_commit=..., source_root=..., out_root=...)

Nothing is decided here. The source contract (pinned hashes), the segments,
the asset-class map, the diagnostics and the metrics are the frozen
definition; this command has **no flag for any of them**. ``--source`` and
``--out`` are operational locations, and the source is accepted only if its
bytes are the frozen ones. No provider exists on this path: the command
reads three files and writes four.

Output contract
---------------
One ``key=value`` line naming the verified source (hashes), then one
``study=...`` line with the output directory and the artifact hashes. On
failure, one ``status=failed`` line; a traceback goes to stderr only for an
unexpected error.

Exit codes: ``0`` the four artifacts were written, ``1`` the analysis did not
complete, ``2`` usage or configuration error.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from typing import Callable, Sequence, TextIO

from src.application.error_analysis import (
    ERROR_ANALYSIS_LABEL,
    ErrorAnalysisRun,
    run_error_analysis_study,
)
from src.application.errors import ApplicationError, FailureKind
from src.application.study import validate_git_commit
from src.cli.outcome_refresh import format_line

Clock = Callable[[], datetime]

PROG = "python -m src.cli.error_analysis"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Run the frozen Error Analysis v1 over the frozen Baseline Study v1 artifacts and "
            "write manifest.json, diagnostics.csv, episodes.csv and report.md. No research "
            "parameter can be changed from the command line and no market data is fetched."
        ),
    )
    parser.add_argument(
        "--git-commit", required=True, metavar="SHA",
        help="full 40-hex commit SHA of the methodology this run executes; recorded verbatim",
    )
    parser.add_argument(
        "--source", metavar="DIR", default=None,
        help="directory holding the frozen Baseline Study v1 artifacts (default: the study's "
             "own output directory under data/research); accepted only if the bytes match",
    )
    parser.add_argument(
        "--out", metavar="DIR", default=None,
        help="root directory for generated artifacts (default: the application's data/research)",
    )
    return parser


def format_source(run: ErrorAnalysisRun) -> str:
    fields = {"source": str(run.source_dir), "status": "verified"}
    for name, digest in run.source_sha256.items():
        fields[f"sha256_{name.replace('.', '_')}"] = digest
    fields["observation_rows"] = run.result.observation_rows
    fields["summary_rows_checked"] = run.result.source_rows_checked
    return format_line(fields)


def format_study(run: ErrorAnalysisRun) -> str:
    fields = {
        "study": run.definition.label,
        "status": "ok",
        "git_commit": run.git_commit,
        "study_fingerprint": run.definition.fingerprint,
        "generated_at": run.generated_at.isoformat(),
        "episodes": len(run.result.episodes),
        "diagnostic_rows": len(run.result.diagnostics),
        "out": str(run.output_dir),
    }
    for name, digest in run.artifact_sha256.items():
        fields[f"sha256_{name.replace('.', '_')}"] = digest
    return format_line(fields)


def _failure(stage: str, **detail: object) -> str:
    return format_line({"study": ERROR_ANALYSIS_LABEL, "status": "failed", "stage": stage, **detail})


def main(
    argv: Sequence[str] | None = None,
    *,
    now: Clock | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse, run the analysis once, print, return the exit code."""
    stdout = sys.stdout if stdout is None else stdout
    stderr = sys.stderr if stderr is None else stderr

    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse has already printed usage or help
        return int(exc.code or 0)

    try:
        git_commit = validate_git_commit(args.git_commit)
    except ValueError as exc:
        print(f"{PROG}: error: {exc}", file=stderr)
        return EXIT_USAGE
    for flag, value in (("--source", args.source), ("--out", args.out)):
        if value is not None and not value.strip():
            print(f"{PROG}: error: {flag} must not be blank", file=stderr)
            return EXIT_USAGE

    try:
        kwargs = {"git_commit": git_commit, "source_root": args.source, "out_root": args.out}
        run = run_error_analysis_study(**kwargs) if now is None else run_error_analysis_study(**kwargs, now=now)
    except Exception as exc:
        if isinstance(exc, ApplicationError):
            if exc.kind is FailureKind.UNEXPECTED:
                traceback.print_exc(file=stderr)
            detail = {"kind": exc.kind.value, "step": exc.step, "error": exc.message}
            stage = exc.step
        else:
            traceback.print_exc(file=stderr)
            detail = {"error_type": type(exc).__name__, "error": str(exc)}
            stage = "analysis"
        print(_failure(stage, **detail), file=stdout)
        return EXIT_FAILED

    print(format_source(run), file=stdout)
    print(format_study(run), file=stdout)
    return EXIT_OK


__all__ = ["main", "build_parser", "format_source", "format_study",
           "EXIT_OK", "EXIT_FAILED", "EXIT_USAGE"]


if __name__ == "__main__":
    raise SystemExit(main())
