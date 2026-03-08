"""Tests for etl/sources/utils.py — extract_extra_fields utility."""

import pytest

from linkml_reference_validator.etl.sources.utils import extract_extra_fields


class TestExtractExtraFieldsEmpty:
    """Tests for empty / no-op cases."""

    def test_empty_field_map_returns_empty_string(self):
        """When no extra fields are configured, return empty string.

        Examples:
            >>> extract_extra_fields({"key": "value"}, {})
            ''
        """
        data = {"protocolSection": {"descriptionModule": {"briefSummary": "Some text."}}}
        assert extract_extra_fields(data, {}) == ""

    def test_empty_data_returns_empty_string(self):
        """When data dict is empty, return empty string."""
        assert extract_extra_fields({}, {"eligibility": "$.eligibility"}) == ""

    def test_both_empty_returns_empty_string(self):
        """When both data and field_map are empty, return empty string."""
        assert extract_extra_fields({}, {}) == ""


class TestExtractExtraFieldsSingleField:
    """Tests for single field extraction."""

    def test_top_level_field(self):
        """Extract a top-level field via JSONPath.

        Examples:
            >>> data = {"title": "My Title"}
            >>> result = extract_extra_fields(data, {"title": "$.title"})
            >>> "### title" in result
            True
            >>> "My Title" in result
            True
        """
        data = {"title": "My Title"}
        result = extract_extra_fields(data, {"title": "$.title"})
        assert "### title" in result
        assert "My Title" in result

    def test_nested_field(self):
        """Extract a deeply nested field via JSONPath."""
        data = {
            "protocolSection": {
                "eligibilityModule": {
                    "eligibilityCriteria": "Inclusion: age > 18\nExclusion: pregnant"
                }
            }
        }
        field_map = {
            "eligibility": "$.protocolSection.eligibilityModule.eligibilityCriteria"
        }
        result = extract_extra_fields(data, field_map)
        assert "### eligibility" in result
        assert "Inclusion: age > 18" in result
        assert "Exclusion: pregnant" in result

    def test_section_format(self):
        """Output uses ### heading followed by blank line then value."""
        data = {"foo": "bar content"}
        result = extract_extra_fields(data, {"foo": "$.foo"})
        assert result == "### foo\n\nbar content"

    def test_missing_field_omitted(self):
        """When JSONPath does not match, that field is silently omitted."""
        data = {"other": "something"}
        result = extract_extra_fields(data, {"eligibility": "$.eligibility"})
        assert result == ""

    def test_none_value_omitted(self):
        """When JSONPath matches a None value, that field is omitted."""
        data = {"eligibility": None}
        result = extract_extra_fields(data, {"eligibility": "$.eligibility"})
        assert result == ""

    def test_empty_string_value_omitted(self):
        """When JSONPath matches an empty string, that field is omitted."""
        data = {"eligibility": ""}
        result = extract_extra_fields(data, {"eligibility": "$.eligibility"})
        assert result == ""


class TestExtractExtraFieldsMultipleFields:
    """Tests for multiple field extraction."""

    def test_multiple_fields_all_present(self):
        """All matching fields appear as separate labeled sections."""
        data = {
            "protocolSection": {
                "descriptionModule": {
                    "detailedDescription": "Detailed objectives here.",
                },
                "eligibilityModule": {
                    "eligibilityCriteria": "Must be over 18.",
                },
            }
        }
        field_map = {
            "detailed_description": "$.protocolSection.descriptionModule.detailedDescription",
            "eligibility": "$.protocolSection.eligibilityModule.eligibilityCriteria",
        }
        result = extract_extra_fields(data, field_map)
        assert "### detailed_description" in result
        assert "Detailed objectives here." in result
        assert "### eligibility" in result
        assert "Must be over 18." in result

    def test_multiple_fields_partial_match(self):
        """Only fields that exist in data are included; missing ones are skipped."""
        data = {
            "protocolSection": {
                "eligibilityModule": {
                    "eligibilityCriteria": "Must be over 18.",
                }
            }
        }
        field_map = {
            "eligibility": "$.protocolSection.eligibilityModule.eligibilityCriteria",
            "outcomes": "$.protocolSection.outcomesModule.primaryOutcomes",
        }
        result = extract_extra_fields(data, field_map)
        assert "### eligibility" in result
        assert "Must be over 18." in result
        assert "### outcomes" not in result

    def test_sections_separated_by_blank_lines(self):
        """Multiple sections are separated by double newlines."""
        data = {"a": "value_a", "b": "value_b"}
        field_map = {"a": "$.a", "b": "$.b"}
        result = extract_extra_fields(data, field_map)
        # Each section header is preceded by a blank line (except possibly the first)
        assert "\n\n" in result


class TestExtractExtraFieldsInvalidJSONPath:
    """Tests for malformed JSONPath expressions."""

    def test_invalid_jsonpath_omitted(self):
        """Invalid JSONPath expression is skipped, no exception raised."""
        data = {"foo": "bar"}
        result = extract_extra_fields(data, {"field": "not a valid $[[[jsonpath"})
        assert result == ""

    def test_invalid_jsonpath_does_not_affect_valid_fields(self):
        """An invalid JSONPath for one field does not prevent extraction of others."""
        data = {"foo": "bar"}
        field_map = {
            "bad": "not a valid $[[[jsonpath",
            "good": "$.foo",
        }
        result = extract_extra_fields(data, field_map)
        assert "### good" in result
        assert "bar" in result
        assert "### bad" not in result


class TestExtractExtraFieldsValueTypes:
    """Tests for non-string value types in the API response."""

    def test_integer_value_converted_to_string(self):
        """Integer values are converted to strings."""
        data = {"count": 42}
        result = extract_extra_fields(data, {"count": "$.count"})
        assert "42" in result

    def test_list_value_joined(self):
        """List values are joined into a readable string."""
        data = {"conditions": ["Fanconi Anemia", "Aplastic Anemia"]}
        result = extract_extra_fields(data, {"conditions": "$.conditions"})
        assert "### conditions" in result
        # The list value should appear in some readable form
        assert result != ""
