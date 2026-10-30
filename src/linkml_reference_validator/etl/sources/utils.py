"""Shared utilities for reference source ETL modules.

Provides helpers used across multiple built-in sources, such as extracting
user-configured extra fields from raw API responses.
"""

import logging
from typing import Any, Optional

import requests  # type: ignore
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError

logger = logging.getLogger(__name__)


def extract_extra_fields(data: dict, field_map: dict[str, str]) -> dict[str, str]:
    """Extract extra fields from a raw API response using JSONPath expressions.

    For each entry in *field_map*, the corresponding JSONPath expression is
    evaluated against *data*.  Fields that produce no match, an empty value,
    or an invalid JSONPath expression are omitted from the result.

    Args:
        data: Raw API response dictionary to extract from.
        field_map: Mapping of ``field_name`` → ``JSONPath expression``.
            Example: ``{"eligibility": "$.protocolSection.eligibilityModule.eligibilityCriteria"}``.

    Returns:
        A dict mapping ``field_name`` → extracted text string for each field
        that had a non-empty value.  Use :func:`format_extra_fields_for_content`
        to turn this into text to append to reference content, and
        ``list(result.keys())`` for ``extra_fields_captured`` metadata.

    Examples:
        >>> extract_extra_fields({}, {})
        {}
        >>> extract_extra_fields({"title": "My Paper"}, {})
        {}
        >>> extract_extra_fields({}, {"eligibility": "$.eligibility"})
        {}
        >>> extract_extra_fields({"foo": "bar"}, {"foo": "$.foo"})
        {'foo': 'bar'}
        >>> result = extract_extra_fields(
        ...     {"a": "alpha", "b": "beta"},
        ...     {"a": "$.a", "b": "$.b"},
        ... )
        >>> result == {"a": "alpha", "b": "beta"}
        True
        >>> extract_extra_fields({"other": "x"}, {"missing": "$.missing"})
        {}
        >>> extract_extra_fields({"foo": "bar"}, {"bad": "not a valid $[[[jsonpath"})
        {}
    """
    if not field_map or not data:
        return {}

    result: dict[str, str] = {}

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

        result[field_name] = text

    return result


def format_extra_fields_for_content(extra: dict[str, str]) -> str:
    """Format an extra-fields dict as markdown sections for appending to reference content.

    Args:
        extra: Result of :func:`extract_extra_fields` (field_name → text).

    Returns:
        String of ``### field_name\\n\\ntext`` sections joined by ``\\n\\n``,
        or empty string if *extra* is empty.

    Examples:
        >>> format_extra_fields_for_content({})
        ''
        >>> format_extra_fields_for_content({"foo": "bar content"})
        '### foo\\n\\nbar content'
        >>> format_extra_fields_for_content({"a": "alpha", "b": "beta"})
        '### a\\n\\nalpha\\n\\n### b\\n\\nbeta'
    """
    if not extra:
        return ""
    return "\n\n".join(f"### {k}\n\n{v}" for k, v in extra.items())


def get_json(
    url: str,
    label: str,
    headers: Optional[dict[str, str]] = None,
    level: int = logging.WARNING,
) -> Optional[Any]:
    """GET ``url`` and return its JSON body, or None if it cannot be had.

    A network error, a timeout, a status other than 200, or a body that is not
    JSON (a maintenance page served on a 200) all give None, so the caller's
    "no result" path runs and the fetcher can fall back to a cached copy
    (#134). Each failure is logged at ``level``, naming ``label``.

    Args:
        url: The URL to fetch.
        label: What is being fetched, such as ``"DOI:10.1/x from Crossref"``.
        headers: Request headers.
        level: Log level for a failure; DEBUG where another source is tried next.

    Returns:
        The parsed JSON body, or None.

    Examples:
        >>> get_json("not a url", "a test record") is None  # no request is sent
        True
    """
    try:  # external system boundary: offline, DNS failure, timeout
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException as exc:
        logger.log(level, f"Failed to fetch {label}: {exc}")
        return None
    if response.status_code != 200:
        logger.log(level, f"Failed to fetch {label}: HTTP {response.status_code}")
        return None
    try:  # external data: a 200 can still carry an HTML error page
        return response.json()
    except ValueError as exc:
        logger.log(level, f"Failed to fetch {label}: the response is not JSON ({exc})")
        return None
