"""Transport state for one configured feed. Not an item cursor.

RSS and Atom have no pagination, no offset and no monotonic item ids -- a feed
document is simply the publisher's current window. So there is deliberately
**no** ``last_seen_ids`` and no cursor here: remembering which ids were seen
would make a later correction to an already-seen entry invisible, and losing a
correction is exactly the kind of silent history damage this project refuses.

What is stored is HTTP cache metadata: an ETag and a Last-Modified value, which
let a refresh ask "has this changed?" cheaply. That is a transport optimisation
and nothing more. A ``304`` means the source says its representation is
unchanged; it is not evidence about the world and it creates no records.

Two rules keep this state from ever costing data:

* it is written **only after** the records from that response are fsynced, so it
  can never point past durable data;
* it is keyed to an endpoint fingerprint, so validators from one URL are never
  replayed against another.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import FeedError, require_aware, require_source_id
from .store import DEFAULT_FEEDS_ROOT

CHECKPOINT_FILE = "checkpoint.json"
CHECKPOINT_SCHEMA_VERSION = 1


class CheckpointError(FeedError):
    """Raised when checkpoint state cannot be written."""


@dataclass(frozen=True)
class Checkpoint:
    """Cached transport validators for one endpoint."""

    source_id: str
    endpoint_fingerprint: str
    etag: str | None = None
    last_modified: str | None = None
    last_success_at: datetime | None = None
    schema_version: int = CHECKPOINT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        set_ = object.__setattr__
        set_(self, "source_id", require_source_id(self.source_id))
        if self.last_success_at is not None:
            set_(self, "last_success_at",
                 require_aware(self.last_success_at, "last_success_at"))

    def validators_for(self, endpoint_fingerprint: str) -> tuple[str | None, str | None]:
        """Validators, but only for the endpoint they were obtained from.

        A changed URL or feed type yields a different fingerprint and therefore
        ``(None, None)``, forcing an unconditional fetch. Sending one endpoint's
        ETag to another could produce a ``304`` that means nothing.
        """
        if endpoint_fingerprint != self.endpoint_fingerprint:
            return (None, None)
        return (self.etag, self.last_modified)


@dataclass(frozen=True)
class CheckpointLoad:
    """A checkpoint read attempt, plus why it may be unusable."""

    checkpoint: Checkpoint | None
    warning: str = ""

    @property
    def has_warning(self) -> bool:
        return bool(self.warning)


class CheckpointStore:
    """Reads and writes ``checkpoint.json`` for each source."""

    def __init__(self, root: str | Path = DEFAULT_FEEDS_ROOT) -> None:
        self._root = Path(root)

    def path_for(self, source_id: str) -> Path:
        return self._root / require_source_id(source_id) / CHECKPOINT_FILE

    def load(self, source_id: str, *, endpoint_fingerprint: str) -> CheckpointLoad:
        """Read the checkpoint, reporting rather than raising when it is unusable.

        Every failure here degrades to an unconditional bounded refresh, which
        is always safe: the worst outcome is re-fetching a document whose entries
        then classify as duplicates. The file is **not** deleted -- a warning is
        surfaced and it is overwritten only after a successful durable refresh.
        """
        path = self.path_for(source_id)
        if not path.is_file():
            return CheckpointLoad(None)
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            return CheckpointLoad(
                None,
                f"checkpoint for {source_id!r} is unreadable ({type(exc).__name__}); "
                "fetching unconditionally and leaving the file in place",
            )
        if not isinstance(payload, dict):
            return CheckpointLoad(None, f"checkpoint for {source_id!r} is not an object")
        version = payload.get("schema_version")
        if version != CHECKPOINT_SCHEMA_VERSION:
            return CheckpointLoad(
                None,
                f"checkpoint for {source_id!r} declares schema_version {version!r}; "
                f"this build understands {CHECKPOINT_SCHEMA_VERSION}, so it was ignored",
            )
        try:
            checkpoint = Checkpoint(
                source_id=payload["source_id"],
                endpoint_fingerprint=payload.get("endpoint_fingerprint", ""),
                etag=payload.get("etag"),
                last_modified=payload.get("last_modified"),
                last_success_at=(
                    datetime.fromisoformat(payload["last_success_at"])
                    if payload.get("last_success_at") else None
                ),
            )
        except Exception as exc:
            return CheckpointLoad(
                None, f"checkpoint for {source_id!r} is malformed ({exc})"
            )

        if checkpoint.endpoint_fingerprint != endpoint_fingerprint:
            return CheckpointLoad(
                None,
                f"the endpoint for {source_id!r} changed since its validators were "
                "stored; fetching unconditionally",
            )
        return CheckpointLoad(checkpoint)

    def save(self, checkpoint: Checkpoint) -> Path:
        """Write durably: temp file, fsync, atomic rename, best-effort dir fsync.

        ``os.replace`` is atomic on POSIX, which is what makes a half-written
        checkpoint unobservable. No cross-platform crash guarantee is claimed.
        """
        path = self.path_for(checkpoint.source_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": CHECKPOINT_SCHEMA_VERSION,
            "source_id": checkpoint.source_id,
            "endpoint_fingerprint": checkpoint.endpoint_fingerprint,
            "etag": checkpoint.etag,
            "last_modified": checkpoint.last_modified,
            "last_success_at": (
                checkpoint.last_success_at.isoformat()
                if checkpoint.last_success_at else None
            ),
        }
        temp = path.with_suffix(".json.tmp")
        try:
            with temp.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
            _fsync_directory(path.parent)
        except OSError as exc:
            raise CheckpointError(f"could not write checkpoint: {exc}") from exc
        finally:
            if temp.exists():  # pragma: no cover - only after a failed replace
                try:
                    temp.unlink()
                except OSError:
                    pass
        return path


def _fsync_directory(directory: Path) -> None:
    """Best effort: not every platform permits fsync on a directory."""
    try:
        fd = os.open(directory, os.O_RDONLY)
    except OSError:  # pragma: no cover - platform dependent
        return
    try:
        os.fsync(fd)
    except OSError:  # pragma: no cover - platform dependent
        pass
    finally:
        os.close(fd)


__all__ = [
    "CHECKPOINT_FILE",
    "CHECKPOINT_SCHEMA_VERSION",
    "CheckpointError",
    "Checkpoint",
    "CheckpointLoad",
    "CheckpointStore",
]
