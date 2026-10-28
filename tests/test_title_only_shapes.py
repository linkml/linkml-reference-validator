"""Title-only validation handles every reference shape, and never skips silently (#146).

With a title but no excerpt, the title was validated only when the reference
was a single string or an object with an ``id``. A list, or an object with no
identifier, made the title check vanish without a word, so a wrong title passed
with exit 0. The excerpt path already handled these shapes (#140); the two now
share one reference resolver.
"""

import pytest
from linkml.validator import Validator  # type: ignore[import-untyped]
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)

#: Titles of tests/fixtures/PMID_TEST001.md and PMID_TEST002.md.
TITLE_1 = "Protein X functions in cell cycle regulation"
TITLE_2 = "Role of Protein Y in apoptosis pathway"
WRONG = "A Totally Wrong Title"

LIST_SCHEMA = """
id: https://example.org/titles
name: titles
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
      title:
        range: string
"""

OBJECT_SCHEMA = """
id: https://example.org/objtitles
name: objtitles
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/
default_prefix: ex
classes:
  Reference:
    attributes:
      id:
        identifier: true
      title:
        range: string
  Evidence:
    tree_root: true
    attributes:
      reference:
        range: Reference
        multivalued: true
        inlined: true
        inlined_as_list: true
"""


def _setup(tmp_path, fixtures_dir, schema_text):
    schema = tmp_path / "schema.yaml"
    schema.write_text(schema_text)
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


@pytest.fixture
def listed(tmp_path, fixtures_dir):
    return _setup(tmp_path, fixtures_dir, LIST_SCHEMA)


@pytest.fixture
def objects(tmp_path, fixtures_dir):
    return _setup(tmp_path, fixtures_dir, OBJECT_SCHEMA)


def test_plain_string_reference_still_checks_the_title(listed):
    """The case that already worked is unchanged."""
    _, _, plugin, validator = listed
    report = validator.validate({"reference": "PMID:TEST001", "title": WRONG})
    assert len(report.results) == 1
    assert plugin.titles_checked == 1


def test_one_item_list_is_checked_like_a_single_reference(listed):
    """The reproduction from #146: a wrong title in a one-item list fails."""
    _, _, plugin, validator = listed
    report = validator.validate({"reference": ["PMID:TEST001"], "title": WRONG})
    assert len(report.results) == 1
    assert plugin.titles_checked == 1
    assert validator.validate({"reference": ["PMID:TEST001"], "title": TITLE_1}).results == []


@pytest.mark.parametrize("title", [TITLE_1, TITLE_2])
def test_one_title_against_several_references_passes_if_any_matches(listed, title):
    _, _, _, validator = listed
    report = validator.validate({"reference": ["PMID:TEST001", "PMID:TEST002"], "title": title})
    assert report.results == []


def test_one_title_matching_none_of_several_references_names_each(listed):
    _, _, plugin, validator = listed
    report = validator.validate({"reference": ["PMID:TEST001", "PMID:TEST002"], "title": WRONG})
    assert len(report.results) == 1
    assert "PMID:TEST001" in report.results[0].message
    assert "PMID:TEST002" in report.results[0].message
    assert plugin.titles_checked == 1


def test_a_skipped_reference_does_not_vouch_for_a_title(listed):
    """As for excerpts, a skipped prefix is no evidence either way."""
    _, _, _, validator = listed
    report = validator.validate({"reference": ["GO:123", "PMID:TEST001"], "title": WRONG})
    assert len(report.results) == 1


def test_reference_without_identifier_is_reported(listed):
    """The second reproduction from #146: no usable identifier is an error, not a pass."""
    _, _, _, validator = listed
    report = validator.validate({"reference": [{"title": "no id here"}], "title": WRONG})
    assert len(report.results) == 1
    assert "no usable identifier" in report.results[0].message


def test_listed_objects_titles_are_each_checked_against_their_own_reference(objects):
    _, _, plugin, validator = objects
    report = validator.validate(
        {
            "reference": [
                {"id": "PMID:TEST001", "title": TITLE_1},
                {"id": "PMID:TEST002", "title": WRONG},
            ]
        }
    )
    assert [r.instantiates for r in report.results] == ["reference[1].title"]
    assert plugin.titles_checked == 2


def test_cli_exits_nonzero_for_a_wrong_title_in_a_list(listed, tmp_path):
    schema, cache, _, _ = listed
    data = tmp_path / "data.yaml"
    data.write_text(f"reference:\n  - PMID:TEST001\ntitle: {WRONG}\n")
    result = CliRunner().invoke(
        app,
        ["validate", "data", str(data), "-s", str(schema), "-c", str(cache), "--no-full-text"],
    )
    assert result.exit_code == 1, result.output
    assert "Titles checked: 1" in result.output


def test_a_single_reference_object_with_its_own_title_is_checked(objects):
    """Not only listed objects: one object carrying a title is checked too."""
    _, _, plugin, validator = objects
    report = validator.validate({"reference": {"id": "PMID:TEST001", "title": WRONG}})
    assert [r.instantiates for r in report.results] == ["reference.title"]
    assert plugin.titles_checked == 1
    assert validator.validate({"reference": {"id": "PMID:TEST001", "title": TITLE_1}}).results == []


def test_an_object_without_identifier_but_with_a_title_is_reported(objects):
    """Its title cannot be checked, so that is an error, not a silent pass."""
    _, _, _, validator = objects
    report = validator.validate({"reference": [{"title": WRONG}]})
    assert len(report.results) == 1
    assert "no usable identifier" in report.results[0].message


def test_references_with_no_title_anywhere_report_nothing(listed):
    """Nothing to check, nothing reported: an unusable reference alone is not a title issue."""
    _, _, plugin, validator = listed
    assert validator.validate({"reference": [""]}).results == []
    assert plugin.titles_checked == 0
