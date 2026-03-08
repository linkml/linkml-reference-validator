"""Shared utilities for reference source ETL modules.

Provides helpers used across multiple built-in sources, such as extracting
user-configured extra fields from raw API responses.
"""

import logging

from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError

logger = logging.getLogger(__name__)


def extract_extra_fields(data: dict, field_map: dict[str, str]) -> str:
    """Extract extra fields from a raw API response using JSONPath expressions.

    For each entry in *field_map*, the corresponding JSONPath expression is
    evaluated against *data*.  Matching values are formatted as a labelled
    Markdown section (``### field_name``) and concatenated together.  Fields
    that produce no match, an empty value, or an invalid JSONPath expression
    are silently omitted.

    Args:
        data: Raw API response dictionary to extract from.
        field_map: Mapping of ``field_name`` → ``JSONPath expression``.
            Example: ``{"eligibility": "$.protocolSection.eligibilityModule.eligibilityCriteria"}``.

    Returns:
        A string of one or more ``### field_name\\n\\nvalue`` sections joined
        by ``\\n\\n``, or an empty string when nothing could be extracted.

    Examples:
        >>> extract_extra_fields({}, {})
        ''
        >>> extract_extra_fields({"title": "My Paper"}, {})
        ''
        >>> extract_extra_fields({}, {"eligibility": "$.eligibility"})
        ''
        >>> extract_extra_fields({"foo": "bar"}, {"foo": "$.foo"})
        '### foo\\n\\nbar'
        >>> result = extract_extra_fields(
        ...     {"a": "alpha", "b": "beta"},
        ...     {"a": "$.a", "b": "$.b"},
        ... )
        >>> "### a" in result and "### b" in result
        True
        >>> "alpha" in result and "beta" in result
        True
        >>> extract_extra_fields({"other": "x"}, {"missing": "$.missing"})
        ''
        >>> extract_extra_fields({"foo": "bar"}, {"bad": "not a valid $[[[jsonpath"})
        ''
    """
    if not field_map or not data:
        return ""

    sections: list[str] = []

    for field_name, jsonpath_expr in field_map.items():
        try:
            parsed = jsonpath_parse(jsonpath_expr)
        except JsonPathParserError as exc:
            logger.warning("Invalid JSONPath expression '%s' for field '%s': %s", jsonpath_expr, field_name, exc)
            continue

        matches = parsed.find(data)
        if not matches:
            continue

        raw_value = matches[0].value
        if raw_value is None:
            continue

        if isinstance(raw_value, list):
            text = " ".join(str(item) for item in raw_value if str(item).strip())
        else:
            text = str(raw_value)

        if not text.strip():
            continue

        sections.append(f"### {field_name}\n\n{text}")

    return "\n\n".join(sections)
