"""Application-facing error taxonomy for the dashboard.

The dashboard has to answer one question about every failure: *is this a
research outcome the user should read, or a fault the user should be told
about?* Phases 1-6 already draw that line -- ``INSUFFICIENT_DATA`` is a
legitimate research state while a symbol mismatch raises -- and this module
preserves it rather than flattening everything into "something went wrong".

Nothing here contains research logic. It classifies exceptions raised by the
domain and provider so the UI can style them correctly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ApplicationError(RuntimeError):
    """Raised when the application layer cannot complete a request.

    Carries a :class:`FailureKind` so the UI can distinguish a provider outage
    from a malformed request without parsing message text.
    """

    def __init__(self, kind: "FailureKind", step: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.step = step
        self.message = message


class FailureKind(str, Enum):
    """Why a refresh or action failed.

    ``UNEXPECTED`` exists so a genuine bug is never disguised as an ordinary
    provider hiccup. The UI shows a generic banner for it and sends the
    traceback to the terminal.
    """

    PROVIDER = "provider"
    DATA_QUALITY = "data_quality"
    REQUEST = "request"
    DOMAIN = "domain"
    UNEXPECTED = "unexpected"

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self.value


#: How each kind is described to a human. Deliberately plain: a beginner
#: should learn what to do next, not what exception class was raised.
_KIND_GUIDANCE: dict[FailureKind, str] = {
    FailureKind.PROVIDER: "The market-data source could not be reached or refused the request.",
    FailureKind.DATA_QUALITY: "The market data that came back did not pass validation.",
    FailureKind.REQUEST: "The request itself was not valid.",
    FailureKind.DOMAIN: "The research inputs were structurally inconsistent.",
    FailureKind.UNEXPECTED: "Something went wrong inside the dashboard.",
}


@dataclass(frozen=True)
class FailureReport:
    """A failure rendered for display, with the technical detail kept aside.

    ``detail`` is shown; ``traceback_text`` is not -- it goes to the terminal.
    Exposing a raw traceback in the UI teaches a beginner nothing and hides
    the one sentence that matters.
    """

    kind: FailureKind
    step: str
    detail: str

    @property
    def guidance(self) -> str:
        return _KIND_GUIDANCE[self.kind]

    @property
    def headline(self) -> str:
        return f"Refresh failed at {self.step}"

    @property
    def is_bug(self) -> bool:
        """True when this indicates a defect rather than an external condition."""
        return self.kind in (FailureKind.DOMAIN, FailureKind.UNEXPECTED)


def classify(exc: BaseException, step: str) -> ApplicationError:
    """Map a domain/provider exception onto the application taxonomy.

    Imports the concrete error types lazily so this module stays importable
    even while the domain packages are being changed, and so the mapping is
    expressed in one place instead of scattered through the UI.
    """
    from src.data.provider import ProviderError
    from src.data.validation import ValidationError

    if isinstance(exc, ApplicationError):
        return exc
    if isinstance(exc, ValidationError):
        return ApplicationError(FailureKind.DATA_QUALITY, step, str(exc))
    if isinstance(exc, ProviderError):
        return ApplicationError(FailureKind.PROVIDER, step, str(exc))

    # Domain records raise ValueError subclasses for structural problems
    # (IntentError, PolicyError, AssessmentError, EvidenceError, ...). A bare
    # ValueError from a malformed request is the caller's fault; a domain
    # subclass means the inputs were inconsistent, which is closer to a bug.
    if isinstance(exc, ValueError):
        kind = FailureKind.REQUEST if type(exc) is ValueError else FailureKind.DOMAIN
        return ApplicationError(kind, step, str(exc))

    return ApplicationError(FailureKind.UNEXPECTED, step, f"{type(exc).__name__}: {exc}")


__all__ = ["ApplicationError", "FailureKind", "FailureReport", "classify"]
