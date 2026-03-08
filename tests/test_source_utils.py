"""Tests for etl/sources/utils.py — extract_extra_fields and format_extra_fields_for_content."""

from linkml_reference_validator.etl.sources.utils import (
    extract_extra_fields,
    format_extra_fields_for_content,
)


class TestExtractExtraFieldsEmpty:
    """Tests for empty / no-op cases."""

    def test_empty_field_map_returns_empty_dict(self):
        """When no extra fields are configured, return empty dict.

        Examples:
            >>> extract_extra_fields({"key": "value"}, {})
            {}
        """
        data = {
            "protocolSection": {"descriptionModule": {"briefSummary": "Some text."}}
        }
        assert extract_extra_fields(data, {}) == {}

    def test_empty_data_returns_empty_dict(self):
        """When data dict is empty, return empty dict."""
        assert extract_extra_fields({}, {"eligibility": "$.eligibility"}) == {}

    def test_both_empty_returns_empty_dict(self):
        """When both data and field_map are empty, return empty dict."""
        assert extract_extra_fields({}, {}) == {}


class TestExtractExtraFieldsSingleField:
    """Tests for single field extraction."""

    def test_top_level_field(self):
        """Extract a top-level field via JSONPath.

        Examples:
            >>> data = {"title": "My Title"}
            >>> result = extract_extra_fields(data, {"title": "$.title"})
            >>> result == {"title": "My Title"}
            True
        """
        data = {"title": "My Title"}
        result = extract_extra_fields(data, {"title": "$.title"})
        assert result == {"title": "My Title"}

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
        assert result["eligibility"] == "Inclusion: age > 18\nExclusion: pregnant"

    def test_section_format_via_formatter(self):
        """format_extra_fields_for_content produces ### heading then value."""
        data = {"foo": "bar content"}
        extra = extract_extra_fields(data, {"foo": "$.foo"})
        assert format_extra_fields_for_content(extra) == "### foo\n\nbar content"

    def test_missing_field_omitted(self):
        """When JSONPath does not match, that field is silently omitted."""
        data = {"other": "something"}
        result = extract_extra_fields(data, {"eligibility": "$.eligibility"})
        assert result == {}

    def test_none_value_omitted(self):
        """When JSONPath matches a None value, that field is omitted."""
        data = {"eligibility": None}
        result = extract_extra_fields(data, {"eligibility": "$.eligibility"})
        assert result == {}

    def test_empty_string_value_omitted(self):
        """When JSONPath matches an empty string, that field is omitted."""
        data = {"eligibility": ""}
        result = extract_extra_fields(data, {"eligibility": "$.eligibility"})
        assert result == {}


class TestExtractExtraFieldsMultipleFields:
    """Tests for multiple field extraction."""

    def test_multiple_fields_all_present(self):
        """All matching fields appear in the result dict."""
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
        assert result["detailed_description"] == "Detailed objectives here."
        assert result["eligibility"] == "Must be over 18."

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
        assert result == {"eligibility": "Must be over 18."}

    def test_formatter_separates_sections_with_blank_lines(self):
        """Multiple sections are separated by double newlines."""
        data = {"a": "value_a", "b": "value_b"}
        field_map = {"a": "$.a", "b": "$.b"}
        extra = extract_extra_fields(data, field_map)
        formatted = format_extra_fields_for_content(extra)
        assert "\n\n" in formatted
        assert "### a" in formatted and "### b" in formatted


class TestExtractExtraFieldsInvalidJSONPath:
    """Tests for malformed JSONPath expressions."""

    def test_invalid_jsonpath_omitted(self):
        """Invalid JSONPath expression is skipped, no exception raised."""
        data = {"foo": "bar"}
        result = extract_extra_fields(data, {"field": "not a valid $[[[jsonpath"})
        assert result == {}

    def test_invalid_jsonpath_does_not_affect_valid_fields(self):
        """An invalid JSONPath for one field does not prevent extraction of others."""
        data = {"foo": "bar"}
        field_map = {
            "bad": "not a valid $[[[jsonpath",
            "good": "$.foo",
        }
        result = extract_extra_fields(data, field_map)
        assert result == {"good": "bar"}


class TestExtractExtraFieldsValueTypes:
    """Tests for non-string value types in the API response."""

    def test_integer_value_converted_to_string(self):
        """Integer values are converted to strings."""
        data = {"count": 42}
        result = extract_extra_fields(data, {"count": "$.count"})
        assert result == {"count": "42"}

    def test_list_value_joined(self):
        """List values are joined into a readable string."""
        data = {"conditions": ["Fanconi Anemia", "Aplastic Anemia"]}
        result = extract_extra_fields(data, {"conditions": "$.conditions"})
        assert "conditions" in result
        assert (
            "Fanconi Anemia" in result["conditions"]
            and "Aplastic Anemia" in result["conditions"]
        )


class TestFormatExtraFieldsForContent:
    """Tests for format_extra_fields_for_content helper."""

    def test_empty_dict_returns_empty_string(self):
        """Empty dict produces empty string."""
        assert format_extra_fields_for_content({}) == ""

    def test_single_field(self):
        """Single key-value formats as ### key then value."""
        assert format_extra_fields_for_content({"foo": "bar"}) == "### foo\n\nbar"

    def test_multiple_fields_order(self):
        """Dict order is preserved (insertion order in Python 3.7+)."""
        extra = {"a": "alpha", "b": "beta"}
        out = format_extra_fields_for_content(extra)
        assert out == "### a\n\nalpha\n\n### b\n\nbeta"
