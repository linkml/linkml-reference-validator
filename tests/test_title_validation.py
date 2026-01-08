"""Tests for title validation against dcterms:title."""

import pytest
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
    ValidationSeverity,
)
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)


@pytest.fixture
def config(tmp_path):
    """Create a test configuration."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
    )


@pytest.fixture
def validator(config):
    """Create a validator."""
    return SupportingTextValidator(config)


@pytest.fixture
def plugin(config):
    """Create a validation plugin."""
    return ReferenceValidationPlugin(config=config)


class TestTitleValidation:
    """Tests for title validation in SupportingTextValidator."""

    def test_validate_title_exact_match(self, validator, mocker):
        """Test title validation with exact match."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate(
            "protein functions",
            "PMID:123",
            expected_title="Role of JAK1 in Cell Signaling",
        )

        assert result.is_valid is True
        assert result.severity == ValidationSeverity.INFO

    def test_validate_title_case_insensitive(self, validator, mocker):
        """Test title validation is case insensitive."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate(
            "protein functions",
            "PMID:123",
            expected_title="role of jak1 in cell signaling",
        )

        assert result.is_valid is True

    def test_validate_title_whitespace_normalization(self, validator, mocker):
        """Test title validation normalizes whitespace."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate(
            "protein functions",
            "PMID:123",
            expected_title="Role  of  JAK1  in  Cell  Signaling",
        )

        assert result.is_valid is True

    def test_validate_title_punctuation_normalization(self, validator, mocker):
        """Test title validation normalizes punctuation."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate(
            "protein functions",
            "PMID:123",
            expected_title="Role of JAK1 in Cell-Signaling",
        )

        assert result.is_valid is True

    def test_validate_title_mismatch(self, validator, mocker):
        """Test title validation fails on mismatch."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate(
            "protein functions",
            "PMID:123",
            expected_title="A Completely Different Title",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "Title mismatch" in result.message

    def test_validate_title_greek_letter_normalization(self, validator, mocker):
        """Test title validation handles Greek letters."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="α-catenin Function in Cells",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate(
            "protein functions",
            "PMID:123",
            expected_title="alpha-catenin Function in Cells",
        )

        assert result.is_valid is True

    def test_validate_title_with_trailing_period(self, validator, mocker):
        """Test title validation handles trailing punctuation."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling.",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate(
            "protein functions",
            "PMID:123",
            expected_title="Role of JAK1 in Cell Signaling",
        )

        assert result.is_valid is True

    def test_validate_title_not_substring(self, validator, mocker):
        """Test title validation is exact, not substring matching."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling",
            content="The protein functions in cell cycle regulation.",
        )

        # A partial title should NOT match
        result = validator.validate(
            "protein functions",
            "PMID:123",
            expected_title="Role of JAK1",  # Missing "in Cell Signaling"
        )

        assert result.is_valid is False
        assert "Title mismatch" in result.message


class TestTitleValidationStandalone:
    """Tests for standalone title validation without excerpt."""

    def test_validate_title_only(self, validator, mocker):
        """Test validating title alone without supporting text."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate_title(
            "PMID:123",
            expected_title="Role of JAK1 in Cell Signaling",
        )

        assert result.is_valid is True
        assert result.severity == ValidationSeverity.INFO

    def test_validate_title_only_mismatch(self, validator, mocker):
        """Test title-only validation fails on mismatch."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title="Role of JAK1 in Cell Signaling",
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate_title(
            "PMID:123",
            expected_title="Wrong Title",
        )

        assert result.is_valid is False
        assert "Title mismatch" in result.message

    def test_validate_title_only_no_reference_title(self, validator, mocker):
        """Test title validation when reference has no title."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            title=None,
            content="The protein functions in cell cycle regulation.",
        )

        result = validator.validate_title(
            "PMID:123",
            expected_title="Some Title",
        )

        assert result.is_valid is False
        assert "no title" in result.message.lower()

    def test_validate_title_only_fetch_fails(self, validator, mocker):
        """Test title validation when reference fetching fails."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = None

        result = validator.validate_title(
            "PMID:123",
            expected_title="Some Title",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "Could not fetch reference" in result.message


class TestPluginTitleFieldDiscovery:
    """Tests for title field discovery in the plugin."""

    def test_find_title_fields_dcterms(self, plugin, mocker):
        """Test finding title fields implementing dcterms:title."""
        mock_class_def = mocker.MagicMock()
        mock_slot = mocker.MagicMock()
        mock_slot.implements = ["dcterms:title"]

        plugin.schema_view = mocker.MagicMock()
        plugin.schema_view.get_class.return_value = mock_class_def
        plugin.schema_view.class_slots.return_value = ["reference_title", "other_field"]
        plugin.schema_view.induced_slot.side_effect = lambda name, cls: (
            mock_slot if name == "reference_title" else None
        )

        fields = plugin._find_title_fields("Evidence")

        assert "reference_title" in fields

    def test_find_title_fields_slot_uri(self, plugin, mocker):
        """Test finding title fields via slot_uri dcterms:title."""
        mock_class_def = mocker.MagicMock()
        mock_slot = mocker.MagicMock()
        mock_slot.implements = None
        mock_slot.slot_uri = "dcterms:title"

        plugin.schema_view = mocker.MagicMock()
        plugin.schema_view.get_class.return_value = mock_class_def
        plugin.schema_view.class_slots.return_value = ["title", "other_field"]
        plugin.schema_view.induced_slot.side_effect = lambda name, cls: (
            mock_slot if name == "title" else mocker.MagicMock(implements=None, slot_uri=None)
        )

        fields = plugin._find_title_fields("Evidence")

        assert "title" in fields

    def test_find_title_fields_fallback(self, plugin, mocker):
        """Test fallback to 'title' slot name."""
        mock_class_def = mocker.MagicMock()
        mock_slot = mocker.MagicMock()
        mock_slot.implements = None
        mock_slot.slot_uri = None

        plugin.schema_view = mocker.MagicMock()
        plugin.schema_view.get_class.return_value = mock_class_def
        plugin.schema_view.class_slots.return_value = ["title", "other_field"]
        plugin.schema_view.induced_slot.return_value = mock_slot

        fields = plugin._find_title_fields("Evidence")

        assert "title" in fields


class TestPluginTitleValidation:
    """Tests for title validation in the plugin process flow."""

    def test_validate_with_title_field(self, plugin, mocker):
        """Test validation includes title field from data."""
        mock_validate = mocker.patch.object(plugin.validator, "validate")
        mock_result = mocker.MagicMock()
        mock_result.is_valid = True
        mock_result.severity.value = "INFO"
        mock_validate.return_value = mock_result

        # Setup schema view
        mock_slot_ref = mocker.MagicMock()
        mock_slot_ref.implements = ["linkml:authoritative_reference"]
        mock_slot_ref.range = None

        mock_slot_excerpt = mocker.MagicMock()
        mock_slot_excerpt.implements = ["linkml:excerpt"]
        mock_slot_excerpt.range = None

        mock_slot_title = mocker.MagicMock()
        mock_slot_title.implements = ["dcterms:title"]
        mock_slot_title.slot_uri = None
        mock_slot_title.range = None

        plugin.schema_view = mocker.MagicMock()
        plugin.schema_view.get_class.return_value = mocker.MagicMock()
        plugin.schema_view.class_slots.return_value = [
            "reference",
            "supporting_text",
            "reference_title",
        ]
        plugin.schema_view.induced_slot.side_effect = lambda name, cls: {
            "reference": mock_slot_ref,
            "supporting_text": mock_slot_excerpt,
            "reference_title": mock_slot_title,
        }.get(name)

        instance = {
            "reference": "PMID:12345678",
            "supporting_text": "test quote",
            "reference_title": "Test Article Title",
        }

        list(plugin._validate_instance(instance, "Evidence", ""))

        # Verify validate was called with expected_title
        mock_validate.assert_called_once()
        call_kwargs = mock_validate.call_args
        # The title should have been passed as expected_title
        assert call_kwargs[1].get("expected_title") == "Test Article Title" or \
               (len(call_kwargs[0]) >= 3 and call_kwargs[0][2] == "Test Article Title")

    def test_validate_title_only_field(self, plugin, mocker):
        """Test validation of title-only (no excerpt)."""
        mock_validate_title = mocker.patch.object(plugin.validator, "validate_title")
        mock_result = mocker.MagicMock()
        mock_result.is_valid = False
        mock_result.message = "Title mismatch"
        mock_result.severity.value = "ERROR"
        mock_validate_title.return_value = mock_result

        # Setup schema view - only reference and title, no excerpt
        mock_slot_ref = mocker.MagicMock()
        mock_slot_ref.implements = ["linkml:authoritative_reference"]
        mock_slot_ref.range = None

        mock_slot_title = mocker.MagicMock()
        mock_slot_title.implements = ["dcterms:title"]
        mock_slot_title.slot_uri = None
        mock_slot_title.range = None

        plugin.schema_view = mocker.MagicMock()
        plugin.schema_view.get_class.return_value = mocker.MagicMock()
        plugin.schema_view.class_slots.return_value = [
            "reference",
            "reference_title",
        ]
        plugin.schema_view.induced_slot.side_effect = lambda name, cls: {
            "reference": mock_slot_ref,
            "reference_title": mock_slot_title,
        }.get(name)

        instance = {
            "reference": "PMID:12345678",
            "reference_title": "Expected Title",
        }

        results = list(plugin._validate_instance(instance, "Evidence", ""))

        # Should have validated title
        mock_validate_title.assert_called_once()
        assert len(results) == 1
        assert results[0].type == "reference_validation"
