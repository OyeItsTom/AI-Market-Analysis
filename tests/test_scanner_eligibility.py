"""Phase 10 eligibility, pinned against the real ``build_snapshot`` contract.

Every case below is driven through the actual function with the repository's own
provider double, because the contract is not what it looks like from the source:
insufficient history does **not** raise, and a 50-bar series is already
assessable even though ``WARMUP_BARS`` is 51. A rule derived from reading rather
than running would have been wrong in both places.
"""

from __future__ import annotations

import pytest

from src.application.errors import ApplicationError, FailureKind
from src.application.snapshot import (
    MINIMUM_SUFFICIENT_OBSERVATIONS,
    WARMUP_BARS,
    build_snapshot,
)
from src.assessments.assessment import AssessmentState
from src.data.models import Interval
from src.data.provider import ProviderUnavailableError
from src.scanner.eligibility import eligibility_for, error_for
from src.scanner.models import EligibilityStatus, ScanErrorCode
from tests.test_application_snapshot import RecordingProvider


class Broken(RecordingProvider):
    def __init__(self, exc):
        self.exc = exc
        super().__init__(1)

    def get_bars(self, *args, **kwargs):
        raise self.exc


class WrongSymbol(RecordingProvider):
    def get_bars(self, symbol, *args, **kwargs):
        return super().get_bars("MSFT", *args, **kwargs)


def snapshot_for(bar_count: int):
    return build_snapshot(RecordingProvider(bar_count), "AAPL", Interval.DAY_1)


# -- the measured contract -----------------------------------------------


def test_no_bars_is_no_data():
    assert eligibility_for(snapshot_for(0)) is EligibilityStatus.NO_DATA


@pytest.mark.parametrize("bars", [1, 5, 10, 25])
def test_too_few_classifying_hypotheses_is_insufficient_evidence(bars):
    snapshot = snapshot_for(bars)
    assert snapshot.assessment.state is AssessmentState.INSUFFICIENT_DATA
    assert eligibility_for(snapshot) is EligibilityStatus.INSUFFICIENT_EVIDENCE


def test_fifty_bars_is_already_eligible():
    """The regression this module exists to prevent.

    ``WARMUP_BARS`` is 51, but only ``MINIMUM_SUFFICIENT_OBSERVATIONS`` (2) of
    the three hypotheses need to classify. A rule of ``bar_count < WARMUP_BARS``
    would discard this perfectly assessable symbol.
    """
    snapshot = snapshot_for(WARMUP_BARS - 1)
    assert snapshot.bar_count == 50
    assert snapshot.assessment.state is not AssessmentState.INSUFFICIENT_DATA
    assert eligibility_for(snapshot) is EligibilityStatus.ELIGIBLE


@pytest.mark.parametrize("bars", [WARMUP_BARS, 100, 300])
def test_ample_history_is_eligible(bars):
    assert eligibility_for(snapshot_for(bars)) is EligibilityStatus.ELIGIBLE


def test_eligibility_never_consults_bar_count():
    """Asserted structurally: there is no bar-count comparison to regress to."""
    import ast
    import pathlib

    source = pathlib.Path("src/scanner/eligibility.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "bar_count" not in names
    assert "WARMUP_BARS" not in {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }


def test_an_absent_assessment_attribute_is_treated_as_no_data():
    class Bare:
        assessment = None

    assert eligibility_for(Bare()) is EligibilityStatus.NO_DATA


# -- operational errors --------------------------------------------------


@pytest.mark.parametrize(
    "kind, expected",
    [
        (FailureKind.PROVIDER, ScanErrorCode.PROVIDER_UNAVAILABLE),
        (FailureKind.DATA_QUALITY, ScanErrorCode.DATA_QUALITY),
        (FailureKind.DOMAIN, ScanErrorCode.SYMBOL_MISMATCH),
        (FailureKind.REQUEST, ScanErrorCode.REQUEST_INVALID),
        (FailureKind.UNEXPECTED, ScanErrorCode.UNEXPECTED),
    ],
)
def test_every_failure_kind_maps_to_its_own_code(kind, expected):
    assert error_for(ApplicationError(kind, "step", "message")) is expected


def test_every_failure_kind_is_covered():
    for kind in FailureKind:
        assert error_for(ApplicationError(kind, "s", "m")) in ScanErrorCode


def test_a_provider_outage_raises_and_maps_to_provider_unavailable():
    with pytest.raises(ApplicationError) as caught:
        build_snapshot(Broken(ProviderUnavailableError("down")), "AAPL", Interval.DAY_1)
    assert caught.value.kind is FailureKind.PROVIDER
    assert error_for(caught.value) is ScanErrorCode.PROVIDER_UNAVAILABLE


def test_a_provider_returning_another_symbol_maps_to_symbol_mismatch():
    """Measured: this raises `domain`, not `unexpected`."""
    with pytest.raises(ApplicationError) as caught:
        build_snapshot(WrongSymbol(80), "AAPL", Interval.DAY_1)
    assert caught.value.kind is FailureKind.DOMAIN
    assert error_for(caught.value) is ScanErrorCode.SYMBOL_MISMATCH


def test_an_unforeseen_failure_kind_degrades_rather_than_raising():
    class Odd:
        kind = "something-new"

    assert error_for(Odd()) is ScanErrorCode.UNEXPECTED


def test_the_locked_thresholds_are_unchanged():
    assert WARMUP_BARS == 51
    assert MINIMUM_SUFFICIENT_OBSERVATIONS == 2
