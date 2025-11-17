"""Integration tests for the validation plugin."""

import pytest
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)


@pytest.fixture
def config(tmp_path):
    """Create a test configuration."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
    )


@pytest.fixture
def plugin(config):
    """Create a validation plugin."""
    return ReferenceValidationPlugin(config=config)


def test_plugin_initialization(plugin):
    """Test plugin initializes correctly."""
    assert plugin.config is not None
    assert plugin.validator is not None
    assert plugin.schema_view is None  # Not set until pre_process


def test_plugin_initialization_with_params():
    """Test plugin initialization with individual parameters."""
    plugin = ReferenceValidationPlugin(
        cache_dir="/tmp/cache",
    )
    assert plugin.config.cache_dir.as_posix() == "/tmp/cache"


def test_extract_reference_id_string(plugin):
    """Test extracting reference ID from string."""
    ref_id = plugin._extract_reference_id("PMID:12345678")
    assert ref_id == "PMID:12345678"


def test_extract_reference_id_dict(plugin):
    """Test extracting reference ID from dict."""
    ref_id = plugin._extract_reference_id({"id": "PMID:12345678", "title": "Test"})
    assert ref_id == "PMID:12345678"

    ref_id = plugin._extract_reference_id({"reference_id": "PMID:12345678"})
    assert ref_id == "PMID:12345678"


def test_extract_reference_id_none(plugin):
    """Test extracting reference ID from invalid value."""
    ref_id = plugin._extract_reference_id(None)
    assert ref_id is None

    ref_id = plugin._extract_reference_id({"title": "Test"})
    assert ref_id is None


def test_find_reference_fields(plugin, mocker):
    """Test finding reference fields in schema."""
    mock_class_def = mocker.MagicMock()
    mock_slot = mocker.MagicMock()
    mock_slot.implements = ["linkml:authoritative_reference"]

    plugin.schema_view = mocker.MagicMock()
    plugin.schema_view.get_class.return_value = mock_class_def
    plugin.schema_view.class_slots.return_value = ["reference", "other_field"]
    plugin.schema_view.induced_slot.side_effect = lambda name, cls: (
        mock_slot if name == "reference" else None
    )

    fields = plugin._find_reference_fields("Evidence")

    assert "reference" in fields


def test_find_excerpt_fields(plugin, mocker):
    """Test finding excerpt fields in schema."""
    mock_class_def = mocker.MagicMock()
    mock_slot = mocker.MagicMock()
    mock_slot.implements = ["linkml:excerpt"]

    plugin.schema_view = mocker.MagicMock()
    plugin.schema_view.get_class.return_value = mock_class_def
    plugin.schema_view.class_slots.return_value = ["supporting_text", "other_field"]
    plugin.schema_view.induced_slot.side_effect = lambda name, cls: (
        mock_slot if name == "supporting_text" else None
    )

    fields = plugin._find_excerpt_fields("Evidence")

    assert "supporting_text" in fields


def test_validate_excerpt(plugin, mocker):
    """Test validating an excerpt."""
    mock_validate = mocker.patch.object(plugin.validator, "validate")
    mock_result = mocker.MagicMock()
    mock_result.is_valid = False
    mock_result.message = "Text not found"
    mock_result.severity.value = "ERROR"
    mock_validate.return_value = mock_result

    results = list(
        plugin._validate_excerpt(
            "test quote",
            "PMID:12345678",
            None,  # expected_title
            "evidence.supporting_text",
        )
    )

    assert len(results) == 1
    assert results[0].type == "reference_validation"
