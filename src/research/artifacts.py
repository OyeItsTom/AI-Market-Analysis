"""The one place Phase R touches the filesystem.

The application layer opens no files (ADR 0005); like the Phase 12 ledger
store, this module is the storage adapter it persists through. It knows
nothing about the study: it is handed four rendered texts and a directory,
and it writes them **once**. A directory that already holds any of the four
artifacts is refused -- a frozen run is never overwritten by a later one;
the operator moves it aside deliberately.

Texts are written as UTF-8 with the line endings they were rendered with
(``newline=""``), so the bytes on disk are exactly the bytes whose SHA-256
the manifest records.

Not transactional. The four files are written one after another; if the
process fails part-way (disk full, permission lost), the files already
written stay where they are and nothing is rolled back. Such a directory is
then refused by the next run as an existing one, so a partial run can never
be silently completed by a later run: the operator removes it deliberately.
A manifest whose siblings are missing, or whose recorded hashes do not match
them, is what a failed run looks like.
"""

from __future__ import annotations

from pathlib import Path
from typing import Mapping

from .render import (
    ARTIFACT_MANIFEST,
    ARTIFACT_OBSERVATIONS,
    ARTIFACT_REPORT,
    ARTIFACT_SUMMARY,
)


class ArtifactError(ValueError):
    """Raised when the artifacts cannot be written as a complete, fresh set."""


#: The four files a run writes, in writing order.
ARTIFACT_NAMES: tuple[str, ...] = (
    ARTIFACT_MANIFEST, ARTIFACT_SUMMARY, ARTIFACT_OBSERVATIONS, ARTIFACT_REPORT,
)


def existing_artifacts(directory: Path) -> tuple[str, ...]:
    """Which of the four artifacts already exist under ``directory``."""
    directory = Path(directory)
    return tuple(name for name in ARTIFACT_NAMES if (directory / name).exists())


def require_fresh(directory: Path) -> None:
    present = existing_artifacts(directory)
    if present:
        raise ArtifactError(
            f"{directory} already holds {list(present)}; a completed study run is not "
            "overwritten. Move it aside deliberately before running again."
        )


def write_artifacts(directory: Path, texts: Mapping[str, str]) -> dict[str, Path]:
    """Write exactly the four artifacts into ``directory`` and return their paths.

    ``texts`` must carry every artifact name and nothing else: a partial set
    would leave a directory that looks like a run and is not one.
    """
    directory = Path(directory)
    names = tuple(texts)
    if sorted(names) != sorted(ARTIFACT_NAMES):
        raise ArtifactError(
            f"artifacts must be exactly {list(ARTIFACT_NAMES)}, got {list(names)}"
        )
    for name, text in texts.items():
        if not isinstance(text, str):
            raise ArtifactError(f"{name}: rendered artifact must be text, got {type(text).__name__}")
    require_fresh(directory)
    directory.mkdir(parents=True, exist_ok=True)
    require_fresh(directory)
    written: dict[str, Path] = {}
    for name in ARTIFACT_NAMES:
        path = directory / name
        path.write_text(texts[name], encoding="utf-8", newline="")
        written[name] = path
    return written


__all__ = ["ArtifactError", "ARTIFACT_NAMES", "existing_artifacts", "require_fresh", "write_artifacts"]
