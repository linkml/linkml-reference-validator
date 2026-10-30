"""``repair data`` writes what ``--output`` asks for, and reads inlined references.

Two bugs in ``cli/repair.py``:

- With ``--no-dry-run --output OUT``, OUT was written only when something was
  auto-fixed. With nothing to fix, or no evidence items at all, the command
  exited 0 and OUT never appeared, so a pipeline reading it next failed or read
  a stale file (#143). OUT is now always written outside a dry run, unchanged
  when there is nothing to fix. A ``.bak`` is made only when the input itself
  is overwritten.
- An evidence item whose ``reference`` is an inlined object
  (``reference: {id: PMID:1, title: ...}``) passed the whole mapping on as the
  reference id, and the repair crashed with ``AttributeError: 'CommentedMap'
  object has no attribute 'strip'`` (#138). The id is now read the way the
  validation plugin reads it.
"""

import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.cli.repair import _extract_evidence_items

runner = CliRunner()

SCHEMA = """
id: https://example.org/test
name: test
default_prefix: test
classes:
  Statement:
    tree_root: true
    attributes:
      text:
        range: string
      evidence:
        multivalued: true
        range: Evidence
  Evidence:
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
"""

VALID = """\
text: "Test statement"
evidence:
  - reference: "PMID:TEST001"
    supporting_text: "Protein X functions in cell cycle regulation"
"""

FIXABLE = """\
text: "Test statement"
evidence:
  - reference: "PMID:TEST001"
    supporting_text: "CO2 levels were measured"
"""

NO_EVIDENCE = """\
text: "Test statement"
"""

INLINED = """\
text: "Test statement"
evidence:
  - reference:
      id: "PMID:TEST001"
      title: "Protein X functions in cell cycle regulation"
    supporting_text: "CO2 levels were measured"
"""


@pytest.fixture
def cache_dir(tmp_path, fixtures_dir):
    """A cache holding the test references, so nothing is fetched."""
    cache = tmp_path / "cache"
    cache.mkdir()
    for fixture in fixtures_dir.glob("*"):
        if fixture.is_file():
            (cache / fixture.name).write_text(fixture.read_text())
    return cache


@pytest.fixture
def schema(tmp_path):
    path = tmp_path / "schema.yaml"
    path.write_text(SCHEMA)
    return path


def _repair(data: Path, schema: Path, cache_dir: Path, *extra: str):
    return runner.invoke(
        app,
        ["repair", "data", str(data), "--schema", str(schema),
         "--cache-dir", str(cache_dir), *extra],
    )


@pytest.mark.parametrize("content", [VALID, NO_EVIDENCE], ids=["already_valid", "no_evidence"])
def test_output_is_written_unchanged_when_there_is_nothing_to_fix(
    tmp_path, schema, cache_dir, content
):
    data = tmp_path / "data.yaml"
    data.write_text(content)
    out = tmp_path / "out.yaml"

    result = _repair(data, schema, cache_dir, "--no-dry-run", "--output", str(out))

    assert result.exit_code == 0, result.output
    assert out.read_bytes() == data.read_bytes()
    assert data.read_text() == content
    assert f"Wrote {out}" in result.output
    assert not (tmp_path / "data.yaml.bak").exists()


def test_output_is_not_written_in_a_dry_run(tmp_path, schema, cache_dir):
    data = tmp_path / "data.yaml"
    data.write_text(FIXABLE)
    out = tmp_path / "out.yaml"

    result = _repair(data, schema, cache_dir, "--dry-run", "--output", str(out))

    assert result.exit_code == 0, result.output
    assert not out.exists()


def test_a_fix_written_to_output_leaves_the_input_alone(tmp_path, schema, cache_dir):
    """No backup either: the input is not being overwritten."""
    data = tmp_path / "data.yaml"
    data.write_text(FIXABLE)
    out = tmp_path / "out.yaml"

    result = _repair(data, schema, cache_dir, "--no-dry-run", "--output", str(out))

    assert result.exit_code == 0, result.output
    assert "CO₂ levels were measured" in out.read_text()
    assert data.read_text() == FIXABLE
    assert not (tmp_path / "data.yaml.bak").exists()


