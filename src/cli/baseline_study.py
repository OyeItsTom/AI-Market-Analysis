"""Run Baseline Study v1 once, print what was produced, exit.

    python -m src.cli.baseline_study --git-commit <SHA> [--out DIR]

One application path, one call::

    default_provider() -> run_baseline_study(provider, git_commit=..., out_root=...)

Nothing is decided here. The universe, the windows, the interval, the
basis, the horizons, the hypotheses, the metrics and the benchmark are the
frozen study definition; this command has **no flag for any of them**, by
design. An operator can choose where the artifacts land and must state
which commit the code was run from. That is all.

Output contract
---------------
One ``key=value`` line per symbol on stdout (coverage as the study counted
it), then one ``study=...`` line naming the output directory and the
artifact hashes. On failure, one ``status=failed`` line; a traceback goes
to stderr only for an unexpected error, exactly as the outcome-refresh
command treats a defect. A value containing whitespace, quotes or ``=`` is
JSON-quoted so the line stays parseable.

Exit codes: ``0`` the study ran and all four artifacts were written, ``1``
the study did not complete, ``2`` usage or configuration error.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from typing import Callable, Sequence, TextIO

from src.application.errors import ApplicationError, FailureKind
from src.application.snapshot import default_provider
from src.application.study import (
    ARTIFACT_NAMES,
    STUDY_LABEL,
    StudyRun,
    run_baseline_study,
    validate_git_commit,
)
from src.cli.outcome_refresh import format_line

Clock = Callable[[], datetime]

PROG = "python -m src.cli.baseline_study"

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description=(
            "Run the frozen Baseline Study v1 (fixed universe, windows, horizons and "
            "hypotheses) against the current market-data source and write manifest.json, "
            "summary.csv, observations.csv and report.md. No research parameter can be "
            "changed from the command line."
        ),
    )
    parser.add_argument(
        "--git-commit",
        required=True,
        metavar="SHA",
        help="full 40-hex commit SHA of the methodology this run executes; recorded verbatim",
    )
    parser.add_argument(
        "--out",
        metavar="DIR",
        default=None,
        help=(
            "root directory for generated artifacts; when omitted the application's "
            "default under the repository's data/research is used"
        ),
    )
    return parser


def format_symbol(run: StudyRun, index: int) -> str:
    symbol = run.result.symbols[index]
    return format_line(
        {
            "symbol": symbol.symbol,
            "status": "ok",
            "bars": symbol.bars_fetched,
            "warmup": symbol.warmup_bars,
            "observations": symbol.observation_bars,
            "buffer": symbol.outcome_buffer_bars,
            "first": symbol.first_timestamp.isoformat(),
            "last": symbol.last_timestamp.isoformat(),
            "fingerprint": run.bars_fingerprints[symbol.symbol],
        }
    )


def format_study(run: StudyRun) -> str:
    fields = {
        "study": run.definition.label,
        "status": "ok",
        "source": run.source,
        "git_commit": run.git_commit,
        "study_fingerprint": run.definition.fingerprint,
        "retrieved_at": run.retrieved_at.isoformat(),
        "generated_at": run.generated_at.isoformat(),
        "out": str(run.output_dir),
    }
    for name in ARTIFACT_NAMES:
        fields[f"sha256_{name.replace('.', '_')}"] = run.artifact_sha256[name]
    return format_line(fields)


def _failure(label: str, stage: str, **detail: object) -> str:
    return format_line({"study": label, "status": "failed", "stage": stage, **detail})


def main(
    argv: Sequence[str] | None = None,
    *,
    provider=None,
    now: Clock | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    """Parse, run the study once, print the report lines, return the exit code.

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
        git_commit = validate_git_commit(args.git_commit)
    except ValueError as exc:
        print(f"{PROG}: error: {exc}", file=stderr)
        return EXIT_USAGE
    if args.out is not None and not args.out.strip():
        print(f"{PROG}: error: --out must not be blank", file=stderr)
        return EXIT_USAGE

    if provider is None:
        provider = default_provider()

    label = STUDY_LABEL
    try:
        run = (
            run_baseline_study(provider, git_commit=git_commit, out_root=args.out)
            if now is None
            else run_baseline_study(provider, git_commit=git_commit, out_root=args.out, now=now)
        )
    except Exception as exc:
        if isinstance(exc, ApplicationError):
            if exc.kind is FailureKind.UNEXPECTED:
                traceback.print_exc(file=stderr)
            detail = {"kind": exc.kind.value, "step": exc.step, "error": exc.message}
            stage = exc.step
        else:
            traceback.print_exc(file=stderr)
            detail = {"error_type": type(exc).__name__, "error": str(exc)}
            stage = "study"
        print(_failure(label, stage, **detail), file=stdout)
        return EXIT_FAILED

    for index in range(len(run.result.symbols)):
        print(format_symbol(run, index), file=stdout)
    print(format_study(run), file=stdout)
    return EXIT_OK


__all__ = ["main", "build_parser", "format_symbol", "format_study",
           "EXIT_OK", "EXIT_FAILED", "EXIT_USAGE"]


if __name__ == "__main__":
    raise SystemExit(main())
