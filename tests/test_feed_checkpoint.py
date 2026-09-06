"""Phase 9 checkpoints: a transport cache, and nothing more.

The design decision under test is what the checkpoint is *not* allowed to hold.
An earlier sketch kept a set of seen item ids so refreshes could skip familiar
entries. That would have made a publisher's correction invisible, so identity
lives in the store and the checkpoint holds only ETag, Last-Modified and when
the last refresh succeeded.

It is also the subordinate half of a pair: if the store is damaged the
checkpoint must not move, and if the checkpoint is unreadable the store is still
authoritative. Losing a checkpoint costs one redundant fetch; trusting a stale
one costs records.
"""

from __future__ import annotations

import json
from dataclasses import fields as dataclass_fields
from datetime import datetime, timezone

import pytest

from src.feeds.checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    Checkpoint,
    CheckpointStore,
)
from src.feeds.models import FeedError

UTC = timezone.utc
T0 = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
FINGERPRINT = "e" * 16


def checkpoint(**overrides) -> Checkpoint:
    fields = dict(
        source_id="demo",
        endpoint_fingerprint=FINGERPRINT,
        etag='W/"abc"',
        last_modified="Sat, 05 Sep 2026 10:00:00 GMT",
        last_success_at=T0,
    )
    fields.update(overrides)
    return Checkpoint(**fields)


@pytest.fixture
def store(tmp_path):
    return CheckpointStore(tmp_path)


# -- what it must not hold -----------------------------------------------


def test_the_checkpoint_holds_no_item_identity():
    """Skipping "already seen" ids here would make corrections invisible."""
    names = {field.name for field in dataclass_fields(Checkpoint)}
    assert names == {
        "source_id", "endpoint_fingerprint", "etag", "last_modified",
        "last_success_at", "schema_version",
    }
    for forbidden in ("last_seen_ids", "seen", "ids", "items", "hashes", "cursor"):
        assert not any(forbidden in name for name in names), forbidden


def test_a_saved_checkpoint_writes_no_item_data(store):
    store.save(checkpoint())
    written = json.loads(store.path_for("demo").read_text())
    assert set(written) <= {
        "schema_version", "source_id", "endpoint_fingerprint",
        "etag", "last_modified", "last_success_at",
    }


# -- round trip ----------------------------------------------------------


def test_no_checkpoint_yet_is_not_an_error(store):
    loaded = store.load("demo", endpoint_fingerprint=FINGERPRINT)
    assert loaded.checkpoint is None
    assert not loaded.has_warning


def test_a_saved_checkpoint_comes_back(store):
    store.save(checkpoint())
    loaded = store.load("demo", endpoint_fingerprint=FINGERPRINT)
    assert loaded.checkpoint.etag == 'W/"abc"'
    assert loaded.checkpoint.last_success_at == T0


def test_validators_are_returned_for_a_matching_endpoint(store):
    store.save(checkpoint())
    loaded = store.load("demo", endpoint_fingerprint=FINGERPRINT)
    assert loaded.checkpoint.validators_for(FINGERPRINT) == (
        'W/"abc"', "Sat, 05 Sep 2026 10:00:00 GMT"
    )


def test_a_naive_timestamp_is_refused():
    with pytest.raises(FeedError):
        checkpoint(last_success_at=datetime(2026, 9, 6, 12, 0))


# -- the endpoint guard --------------------------------------------------


def test_validators_are_withheld_when_the_endpoint_changed(store):
    """An ETag from the old URL says nothing about the new one.

    The load withholds the whole checkpoint rather than merely blanking its
    validators, so there is no object left from which a caller could read a
    stale ETag by mistake.
    """
    store.save(checkpoint())
    loaded = store.load("demo", endpoint_fingerprint="0" * 16)
    assert loaded.checkpoint is None


