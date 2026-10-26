"""A multivalued reference slot must not leave its excerpts unchecked (#140)."""

import pytest
from linkml.validator import Validator  # type: ignore[import-untyped]
from linkml.validator.report import Severity  # type: ignore[import-untyped]
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ValidationSeverity,
)
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)

#: Text from tests/fixtures/PMID_TEST001.md and PMID_TEST002.md respectively.
QUOTE_1 = "Protein X functions in cell cycle regulation"
QUOTE_2 = "Protein Y inhibits apoptosis through direct interaction with caspase-3"
FABRICATED = "totally fabricated quote not in the paper"

SCHEMA = """
id: https://example.org/multiref
name: multiref
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/
default_prefix: ex
classes:
  Evidence:
    tree_root: true
    attributes:
      reference:
        range: string
        multivalued: true
      supporting_text:
        range: string
"""


@pytest.fixture
def setup(tmp_path, fixtures_dir):
    """A real schema with a multivalued reference slot and the fixture cache."""
    schema = tmp_path / "schema.yaml"
    schema.write_text(SCHEMA)
    cache = tmp_path / "cache"
    cache.mkdir()
    for source in fixtures_dir.glob("*.md"):
        (cache / source.name).write_text(source.read_text())
    plugin = ReferenceValidationPlugin(
        config=ReferenceValidationConfig(
            cache_dir=cache, fetch_full_text=False, skip_prefixes=["GO"]
        )
    )
    return schema, cache, plugin, Validator(schema=str(schema), validation_plugins=[plugin])


def messages(report):
    """The messages of every result in a LinkML validation report."""
    return [result.message for result in report.results]


def test_fabricated_quote_with_single_item_list_fails(setup):
    """The reported case: a one-item list must be checked like a string."""
    _, _, plugin, validator = setup
    report = validator.validate({"reference": ["PMID:TEST001"], "supporting_text": FABRICATED})
    assert len(report.results) == 1
    assert plugin.snippets_checked == 1


def test_true_quote_with_single_item_list_passes(setup):
    """A correct quote against a one-item list passes and is counted."""
    _, _, plugin, validator = setup
    report = validator.validate({"reference": ["PMID:TEST001"], "supporting_text": QUOTE_1})
    assert report.results == []
    assert plugin.snippets_checked == 1


@pytest.mark.parametrize("quote", [QUOTE_1, QUOTE_2])
def test_quote_from_any_listed_reference_passes(setup, quote):
    """An excerpt drawn from one of several cited references is valid."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {"reference": ["PMID:TEST001", "PMID:TEST002"], "supporting_text": quote}
    )
    assert report.results == []
    assert plugin.snippets_checked == 1


def test_quote_in_no_listed_reference_fails_naming_each(setup):
    """When no listed reference holds the excerpt, one error names them all."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {"reference": ["PMID:TEST001", "PMID:TEST002"], "supporting_text": FABRICATED}
    )
    assert len(report.results) == 1
    message = report.results[0].message
    assert "PMID:TEST001" in message and "PMID:TEST002" in message
    assert plugin.snippets_checked == 1


def test_listed_references_as_objects(setup):
    """List items may be inlined objects carrying an id, as single values may."""
    _, _, _, validator = setup
    data = {"reference": [{"id": "PMID:TEST002"}], "supporting_text": FABRICATED}
    assert len(validator.validate(data).results) == 1
    data["supporting_text"] = QUOTE_2
    assert validator.validate(data).results == []


def test_skipped_prefix_in_list_counts_as_skipped(setup):
    """A configured skip prefix still skips, rather than failing the excerpt."""
    _, _, plugin, validator = setup
    report = validator.validate({"reference": ["GO:123"], "supporting_text": QUOTE_1})
    assert report.results == []
    assert (plugin.snippets_checked, plugin.snippets_skipped) == (0, 1)


