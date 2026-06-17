"""Tests for deeply nested evidence traversal.

Verifies that the reference validation plugin correctly discovers and validates
evidence items nested multiple levels deep from the tree root.

Schema pattern being tested:
  Community (root) -> MemberRecord -> EvidenceItem (has implements annotations)
  Community (root) -> Interaction -> EvidenceItem

This mirrors real-world schemas like CommunityMech where:
  MicrobialCommunity -> TaxonomicComposition -> EvidenceItem

The existing test_schema.yaml only tests 1-level nesting:
  Statement (root) -> Evidence (has implements annotations)

See: https://github.com/CultureBotAI/CommunityMech/issues/3
"""

from pathlib import Path

import pytest
from ruamel.yaml import YAML
from linkml_runtime.utils.schemaview import SchemaView  # type: ignore[import-untyped]
from linkml.validator import Validator  # type: ignore[import-untyped]
from linkml.validator.validation_context import ValidationContext  # type: ignore[import-untyped]

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)


DATA_DIR = Path(__file__).parent / "data"
FIXTURES_DIR = Path(__file__).parent / "fixtures"

DEEP_SCHEMA = DATA_DIR / "test_schema_deep_nesting.yaml"
SHALLOW_SCHEMA = DATA_DIR / "test_schema.yaml"

_yaml = YAML(typ="safe")


@pytest.fixture
def deep_schema_view():
    """SchemaView for the deeply nested schema."""
    return SchemaView(str(DEEP_SCHEMA))


@pytest.fixture
def shallow_schema_view():
    """SchemaView for the existing shallow schema (1-level nesting)."""
    return SchemaView(str(SHALLOW_SCHEMA))