def test_the_record_itself_also_refuses_to_hand_over_mismatched_validators():
    """Defence in depth, for a checkpoint obtained by any other route."""
    assert checkpoint().validators_for("0" * 16) == (None, None)
    assert checkpoint().validators_for(FINGERPRINT) == (
        'W/"abc"', "Sat, 05 Sep 2026 10:00:00 GMT"
    )


def test_an_endpoint_change_is_explained_rather_than_silent(store):
    store.save(checkpoint())
    loaded = store.load("demo", endpoint_fingerprint="0" * 16)
    assert loaded.has_warning
    assert "demo" in loaded.warning


def test_a_matching_endpoint_produces_no_warning(store):
    store.save(checkpoint())
    assert not store.load("demo", endpoint_fingerprint=FINGERPRINT).has_warning


# -- degradation ---------------------------------------------------------


def test_an_unreadable_checkpoint_degrades_to_a_warning(store):
    """The store is authoritative; a bad cache must not fail a refresh."""
    store.save(checkpoint())
    store.path_for("demo").write_text("{not json")
    loaded = store.load("demo", endpoint_fingerprint=FINGERPRINT)
    assert loaded.checkpoint is None
    assert loaded.has_warning


def test_a_damaged_checkpoint_file_is_never_deleted(store):
    """Nothing is destroyed to make a read succeed."""
    store.save(checkpoint())
    path = store.path_for("demo")
    path.write_text("{not json")
    before = path.read_bytes()
    store.load("demo", endpoint_fingerprint=FINGERPRINT)
    assert path.exists()
    assert path.read_bytes() == before


def test_a_future_schema_version_degrades_rather_than_being_guessed_at(store):
    store.save(checkpoint())
    path = store.path_for("demo")
    row = json.loads(path.read_text())
    row["schema_version"] = 999
    path.write_text(json.dumps(row))
    loaded = store.load("demo", endpoint_fingerprint=FINGERPRINT)
    assert loaded.checkpoint is None
    assert loaded.has_warning


@pytest.mark.parametrize("body", ["[]", '"text"', "null", "42"])
def test_a_checkpoint_of_the_wrong_shape_degrades(store, body):
    path = store.path_for("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    loaded = store.load("demo", endpoint_fingerprint=FINGERPRINT)
    assert loaded.checkpoint is None
    assert loaded.has_warning


def test_loading_never_raises(store):
    """A cache read must not be able to take a refresh down."""
    path = store.path_for("demo")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xff\xfe not utf-8 at all")
    assert store.load("demo", endpoint_fingerprint=FINGERPRINT).checkpoint is None


# -- durability ----------------------------------------------------------


def test_saving_replaces_atomically_leaving_no_temporary_behind(store):
    store.save(checkpoint())
    store.save(checkpoint(etag='W/"second"'))
    directory = store.path_for("demo").parent
    leftovers = [p.name for p in directory.iterdir() if p.name != store.path_for("demo").name]
    assert leftovers == []
    assert store.load("demo", endpoint_fingerprint=FINGERPRINT).checkpoint.etag == 'W/"second"'


def test_the_written_file_declares_its_schema_version(store):
    store.save(checkpoint())
    assert json.loads(store.path_for("demo").read_text())["schema_version"] == (
        CHECKPOINT_SCHEMA_VERSION
    )


def test_checkpoints_are_kept_per_source(store):
    store.save(checkpoint())
    store.save(checkpoint(source_id="other", etag='W/"other"'))
    assert store.load("demo", endpoint_fingerprint=FINGERPRINT).checkpoint.etag == 'W/"abc"'
    assert store.load("other", endpoint_fingerprint=FINGERPRINT).checkpoint.etag == 'W/"other"'


def test_an_absent_etag_is_allowed(store):
    """Not every server sends validators; that is normal, not a failure."""
    store.save(checkpoint(etag=None, last_modified=None))
    loaded = store.load("demo", endpoint_fingerprint=FINGERPRINT)
    assert loaded.checkpoint.validators_for(FINGERPRINT) == (None, None)