def test_a_fix_in_place_still_backs_up_the_input(tmp_path, schema, cache_dir):
    data = tmp_path / "data.yaml"
    data.write_text(FIXABLE)

    result = _repair(data, schema, cache_dir, "--no-dry-run")

    assert result.exit_code == 0, result.output
    assert "CO₂ levels were measured" in data.read_text()
    assert (tmp_path / "data.yaml.bak").read_text() == FIXABLE


def test_output_naming_the_input_with_nothing_to_fix_leaves_it_alone(
    tmp_path, schema, cache_dir
):
    """``-o`` pointing at the input itself is not an error, and nothing changes."""
    data = tmp_path / "data.yaml"
    data.write_text(VALID)

    result = _repair(data, schema, cache_dir, "--no-dry-run", "--output", str(data))

    assert result.exit_code == 0, result.output
    assert data.read_text() == VALID
    assert not (tmp_path / "data.yaml.bak").exists()


def test_nothing_to_fix_without_output_writes_nothing(tmp_path, schema, cache_dir):
    """Without ``-o`` the input is rewritten only when a fix is applied."""
    data = tmp_path / "data.yaml"
    data.write_text(VALID)
    before = data.stat().st_mtime_ns

    result = _repair(data, schema, cache_dir, "--no-dry-run")

    assert result.exit_code == 0, result.output
    assert data.stat().st_mtime_ns == before
    assert not (tmp_path / "data.yaml.bak").exists()


# --- #138: inlined reference objects ----------------------------------------


def test_an_inlined_reference_is_repaired_without_crashing(tmp_path, schema, cache_dir):
    data = tmp_path / "data.yaml"
    data.write_text(INLINED)
    out = tmp_path / "out.yaml"

    result = _repair(data, schema, cache_dir, "--no-dry-run", "--output", str(out))

    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.exit_code == 0, result.output
    assert "Found 1 evidence item(s)" in result.output
    repaired = out.read_text()
    assert "CO₂ levels were measured" in repaired
    assert 'id: "PMID:TEST001"' in repaired


def test_extract_reads_the_id_of_an_inlined_reference():
    data = {"evidence": [{"reference": {"id": "PMID:1", "title": "T"}, "supporting_text": "x"}]}
    assert _extract_evidence_items(data, None, Path("unused.yaml")) == [
        ("x", "PMID:1", "evidence[0].supporting_text")
    ]


def test_extract_accepts_reference_id_inside_the_object():
    data = {"evidence": [{"reference": {"reference_id": "PMID:2"}, "supporting_text": "x"}]}
    assert _extract_evidence_items(data, None, Path("unused.yaml")) == [
        ("x", "PMID:2", "evidence[0].supporting_text")
    ]


@pytest.mark.parametrize(
    "reference",
    [{"title": "No id"}, {"id": 123}, ["PMID:1", "PMID:2"]],
    ids=["no_id", "non_text_id", "list"],
)
def test_extract_skips_a_reference_with_no_single_id_and_says_so(reference, caplog):
    """Not a crash, and not silent: the item is skipped with a warning naming it."""
    data = {"evidence": [{"reference": reference, "supporting_text": "x"}]}
    with caplog.at_level(logging.WARNING):
        assert _extract_evidence_items(data, None, Path("unused.yaml")) == []
    assert "evidence[0]" in caplog.text


def test_the_inlined_reference_object_is_not_itself_an_evidence_item():
    """Recursing into ``{id, title}`` finds no second item there."""
    data = {"evidence": [{"reference": {"id": "PMID:1", "supporting_text": "odd"},
                          "supporting_text": "x"}]}
    items = _extract_evidence_items(data, None, Path("unused.yaml"))
    assert [i[1] for i in items] == ["PMID:1"]