@pytest.fixture
def plugin_with_fixtures(tmp_path):
    """Plugin with cached test references."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for fixture_file in FIXTURES_DIR.glob("*.md"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    for fixture_file in FIXTURES_DIR.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        rate_limit_delay=0.0,
    )
    return ReferenceValidationPlugin(config=config)


# ---------------------------------------------------------------------------
# Sanity check: shallow nesting (1 level) works with existing schema
# ---------------------------------------------------------------------------


def test_shallow_nesting_finds_evidence(plugin_with_fixtures, shallow_schema_view):
    """Shallow nesting (Statement -> Evidence) should find and validate evidence.

    The plugin must traverse to the nested evidence; we prove it did by feeding
    INVALID supporting text and checking it is rejected (0 results would mean the
    plugin never reached the evidence item).
    """
    context = ValidationContext(
        shallow_schema_view.schema,
        target_class="Statement",
    )
    plugin_with_fixtures.pre_process(context)

    instance_invalid = {
        "text": "Some statement",
        "has_evidence": [
            {
                "reference": {"id": "PMID:TEST001", "title": "Study of Protein X"},
                "supporting_text": "fabricated text not in the reference at all",
            }
        ],
    }
    results_invalid = list(plugin_with_fixtures.process(instance_invalid, context))
    assert len(results_invalid) > 0, (
        "Shallow nesting: plugin should find and reject invalid snippet"
    )


# ---------------------------------------------------------------------------
# The actual bug: deep nesting (2+ levels) should also find evidence
# ---------------------------------------------------------------------------


def test_deep_nesting_finds_evidence_in_members(
    plugin_with_fixtures, deep_schema_view
):
    """Deep nesting (Community -> MemberRecord -> EvidenceItem) must find evidence.

    This is the core bug reproduction: the plugin should recursively traverse
    through MemberRecord to reach EvidenceItem and validate the snippet.
    """
    instance_invalid = {
        "name": "Test Community",
        "members": [
            {
                "taxon_name": "Species A",
                "evidence": [
                    {
                        "reference": "PMID:TEST001",
                        "snippet": "fabricated text not in the reference at all",
                    }
                ],
            }
        ],
    }

    context = ValidationContext(
        deep_schema_view.schema,
        target_class="Community",
    )
    plugin_with_fixtures.pre_process(context)

    results = list(plugin_with_fixtures.process(instance_invalid, context))
    assert len(results) > 0, (
        "Deep nesting: plugin should traverse Community -> MemberRecord -> "
        "EvidenceItem and reject the invalid snippet. Got 0 results, meaning "
        "the plugin never found the deeply nested evidence items."
    )


def test_deep_nesting_valid_snippets_pass(plugin_with_fixtures, deep_schema_view):
    """Valid snippets in deeply nested evidence should pass without errors."""
    with open(DATA_DIR / "test_data_deep_nesting_valid.yaml") as f:
        instance = _yaml.load(f)

    context = ValidationContext(
        deep_schema_view.schema,
        target_class="Community",
    )
    plugin_with_fixtures.pre_process(context)

    results = list(plugin_with_fixtures.process(instance, context))
    assert len(results) == 0, (
        f"Valid deep-nested snippets should pass, but got {len(results)} errors: "
        + "; ".join(r.message for r in results)
    )


def test_deep_nesting_invalid_snippets_caught(
    plugin_with_fixtures, deep_schema_view
):
    """Invalid snippets in deeply nested evidence should be caught."""
    with open(DATA_DIR / "test_data_deep_nesting_invalid.yaml") as f:
        instance = _yaml.load(f)

    context = ValidationContext(
        deep_schema_view.schema,
        target_class="Community",
    )
    plugin_with_fixtures.pre_process(context)

    results = list(plugin_with_fixtures.process(instance, context))
    # There are 2 invalid snippets: one in members, one in interactions
    assert len(results) >= 2, (
        f"Should catch at least 2 invalid snippets in deeply nested evidence, "
        f"but only caught {len(results)}. This suggests the plugin isn't "
        f"traversing through intermediate containers to reach EvidenceItem."
    )


def test_deep_nesting_interactions_path(plugin_with_fixtures, deep_schema_view):
    """Evidence nested under interactions (second path) should also be found."""
    instance_invalid = {
        "name": "Test Community",
        "interactions": [
            {
                "interaction_name": "cross-feeding",
                "source_taxon": "Species A",
                "target_taxon": "Species B",
                "evidence": [
                    {
                        "reference": "PMID:TEST001",
                        "snippet": "completely made up text not in abstract",
                    }
                ],
            }
        ],
    }

    context = ValidationContext(
        deep_schema_view.schema,
        target_class="Community",
    )
    plugin_with_fixtures.pre_process(context)

    results = list(plugin_with_fixtures.process(instance_invalid, context))
    assert len(results) > 0, (
        "Deep nesting via interactions path: plugin should traverse "
        "Community -> Interaction -> EvidenceItem and reject invalid snippet."
    )


def test_deep_nesting_multiple_members_multiple_evidence(
    plugin_with_fixtures, deep_schema_view
):
    """Multiple members each with multiple evidence items should all be found."""
    instance_invalid = {
        "name": "Test Community",
        "members": [
            {
                "taxon_name": "Species A",
                "evidence": [
                    {
                        "reference": "PMID:TEST001",
                        "snippet": "fake snippet one",
                    },
                    {
                        "reference": "PMID:TEST002",
                        "snippet": "fake snippet two",
                    },
                ],
            },
            {
                "taxon_name": "Species B",
                "evidence": [
                    {
                        "reference": "PMID:TEST001",
                        "snippet": "fake snippet three",
                    },
                ],
            },
        ],
    }

    context = ValidationContext(
        deep_schema_view.schema,
        target_class="Community",
    )
    plugin_with_fixtures.pre_process(context)

    results = list(plugin_with_fixtures.process(instance_invalid, context))
    assert len(results) >= 3, (
        f"Should catch all 3 invalid snippets across 2 members, "
        f"but only caught {len(results)}."
    )


# ---------------------------------------------------------------------------
# Field detection: verify plugin discovers implements annotations at depth
# ---------------------------------------------------------------------------


def test_deep_schema_evidence_fields_detected(
    plugin_with_fixtures, deep_schema_view
):
    """Plugin should detect reference and excerpt fields on EvidenceItem class."""
    plugin_with_fixtures.schema_view = deep_schema_view

    ref_fields = plugin_with_fixtures._find_reference_fields("EvidenceItem")
    excerpt_fields = plugin_with_fixtures._find_excerpt_fields("EvidenceItem")

    assert "reference" in ref_fields, (
        f"Should find 'reference' as a reference field on EvidenceItem. "
        f"Found: {ref_fields}"
    )
    assert "snippet" in excerpt_fields, (
        f"Should find 'snippet' as an excerpt field on EvidenceItem. "
        f"Found: {excerpt_fields}"
    )


def test_deep_schema_root_has_no_evidence_fields(
    plugin_with_fixtures, deep_schema_view
):
    """Root Community class should NOT have reference/excerpt fields itself."""
    plugin_with_fixtures.schema_view = deep_schema_view

    ref_fields = plugin_with_fixtures._find_reference_fields("Community")
    excerpt_fields = plugin_with_fixtures._find_excerpt_fields("Community")

    # Community has no implements annotations - should not match
    assert len(ref_fields) == 0, (
        f"Root Community class should have no reference fields, found: {ref_fields}"
    )
    assert len(excerpt_fields) == 0, (
        f"Root Community class should have no excerpt fields, found: {excerpt_fields}"
    )


# ---------------------------------------------------------------------------
# Full pipeline: test through linkml.validator.Validator (matches CLI path)
# ---------------------------------------------------------------------------


def test_full_pipeline_deep_nesting_invalid(tmp_path):
    """End-to-end test through Validator (same as CLI 'validate data').

    This uses the full linkml.validator.Validator pipeline to ensure the
    plugin is correctly wired up and receives deeply nested data.
    """
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for fixture_file in FIXTURES_DIR.glob("*.md"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    for fixture_file in FIXTURES_DIR.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        rate_limit_delay=0.0,
    )
    plugin = ReferenceValidationPlugin(config=config)

    validator = Validator(
        schema=str(DEEP_SCHEMA),
        validation_plugins=[plugin],
    )

    instance_invalid = {
        "name": "Test Community",
        "members": [
            {
                "taxon_name": "Species A",
                "evidence": [
                    {
                        "reference": "PMID:TEST001",
                        "snippet": "fabricated text not in reference",
                    }
                ],
            }
        ],
        "interactions": [
            {
                "interaction_name": "some interaction",
                "evidence": [
                    {
                        "reference": "PMID:TEST002",
                        "snippet": "another fabricated snippet",
                    }
                ],
            }
        ],
    }

    report = validator.validate(instance_invalid, target_class="Community")
    ref_results = [
        r for r in report.results if r.type == "reference_validation"
    ]
    assert len(ref_results) >= 2, (
        f"Full pipeline should catch invalid snippets in deeply nested "
        f"evidence. Expected >= 2, got {len(ref_results)}. "
        f"All results: {[r.message for r in report.results]}"
    )


def test_full_pipeline_deep_nesting_valid(tmp_path):
    """End-to-end: valid snippets in deeply nested evidence pass."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for fixture_file in FIXTURES_DIR.glob("*.md"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    for fixture_file in FIXTURES_DIR.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        rate_limit_delay=0.0,
    )
    plugin = ReferenceValidationPlugin(config=config)

    validator = Validator(
        schema=str(DEEP_SCHEMA),
        validation_plugins=[plugin],
    )

    with open(DATA_DIR / "test_data_deep_nesting_valid.yaml") as f:
        instance = _yaml.load(f)

    report = validator.validate(instance, target_class="Community")
    ref_results = [
        r for r in report.results if r.type == "reference_validation"
    ]
    assert len(ref_results) == 0, (
        f"Valid snippets should pass full pipeline, but got "
        f"{len(ref_results)} errors: {[r.message for r in ref_results]}"
    )
