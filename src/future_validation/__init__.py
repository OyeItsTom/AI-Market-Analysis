"""FUTURE_VALIDATION_V1 storage: frozen input snapshots and write-once artifacts.

The research question lives in :mod:`src.research.future_validation` and the
pure computation in :mod:`src.research.future_validation_engine`; this
package only reads the collection's evidence under its lock and writes the
validation's own write-once files. See ``docs/research/future_validation_v1.md``.
"""

from .store import (
    MATCH_EXACT,
    MATCH_PREFIX,
    REPORT_NAME,
    RESULT_NAME,
    UNLOCK_NAME,
    VALIDATION_DIR,
    ArtifactExists,
    InputSnapshot,
    RootMissing,
    SnapshotFile,
    SnapshotMismatch,
    UnsupportedEntry,
    ValidationArtifacts,
    ValidationStoreError,
    capture,
    materialize,
    recapture,
)

__all__ = [
    "MATCH_EXACT",
    "MATCH_PREFIX",
    "REPORT_NAME",
    "RESULT_NAME",
    "UNLOCK_NAME",
    "VALIDATION_DIR",
    "ArtifactExists",
    "InputSnapshot",
    "RootMissing",
    "SnapshotFile",
    "SnapshotMismatch",
    "UnsupportedEntry",
    "ValidationArtifacts",
    "ValidationStoreError",
    "capture",
    "materialize",
    "recapture",
]
