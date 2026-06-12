"""Tests that recursive traversal tolerates data keys not defined in the schema.

The plugin walks an instance's keys and looks up each one with
``SchemaView.induced_slot``. That call raises ``ValueError`` for unknown slots,
so any extra key in the data (a stray ``id``, a typo, a metadata field) used to
crash the whole validation instead of being skipped. These tests pin the
behaviour: unknown keys are ignored and known nested evidence is still reached.
"""

from pathlib import Path

import pytest
from linkml_runtime.utils.schemaview import SchemaView  # type: ignore[import-untyped]
from linkml.validator import Validator  # type: ignore[import-untyped]
from linkml.validator.validation_context import (  # type: ignore[import-untyped]
    ValidationContext,
)

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)


DATA_DIR = Path(__file__).parent / "data"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
SCHEMA = DATA_DIR / "test_schema.yaml"


def _make_cache(tmp_path):
    """Build a cache dir seeded with the tracked reference fixtures."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for fixture_file in FIXTURES_DIR.glob("*.md"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    for fixture_file in FIXTURES_DIR.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    return cache_dir


@pytest.fixture
def plugin(tmp_path):
    """Plugin with a cache seeded from the tracked fixtures."""
    config = ReferenceValidationConfig(
        cache_dir=_make_cache(tmp_path),
        rate_limit_delay=0.0,
    )
    return ReferenceValidationPlugin(config=config)


@pytest.fixture
def schema_view():
    """SchemaView for the shared test schema."""
    return SchemaView(str(SCHEMA))


def test_unknown_top_level_key_does_not_crash(plugin, schema_view):
    """An extra top-level key not in the schema must be skipped, not crash."""
    instance = {
        "id": "statement:001",  # not a slot on Statement
        "text": "Protein X functions in cell cycle regulation",
        "has_evidence": [
            {
                "reference": {"id": "PMID:TEST001", "title": "Study of Protein X"},
                "supporting_text": "Protein X functions in cell cycle regulation",
            }
        ],
    }

    context = ValidationContext(schema_view.schema, target_class="Statement")
    plugin.pre_process(context)

    # Should not raise ValueError for the unknown "id" slot.
    list(plugin.process(instance, context))


def test_unknown_nested_key_does_not_crash(plugin, schema_view):
    """An extra key on a nested object must be skipped, not crash."""
    instance = {
        "text": "Some statement",
        "has_evidence": [
            {
                "id": "evidence:001",  # not a slot on Evidence
                "category": "experimental",  # also not a slot
                "reference": {"id": "PMID:TEST001", "title": "Study of Protein X"},
                "supporting_text": "fabricated text not in the reference at all",
            }
        ],
    }

    context = ValidationContext(schema_view.schema, target_class="Statement")
    plugin.pre_process(context)

    # Traversal must still reach the evidence and reject the bad snippet.
    results = list(plugin.process(instance, context))
    assert len(results) > 0, (
        "Plugin should skip unknown nested keys but still validate the "
        "evidence's invalid supporting_text"
    )


def test_unknown_key_through_full_validator_pipeline(tmp_path):
    """End-to-end: an unknown key must not break the full Validator pipeline."""
    config = ReferenceValidationConfig(
        cache_dir=_make_cache(tmp_path),
        rate_limit_delay=0.0,
    )
    plugin = ReferenceValidationPlugin(config=config)
    validator = Validator(
        schema=str(SCHEMA),
        validation_plugins=[plugin],
    )

    instance = {
        "id": "statement:001",  # not a slot on Statement
        "text": "Some statement",
        "has_evidence": [
            {
                "reference": {"id": "PMID:TEST001"},
                "supporting_text": "fabricated text not in the reference at all",
            }
        ],
    }

    # The reference plugin must run without raising on the unknown "id" key.
    report = validator.validate(instance, target_class="Statement")
    ref_results = [r for r in report.results if r.type == "reference_validation"]
    assert len(ref_results) > 0, (
        "Full pipeline should reach the evidence and flag the invalid snippet "
        "even when the instance carries an unknown 'id' key"
    )
