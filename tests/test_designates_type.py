"""Inlined objects are validated as the class their type designator names (#170).

A slot whose range is an abstract class may hold an object that names its
concrete subclass in a ``designates_type`` slot. The plugin used to validate
such an object as the abstract range, so every slot defined only on the
subclass (here ``references``) was skipped and validation reported success
having checked nothing.
"""

import pytest
from linkml.validator import Validator  # type: ignore[import-untyped]
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)

#: Title and a true quote from tests/fixtures/PMID_TEST001.md.
TITLE = "Protein X functions in cell cycle regulation"
QUOTE = "Protein X functions in cell cycle regulation"
WRONG_TITLE = "A deliberately wrong title"
FABRICATED = "totally fabricated quote not in the paper"

#: The schema from #170, plus an excerpt-bearing subclass, a grandchild, an
#: unrelated class, and list and keyed-mapping slots.
SCHEMA = """
id: https://example.org/repro
name: repro
prefixes:
  linkml: https://w3id.org/linkml/
  dcterms: http://purl.org/dc/terms/
  ex: https://example.org/repro/
default_prefix: ex
default_range: string
imports:
- linkml:types

classes:
  Container:
    tree_root: true
    attributes:
      model:
        range: Model
        inlined: true
      models:
        range: Model
        multivalued: true
        inlined_as_list: true
      model_map:
        range: Model
        multivalued: true
        inlined: true
        inlined_as_list: false
  Model:
    abstract: true
    attributes:
      id:
        identifier: true
      type:
        designates_type: true
  Organoid:
    is_a: Model
    attributes:
      references:
        range: Reference
        multivalued: true
        inlined_as_list: true
  BrainOrganoid:
    is_a: Organoid
  Assay:
    is_a: Model
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
  Unrelated:
    attributes:
      references:
        range: Reference
        multivalued: true
        inlined_as_list: true
  Reference:
    attributes:
      id:
        identifier: true
        implements:
        - dcterms:references
      title:
        slot_uri: dcterms:title
"""


def _wrong_reference():
    return [{"id": "PMID:TEST001", "title": WRONG_TITLE}]


@pytest.fixture
def setup(tmp_path, fixtures_dir):
    """Schema file, cache of fixture references, plugin, and validator."""
    schema = tmp_path / "schema.yaml"
    schema.write_text(SCHEMA)
    cache = tmp_path / "cache"
    cache.mkdir()
    for source in fixtures_dir.glob("*.md"):
        (cache / source.name).write_text(source.read_text())
    plugin = ReferenceValidationPlugin(
        config=ReferenceValidationConfig(cache_dir=cache, fetch_full_text=False)
    )
    validator = Validator(schema=str(schema), validation_plugins=[plugin])
    return schema, cache, plugin, validator


def test_nested_single_object_is_validated_as_its_type(setup):
    """The reproduction from #170: the wrong title is caught when nested."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {"model": {"id": "m1", "type": "Organoid", "references": _wrong_reference()}},
        "Container",
    )
    assert plugin.titles_checked == 1
    assert len(report.results) == 1
    assert report.results[0].instantiates == "model.references[0].title"


def test_correct_nested_title_passes(setup):
    _, _, plugin, validator = setup
    report = validator.validate(
        {
            "model": {
                "id": "m1",
                "type": "Organoid",
                "references": [{"id": "PMID:TEST001", "title": TITLE}],
            }
        },
        "Container",
    )
    assert plugin.titles_checked == 1
    assert report.results == []


def test_each_list_item_resolves_its_own_type(setup):
    """A mixed list: each item is validated as the class it names."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {
            "models": [
                {"id": "m1", "type": "Organoid", "references": _wrong_reference()},
                {
                    "id": "m2",
                    "type": "Assay",
                    "reference": "PMID:TEST001",
                    "supporting_text": FABRICATED,
                },
            ]
        },
        "Container",
    )
    assert plugin.titles_checked == 1
    assert plugin.snippets_checked == 1
    assert sorted(r.instantiates for r in report.results) == [
        "models[0].references[0].title",
        "models[1].supporting_text",
    ]


def test_keyed_mapping_values_resolve_their_type(setup):
    """The type slot inside each value of a keyed mapping is honoured."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {"model_map": {"m1": {"type": "Organoid", "references": _wrong_reference()}}},
        "Container",
    )
    assert plugin.titles_checked == 1
    assert [r.instantiates for r in report.results] == ["model_map[m1].references[0].title"]


def test_grandchild_type_inherits_the_designator(setup):
    """BrainOrganoid is a grandchild of Model; its designator is inherited."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {"model": {"id": "m1", "type": "BrainOrganoid", "references": _wrong_reference()}},
        "Container",
    )
    assert plugin.titles_checked == 1
    assert len(report.results) == 1


@pytest.mark.parametrize(
    "type_value",
    ["ex:Organoid", "https://example.org/repro/Organoid"],
)
def test_type_given_as_curie_or_uri(setup, type_value):
    _, _, plugin, validator = setup
    report = validator.validate(
        {"model": {"id": "m1", "type": type_value, "references": _wrong_reference()}},
        "Container",
    )
    assert plugin.titles_checked == 1
    assert len(report.results) == 1


@pytest.mark.parametrize("type_value", ["NoSuchClass", "Unrelated", "Reference", 42])
def test_unknown_or_unrelated_type_falls_back_to_range(setup, type_value):
    """A type that is not the range or a descendant of it is not trusted."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {"model": {"id": "m1", "type": type_value, "references": _wrong_reference()}},
        "Container",
    )
    assert plugin.titles_checked == 0
    assert report.results == []


def test_top_level_target_class_resolves_type(setup):
    """Validating a Model directly also follows its type designator."""
    _, _, plugin, validator = setup
    report = validator.validate(
        {"id": "m1", "type": "Organoid", "references": _wrong_reference()},
        "Model",
    )
    assert plugin.titles_checked == 1
    assert len(report.results) == 1


def test_resolve_concrete_class(setup):
    """The helper itself, across the shapes a designator value takes."""
    _, _, plugin, validator = setup
    validator.validate({}, "Container")  # gives the plugin its schema view
    resolve = plugin._resolve_concrete_class
    assert resolve({"type": "Organoid"}, "Model") == "Organoid"
    assert resolve({"type": "ex:BrainOrganoid"}, "Model") == "BrainOrganoid"
    assert resolve({"type": "Model"}, "Model") == "Model"
    assert resolve({}, "Model") == "Model"
    assert resolve({"type": "Unrelated"}, "Model") == "Model"
    # Container has no designator, so the value is never consulted.
    assert resolve({"type": "Organoid"}, "Container") == "Container"


def test_cli_reproduction(setup, tmp_path):
    """The console reproduction from #170."""
    schema, cache, _, _ = setup
    data = tmp_path / "nested.yaml"
    data.write_text(
        "model:\n"
        "  id: m1\n"
        "  type: Organoid\n"
        "  references:\n"
        "  - id: PMID:TEST001\n"
        f"    title: {WRONG_TITLE}\n"
    )
    result = CliRunner().invoke(
        app,
        [
            "validate",
            "data",
            str(data),
            "-s",
            str(schema),
            "-c",
            str(cache),
            "--no-full-text",
            "--target-class",
            "Container",
        ],
    )
    assert result.exit_code == 1, result.output
    assert "Titles checked: 1" in result.output
