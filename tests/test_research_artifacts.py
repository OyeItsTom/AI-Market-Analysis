"""Phase R artifact store: four files, written once, bytes as rendered."""

from __future__ import annotations

import pytest

from src.research import (
    ARTIFACT_MANIFEST,
    ARTIFACT_NAMES,
    ARTIFACT_OBSERVATIONS,
    ARTIFACT_REPORT,
    ARTIFACT_SUMMARY,
    ArtifactError,
    existing_artifacts,
    require_fresh,
    write_artifacts,
)

TEXTS = {
    ARTIFACT_MANIFEST: '{"a": 1}\n',
    ARTIFACT_SUMMARY: "row_type\ncoverage\n",
    ARTIFACT_OBSERVATIONS: "symbol\nAAA\n",
    ARTIFACT_REPORT: "# report\n",
}


def test_the_four_names_in_writing_order():
    assert ARTIFACT_NAMES == ("manifest.json", "summary.csv", "observations.csv", "report.md")


def test_writes_exactly_the_bytes_it_was_given(tmp_path):
    written = write_artifacts(tmp_path / "run", TEXTS)
    assert list(written) == list(ARTIFACT_NAMES)
    for name, path in written.items():
        assert path == tmp_path / "run" / name
        assert path.read_bytes() == TEXTS[name].encode("utf-8")
    assert existing_artifacts(tmp_path / "run") == ARTIFACT_NAMES


def test_line_endings_are_preserved_verbatim(tmp_path):
    texts = dict(TEXTS)
    texts[ARTIFACT_SUMMARY] = "a\r\nb\n"
    write_artifacts(tmp_path, texts)
    assert (tmp_path / ARTIFACT_SUMMARY).read_bytes() == b"a\r\nb\n"


def test_a_directory_with_any_artifact_is_refused(tmp_path):
    (tmp_path / ARTIFACT_REPORT).write_text("old")
    with pytest.raises(ArtifactError, match="not overwritten"):
        require_fresh(tmp_path)
    with pytest.raises(ArtifactError, match="not overwritten"):
        write_artifacts(tmp_path, TEXTS)
    assert (tmp_path / ARTIFACT_REPORT).read_text() == "old"
    assert not (tmp_path / ARTIFACT_MANIFEST).exists()


def test_a_fresh_or_missing_directory_is_accepted(tmp_path):
    require_fresh(tmp_path / "missing")
    assert existing_artifacts(tmp_path / "missing") == ()
    write_artifacts(tmp_path / "deep" / "er", TEXTS)
    assert (tmp_path / "deep" / "er" / ARTIFACT_MANIFEST).is_file()


@pytest.mark.parametrize(
    "texts",
    [
        {k: v for k, v in TEXTS.items() if k != ARTIFACT_REPORT},
        {**TEXTS, "extra.txt": "x"},
        {**TEXTS, ARTIFACT_SUMMARY: b"bytes"},
    ],
    ids=["missing", "extra", "not-text"],
)
def test_the_set_must_be_complete_and_textual(tmp_path, texts):
    with pytest.raises(ArtifactError):
        write_artifacts(tmp_path, texts)
    assert not list(tmp_path.iterdir())


# -- Phase 13A: a study's own artifact set, and reading a frozen study back ------------------


def test_a_named_artifact_set_is_written_and_read_back_exactly(tmp_path):
    from src.research import read_artifacts

    names = ("manifest.json", "diagnostics.csv", "episodes.csv", "report.md")
    texts = {"manifest.json": "{}\n", "diagnostics.csv": "a\r\nb\n", "episodes.csv": "x\n", "report.md": "# r\n"}
    written = write_artifacts(tmp_path / "run", texts, names)
    assert list(written) == list(names)
    assert read_artifacts(tmp_path / "run", names) == texts
    assert existing_artifacts(tmp_path / "run", names) == names
    # Seen through the Phase R default set, only the two shared names exist.
    assert existing_artifacts(tmp_path / "run") == ("manifest.json", "report.md")


def test_named_set_must_be_complete_and_fresh(tmp_path):
    names = ("a.txt", "b.txt")
    with pytest.raises(ArtifactError, match="exactly"):
        write_artifacts(tmp_path, {"a.txt": "1"}, names)
    write_artifacts(tmp_path, {"a.txt": "1", "b.txt": "2"}, names)
    with pytest.raises(ArtifactError, match="not overwritten"):
        write_artifacts(tmp_path, {"a.txt": "1", "b.txt": "2"}, names)
    with pytest.raises(ArtifactError, match="unique plain file names"):
        write_artifacts(tmp_path / "z", {"a.txt": "1"}, ("a.txt", "a.txt"))


def test_reading_a_missing_artifact_is_an_error(tmp_path):
    from src.research import read_artifacts

    with pytest.raises(ArtifactError, match="does not exist"):
        read_artifacts(tmp_path, ("missing.csv",))
