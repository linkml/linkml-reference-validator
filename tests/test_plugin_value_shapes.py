"""Every excerpt and every evidence object is validated, whatever shape holds it.

- #141: a multivalued excerpt slot reached the validator as a list and
  crashed ``validate data`` with ``TypeError``. Each listed excerpt is now
  checked on its own, at its own ``[i]`` path.
- #139: a multivalued, class-ranged slot written as a keyed mapping
  (``inlined_as_list: false``) was treated as one object, so the evidence
  inside was never visited and a fabricated quote passed with exit 0.
"""

import pytest
from linkml.validator import Validator  # type: ignore[import-untyped]
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)

#: Text from tests/fixtures/PMID_TEST001.md.
QUOTE = "Protein X functions in cell cycle regulation"
FABRICATED = "totally fabricated quote not in the paper"

MULTIVALUED_EXCERPT_SCHEMA = """
id: https://example.org/mvexcerpt
name: mvexcerpt
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
      supporting_text:
        range: string
        multivalued: true
"""

KEYED_EVIDENCE_SCHEMA = """
id: https://example.org/keyed
name: keyed
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/
default_prefix: ex
classes:
  Evidence:
    attributes:
      id:
        identifier: true
      reference:
        range: string
      supporting_text:
        range: string
  Statement:
    tree_root: true
    attributes:
      id:
        identifier: true
      has_evidence:
        range: Evidence
        multivalued: true
        inlined: true
        inlined_as_list: false
"""


def _setup(tmp_path, fixtures_dir, schema_text):
    schema = tmp_path / "schema.yaml"
    schema.write_text(schema_text)
    cache = tmp_path / "cache"
    cache.mkdir()
    for source in fixtures_dir.glob("*.md"):
        (cache / source.name).write_text(source.read_text())
    plugin = ReferenceValidationPlugin(
        config=ReferenceValidationConfig(cache_dir=cache, fetch_full_text=False)
    )
    return schema, cache, plugin, Validator(schema=str(schema), validation_plugins=[plugin])


def _cli(schema, cache, data):
    return CliRunner().invoke(
        app,
        ["validate", "data", str(data), "-s", str(schema), "-c", str(cache), "--no-full-text"],
    )


# ----------------------------------------------------------------- #141


@pytest.fixture
def excerpts(tmp_path, fixtures_dir):
    return _setup(tmp_path, fixtures_dir, MULTIVALUED_EXCERPT_SCHEMA)


def test_listed_fabricated_excerpt_fails_without_crashing(excerpts):
    """The reproduction from #141: an error, not a TypeError."""
    _, _, plugin, validator = excerpts
    report = validator.validate({"reference": "PMID:TEST001", "supporting_text": [FABRICATED]})
    assert len(report.results) == 1
    assert report.results[0].instantiates == "supporting_text[0]"
    assert plugin.snippets_checked == 1


def test_each_listed_excerpt_is_checked_on_its_own(excerpts):
    """A true excerpt beside a fabricated one does not carry it."""
    _, _, plugin, validator = excerpts
    report = validator.validate(
        {"reference": "PMID:TEST001", "supporting_text": [QUOTE, FABRICATED]}
    )
    assert [r.instantiates for r in report.results] == ["supporting_text[1]"]
    assert plugin.snippets_checked == 2


def test_listed_true_excerpts_pass(excerpts):
    _, _, plugin, validator = excerpts
    report = validator.validate({"reference": "PMID:TEST001", "supporting_text": [QUOTE, QUOTE]})
    assert report.results == []
    assert plugin.snippets_checked == 2


def test_a_blank_listed_excerpt_is_reported_at_its_index(excerpts):
    """The content check applies to each item, as to a single excerpt."""
    _, _, _, validator = excerpts
    report = validator.validate({"reference": "PMID:TEST001", "supporting_text": [QUOTE, "  "]})
    assert [r.instantiates for r in report.results] == ["supporting_text[1]"]
    assert "empty" in report.results[0].message.lower()


def test_listed_excerpts_without_a_usable_reference_report_it_once(excerpts):
    """One unusable-reference error for the field, not one per excerpt."""
    _, _, _, validator = excerpts
    report = validator.validate({"reference": "", "supporting_text": [QUOTE, FABRICATED]})
    assert len(report.results) == 1
    assert "no usable identifier" in report.results[0].message


def test_cli_exits_nonzero_for_a_listed_fabricated_excerpt(excerpts, tmp_path):
    schema, cache, _, _ = excerpts
    data = tmp_path / "data.yaml"
    data.write_text(f"reference: PMID:TEST001\nsupporting_text:\n  - {FABRICATED}\n")
    result = _cli(schema, cache, data)
    assert result.exit_code == 1, result.output
    assert "Snippets checked: 1" in result.output


# ----------------------------------------------------------------- #139


@pytest.fixture
def keyed(tmp_path, fixtures_dir):
    return _setup(tmp_path, fixtures_dir, KEYED_EVIDENCE_SCHEMA)


def test_fabricated_evidence_in_a_keyed_mapping_fails(keyed):
    """The reproduction from #139: the evidence inside the mapping is visited."""
    _, _, plugin, validator = keyed
    report = validator.validate(
        {
            "id": "S1",
            "has_evidence": {
                "E1": {"reference": "PMID:TEST001", "supporting_text": FABRICATED},
            },
        }
    )
    assert len(report.results) == 1
    assert report.results[0].instantiates == "has_evidence[E1].supporting_text"
    assert plugin.snippets_checked == 1