@pytest.mark.parametrize(
    "reference",
    [
        [{"title": "no id here"}],
        [""],
        [None],
        [42],
        {"title": "no id here"},
        42,
        "",
        0,
        False,
        {},
        [{"id": 123}],
        {"id": 123},
        {"id": ""},
    ],
)
def test_reference_without_usable_id_is_an_error(setup, reference):
    """A non-null reference that yields no identifier must not pass silently."""
    _, _, _, validator = setup
    report = validator.validate({"reference": reference, "supporting_text": QUOTE_1})
    assert len(report.results) == 1, messages(report)
    assert "identifier" in report.results[0].message


def test_unusable_item_beside_usable_one_is_reported(setup):
    """A bad list item is reported even when another item validates."""
    _, _, _, validator = setup
    report = validator.validate(
        {"reference": ["PMID:TEST001", {"title": "x"}], "supporting_text": QUOTE_1}
    )
    assert len(report.results) == 1
    assert "identifier" in report.results[0].message


def test_no_reference_at_all_is_unchanged(setup):
    """An excerpt with no reference value is not this check's concern."""
    _, _, _, validator = setup
    assert validator.validate({"supporting_text": QUOTE_1}).results == []
    assert validator.validate({"reference": [], "supporting_text": QUOTE_1}).results == []


def test_cli_exits_nonzero_for_fabricated_quote(setup, tmp_path):
    """End to end: validate data fails, as it does for a plain string reference."""
    schema, cache, _, _ = setup
    data = tmp_path / "data.yaml"
    data.write_text(f"reference:\n  - PMID:TEST001\nsupporting_text: {FABRICATED}\n")
    result = CliRunner().invoke(
        app,
        ["validate", "data", str(data), "-s", str(schema), "-c", str(cache), "--no-full-text"],
    )
    assert result.exit_code == 1, result.output
    assert "Snippets checked: 1" in result.output


@pytest.mark.parametrize(
    "references",
    [["GO:123", "PMID:TEST001"], ["PMID:TEST001", "GO:123"]],
)
def test_skipped_reference_is_no_evidence_for_a_fabricated_quote(setup, references):
    """A skipped prefix must not vouch for a quote another reference lacks."""
    _, _, plugin, validator = setup
    report = validator.validate({"reference": references, "supporting_text": FABRICATED})
    assert len(report.results) == 1
    assert "PMID:TEST001" in report.results[0].message
    assert (plugin.snippets_checked, plugin.snippets_skipped) == (1, 0)


def test_skipped_reference_beside_a_holding_reference_passes(setup):
    """The quote passes on the reference that holds it, skip or no skip."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {"reference": ["GO:123", "PMID:TEST001"], "supporting_text": QUOTE_1}
    )
    assert report.results == []
    assert (plugin.snippets_checked, plugin.snippets_skipped) == (1, 0)


def test_all_listed_references_skipped_counts_as_skipped(setup):
    """Only when every reference is skipped is the excerpt skipped."""
    _, _, plugin, validator = setup
    report = validator.validate({"reference": ["GO:123", "GO:456"], "supporting_text": QUOTE_1})
    assert report.results == []
    assert (plugin.snippets_checked, plugin.snippets_skipped) == (0, 1)


@pytest.mark.parametrize(
    "references,expected",
    [
        (["UNSUPPORTED:1", "PMID:TEST001"], Severity.ERROR),
        (["PMID:TEST001", "UNSUPPORTED:1"], Severity.ERROR),
        (["UNSUPPORTED:1", "UNSUPPORTED:2"], Severity.WARN),
    ],
)
def test_combined_error_takes_the_most_severe(setup, references, expected):
    """The combined severity does not depend on the order references are listed."""
    schema, cache, _, _ = setup
    plugin = ReferenceValidationPlugin(
        config=ReferenceValidationConfig(
            cache_dir=cache,
            fetch_full_text=False,
            unknown_prefix_severity=ValidationSeverity.WARNING,
        )
    )
    validator = Validator(schema=str(schema), validation_plugins=[plugin])
    report = validator.validate({"reference": references, "supporting_text": FABRICATED})
    assert [result.severity for result in report.results] == [expected]
