"""The one place Phase R touches the filesystem.

The application layer opens no files (ADR 0005); like the Phase 12 ledger
store, this module is the storage adapter it persists through. It knows
nothing about any study: it is handed rendered texts and a directory and
writes them **once** (the Phase R four by default, or a later study's own
fixed set), and it reads a frozen study's artifacts back as exact text for
a later, read-only analysis. A directory that already holds any of the four
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
from typing import Mapping, Sequence

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


def _names(names: Sequence[str] | None) -> tuple[str, ...]:
    """The artifact set in force: the Phase R four unless a study names its own."""
    chosen = tuple(ARTIFACT_NAMES if names is None else names)
    if not chosen or len(set(chosen)) != len(chosen) or any(not n or "/" in n for n in chosen):
        raise ArtifactError(f"artifact names must be unique plain file names, got {list(chosen)}")
    return chosen


def existing_artifacts(directory: Path, names: Sequence[str] | None = None) -> tuple[str, ...]:
    """Which of the artifacts already exist under ``directory``."""
    directory = Path(directory)
    return tuple(name for name in _names(names) if (directory / name).exists())


def require_fresh(directory: Path, names: Sequence[str] | None = None) -> None:
    present = existing_artifacts(directory, names)
    if present:
        raise ArtifactError(
            f"{directory} already holds {list(present)}; a completed study run is not "
            "overwritten. Move it aside deliberately before running again."
        )


def write_artifacts(
    directory: Path, texts: Mapping[str, str], names: Sequence[str] | None = None
) -> dict[str, Path]:
    """Write exactly the named artifacts into ``directory`` and return their paths.

    ``texts`` must carry every artifact name and nothing else: a partial set
    would leave a directory that looks like a run and is not one. ``names``
    defaults to the Phase R four; a later study passes its own fixed set.
    """
    directory = Path(directory)
    chosen = _names(names)
    if sorted(texts) != sorted(chosen):
        raise ArtifactError(
            f"artifacts must be exactly {list(chosen)}, got {list(texts)}"
        )
    for name, text in texts.items():
        if not isinstance(text, str):
            raise ArtifactError(f"{name}: rendered artifact must be text, got {type(text).__name__}")
    require_fresh(directory, chosen)
    directory.mkdir(parents=True, exist_ok=True)
    require_fresh(directory, chosen)
    written: dict[str, Path] = {}
    for name in chosen:
        path = directory / name
        path.write_text(texts[name], encoding="utf-8", newline="")
        written[name] = path
    return written


def read_artifacts(directory: Path, names: Sequence[str]) -> dict[str, str]:
    """Read the named artifacts as exact UTF-8 text, bytes preserved.

    Read-only: the one way a later study consumes an earlier study's frozen
    output. Bytes are decoded without newline translation, so hashing the
    returned text reproduces the hash of the file on disk. A missing file is
    an error, not an empty artifact.
    """
    directory = Path(directory)
    texts: dict[str, str] = {}
    for name in _names(names):
        path = directory / name
        if not path.is_file():
            raise ArtifactError(f"{path} does not exist; a frozen source artifact cannot be inferred")
        texts[name] = path.read_bytes().decode("utf-8")
    return texts


__all__ = ["ArtifactError", "ARTIFACT_NAMES", "existing_artifacts", "require_fresh",
           "write_artifacts", "read_artifacts"]