def test_every_object_in_a_keyed_mapping_is_validated(keyed):
    _, _, plugin, validator = keyed
    report = validator.validate(
        {
            "id": "S1",
            "has_evidence": {
                "E1": {"reference": "PMID:TEST001", "supporting_text": QUOTE},
                "E2": {"reference": "PMID:TEST001", "supporting_text": FABRICATED},
            },
        }
    )
    assert [r.instantiates for r in report.results] == ["has_evidence[E2].supporting_text"]
    assert plugin.snippets_checked == 2


def test_keyed_mapping_written_as_a_list_still_works(keyed):
    """The list form, which already worked, is unchanged."""
    _, _, plugin, validator = keyed
    report = validator.validate(
        {
            "id": "S1",
            "has_evidence": [
                {"id": "E1", "reference": "PMID:TEST001", "supporting_text": FABRICATED},
            ],
        }
    )
    assert len(report.results) == 1
    assert plugin.snippets_checked == 1


def test_cli_exits_nonzero_for_fabricated_keyed_evidence(keyed, tmp_path):
    schema, cache, _, _ = keyed
    data = tmp_path / "data.yaml"
    data.write_text(
        "id: S1\nhas_evidence:\n  E1:\n    reference: PMID:TEST001\n"
        f"    supporting_text: {FABRICATED}\n"
    )
    result = _cli(schema, cache, data)
    assert result.exit_code == 1, result.output
    assert "Snippets checked: 1" in result.output


ANONYMOUS_EVIDENCE_SCHEMA = """
id: https://example.org/anon
name: anon
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/
default_prefix: ex
classes:
  Evidence:
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
  Statement:
    tree_root: true
    attributes:
      has_evidence:
        range: Evidence
        multivalued: true
        inlined: true
"""

KEY_SLOT_SCHEMA = """
id: https://example.org/keyslot
name: keyslot
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/
default_prefix: ex
classes:
  Evidence:
    attributes:
      reference:
        key: true
      supporting_text:
        range: string
  Statement:
    tree_root: true
    attributes:
      has_evidence:
        range: Evidence
        multivalued: true
        inlined: true
        inlined_as_list: false
"""


def test_single_object_in_a_multivalued_slot_without_identifier_is_validated(
    tmp_path, fixtures_dir
):
    """With no identifier the dict cannot be a keyed mapping: it is one object, as before."""
    _, _, plugin, validator = _setup(tmp_path, fixtures_dir, ANONYMOUS_EVIDENCE_SCHEMA)
    report = validator.validate(
        {"has_evidence": {"reference": "PMID:TEST001", "supporting_text": FABRICATED}}
    )
    assert len(report.results) == 1
    assert report.results[0].instantiates == "has_evidence.supporting_text"
    assert plugin.snippets_checked == 1


def test_single_object_with_an_identifier_in_a_multivalued_slot_is_validated(keyed):
    """A dict whose values are not all objects is one object, not a mapping."""
    _, _, plugin, validator = keyed
    report = validator.validate(
        {
            "id": "S1",
            "has_evidence": {
                "id": "E1", "reference": "PMID:TEST001", "supporting_text": FABRICATED,
            },
        }
    )
    assert len(report.results) == 1
    assert plugin.snippets_checked == 1


def test_a_key_slot_is_filled_in_from_the_mapping_key(tmp_path, fixtures_dir):
    """Evidence keyed by its ``key: true`` reference: the key is the reference."""
    _, _, plugin, validator = _setup(tmp_path, fixtures_dir, KEY_SLOT_SCHEMA)
    report = validator.validate(
        {"has_evidence": {"PMID:TEST001": {"supporting_text": FABRICATED}}}
    )
    assert len(report.results) == 1
    assert report.results[0].instantiates == "has_evidence[PMID:TEST001].supporting_text"
    assert plugin.snippets_checked == 1


def test_null_and_compact_entries_in_a_keyed_mapping_do_not_crash(keyed):
    """``E1: null`` is an object with only its key; ``E2: text`` is the compact form."""
    _, _, plugin, validator = keyed
    report = validator.validate(
        {
            "id": "S1",
            "has_evidence": {
                "E1": None,
                "E3": {"reference": "PMID:TEST001", "supporting_text": FABRICATED},
            },
        }
    )
    assert [r.instantiates for r in report.results] == ["has_evidence[E3].supporting_text"]
    report = validator.validate({"id": "S1", "has_evidence": {"E2": "compact text"}})
    assert report.results == []


def test_a_non_text_listed_excerpt_is_an_error_at_its_index(excerpts):
    _, _, _, validator = excerpts
    report = validator.validate({"reference": "PMID:TEST001", "supporting_text": [QUOTE, 5]})
    assert [r.instantiates for r in report.results] == ["supporting_text[1]"]
    assert "must be text" in report.results[0].message


def test_a_null_listed_excerpt_is_skipped_like_an_absent_one(excerpts):
    _, _, plugin, validator = excerpts
    report = validator.validate({"reference": "PMID:TEST001", "supporting_text": [QUOTE, None]})
    assert report.results == []
    assert plugin.snippets_checked == 1


def test_a_compact_entry_does_not_hide_the_objects_beside_it(keyed):
    """Mixed entries: the mapping is still keyed, and its objects are validated."""
    _, _, plugin, validator = keyed
    report = validator.validate(
        {
            "id": "S1",
            "has_evidence": {
                "E1": {"reference": "PMID:TEST001", "supporting_text": FABRICATED},
                "E2": "compact value",
            },
        }
    )
    assert [r.instantiates for r in report.results] == ["has_evidence[E1].supporting_text"]
    assert plugin.snippets_checked == 1
