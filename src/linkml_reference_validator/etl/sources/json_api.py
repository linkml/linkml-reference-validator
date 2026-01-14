"""JSON API reference source.

A configurable reference source that fetches data from any JSON API endpoint.
Field extraction is done via JSONPath expressions, allowing new sources to be
defined through configuration rather than Python code.

Examples:
    >>> from linkml_reference_validator.models import JSONAPISourceConfig
    >>> config = JSONAPISourceConfig(
    ...     prefix="MGNIFY",
    ...     url_template="https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}",
    ...     fields={
    ...         "title": "$.data.attributes.study-name",
    ...         "content": "$.data.attributes.study-abstract",
    ...     },
    ... )
    >>> source = JSONAPISource(config)
    >>> source._prefix
    'MGNIFY'
"""

import logging
import os
import re
import time
from typing import Optional

import requests
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError

from linkml_reference_validator.etl.sources.base import (
    ReferenceSource,
    ReferenceSourceRegistry,
)
from linkml_reference_validator.models import (
    JSONAPISourceConfig,
    ReferenceContent,
    ReferenceValidationConfig,
)

logger = logging.getLogger(__name__)


class JSONAPISource(ReferenceSource):
    """A configurable reference source that fetches from JSON APIs.

    Uses JSONPath expressions to extract fields from the API response.
    Supports environment variable interpolation in headers for authentication.

    Examples:
        >>> from linkml_reference_validator.models import JSONAPISourceConfig
        >>> config = JSONAPISourceConfig(
        ...     prefix="TEST",
        ...     url_template="https://api.example.com/{id}",
        ...     fields={"title": "$.name"},
        ... )
        >>> source = JSONAPISource(config)
        >>> source._prefix
        'TEST'
        >>> source.can_handle("TEST:123")
        True
        >>> source.can_handle("OTHER:123")
        False
    """

    def __init__(self, source_config: JSONAPISourceConfig):
        """Initialize with a source configuration.

        Args:
            source_config: Configuration specifying URL template, fields, etc.
        """
        self._config = source_config
        self._compiled_patterns = [
            re.compile(p) for p in source_config.id_patterns
        ]

    @classmethod
    def prefix(cls) -> str:
        """Return the prefix (not applicable for instance-based sources).

        Note: This is overridden per-instance via _prefix property.
        The classmethod exists to satisfy the abstract base class.

        Returns:
            Empty string (use _prefix property on instances)
        """
        return ""

    @property
    def _prefix(self) -> str:
        """Return the configured prefix for this instance."""
        return self._config.prefix

    def can_handle(self, reference_id: str) -> bool:  # type: ignore[override]
        """Check if this source can handle the given reference ID.

        Note: This is an instance method (not classmethod) because it needs access
        to the configured id_patterns. JSONAPISource instances are not registered
        directly with the registry; instead, register_json_api_source() creates
        wrapper classes with proper classmethod signatures.

        Matches if:
        1. Reference starts with the configured prefix, OR
        2. Bare ID matches one of the configured id_patterns

        Args:
            reference_id: Full reference ID (e.g., 'MGNIFY:MGYS00000596')

        Returns:
            True if this source can handle the reference

        Examples:
            >>> from linkml_reference_validator.models import JSONAPISourceConfig
            >>> config = JSONAPISourceConfig(
            ...     prefix="MGNIFY",
            ...     url_template="https://example.com/{id}",
            ...     fields={"title": "$.title"},
            ...     id_patterns=["^MGYS\\\\d+$"],
            ... )
            >>> source = JSONAPISource(config)
            >>> source.can_handle("MGNIFY:MGYS00000596")
            True
            >>> source.can_handle("MGYS00000596")
            True
            >>> source.can_handle("DOI:10.1234/test")
            False
        """
        # Check prefix match
        prefix = self._prefix
        pattern = rf"^{re.escape(prefix)}[:\s]"
        if re.match(pattern, reference_id, re.IGNORECASE):
            return True

        # Check bare ID patterns
        for compiled in self._compiled_patterns:
            if compiled.match(reference_id):
                return True

        return False

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch content from the JSON API.

        Args:
            identifier: The identifier without prefix (e.g., 'MGYS00000596')
            config: Validation configuration (for rate limiting, etc.)

        Returns:
            ReferenceContent if successful, None otherwise

        Examples:
            >>> from linkml_reference_validator.models import (
            ...     JSONAPISourceConfig, ReferenceValidationConfig
            ... )
            >>> source_config = JSONAPISourceConfig(
            ...     prefix="TEST",
            ...     url_template="https://api.example.com/{id}",
            ...     fields={"title": "$.name", "content": "$.description"},
            ... )
            >>> source = JSONAPISource(source_config)
            >>> val_config = ReferenceValidationConfig()
            >>> # Would fetch in real usage:
            >>> # result = source.fetch("123", val_config)
        """
        identifier = identifier.strip()
        time.sleep(config.rate_limit_delay)

        url = self._config.url_template.format(id=identifier)
        headers = self._interpolate_headers(self._config.headers)

        # Add default Accept header if not specified
        if "Accept" not in headers:
            headers["Accept"] = "application/json"

        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.warning(
                f"Failed to fetch {self._prefix}:{identifier} - status {response.status_code}"
            )
            return None

        data = response.json()

        # Extract fields using JSONPath
        extracted = self._extract_fields(data)

        # Build metadata dict
        metadata: dict = {}
        if self._config.store_raw_response:
            metadata["raw_response"] = data

        return ReferenceContent(
            reference_id=f"{self._prefix}:{identifier}",
            title=extracted.get("title"),
            content=extracted.get("content"),
            content_type="abstract_only" if extracted.get("content") else "unavailable",
            authors=extracted.get("authors"),
            journal=extracted.get("journal"),
            year=extracted.get("year"),
            doi=extracted.get("doi"),
            metadata=metadata,
        )

    def _extract_fields(self, data: dict) -> dict:
        """Extract fields from JSON data using configured JSONPath expressions.

        Args:
            data: JSON response data

        Returns:
            Dict with extracted field values

        Examples:
            >>> from linkml_reference_validator.models import JSONAPISourceConfig
            >>> config = JSONAPISourceConfig(
            ...     prefix="TEST",
            ...     url_template="https://example.com/{id}",
            ...     fields={"title": "$.name", "content": "$.desc"},
            ... )
            >>> source = JSONAPISource(config)
            >>> source._extract_fields({"name": "Test", "desc": "Description"})
            {'title': 'Test', 'content': 'Description'}
            >>> source._extract_fields({"name": "Test"})
            {'title': 'Test', 'content': None}
        """
        result: dict = {}
        for field_name, jsonpath_expr in self._config.fields.items():
            value = self._jsonpath_extract(data, jsonpath_expr)
            result[field_name] = value
        return result

    def _jsonpath_extract(self, data: dict, expression: str) -> Optional[str]:
        """Extract a single value using a JSONPath expression.

        Args:
            data: JSON data to extract from
            expression: JSONPath expression (e.g., '$.data.title')

        Returns:
            Extracted string value, or None if not found

        Examples:
            >>> from linkml_reference_validator.models import JSONAPISourceConfig
            >>> config = JSONAPISourceConfig(
            ...     prefix="TEST",
            ...     url_template="https://example.com/{id}",
            ...     fields={},
            ... )
            >>> source = JSONAPISource(config)
            >>> source._jsonpath_extract({"name": "Test"}, "$.name")
            'Test'
            >>> source._jsonpath_extract({"nested": {"value": "Deep"}}, "$.nested.value")
            'Deep'
            >>> source._jsonpath_extract({"arr": [1, 2, 3]}, "$.arr[0]")
            '1'
            >>> source._jsonpath_extract({"name": "Test"}, "$.missing") is None
            True
        """
        try:
            parsed = jsonpath_parse(expression)
            matches = parsed.find(data)
            if matches:
                value = matches[0].value
                # Convert to string if not already
                if isinstance(value, str):
                    return value
                elif value is not None:
                    return str(value)
        except JsonPathParserError as e:
            logger.warning(f"Invalid JSONPath expression '{expression}': {e}")
        return None

    def _interpolate_headers(self, headers: dict[str, str]) -> dict[str, str]:
        """Interpolate environment variables in header values.

        Replaces ${VAR_NAME} patterns with values from environment.

        Args:
            headers: Header dict with potential ${VAR} placeholders

        Returns:
            Headers with environment variables interpolated

        Examples:
            >>> import os
            >>> os.environ["TEST_KEY"] = "secret123"
            >>> from linkml_reference_validator.models import JSONAPISourceConfig
            >>> config = JSONAPISourceConfig(
            ...     prefix="TEST",
            ...     url_template="https://example.com/{id}",
            ...     fields={},
            ... )
            >>> source = JSONAPISource(config)
            >>> source._interpolate_headers({"Authorization": "Bearer ${TEST_KEY}"})
            {'Authorization': 'Bearer secret123'}
            >>> source._interpolate_headers({"X-Custom": "static"})
            {'X-Custom': 'static'}
        """
        result = {}
        pattern = re.compile(r"\$\{([^}]+)\}")

        for key, value in headers.items():

            def replace_env(match: re.Match) -> str:
                var_name = match.group(1)
                env_value = os.environ.get(var_name, "")
                if not env_value:
                    logger.warning(f"Environment variable '{var_name}' not set")
                return env_value

            result[key] = pattern.sub(replace_env, value)

        return result


def register_json_api_source(source_config: JSONAPISourceConfig) -> type[ReferenceSource]:
    """Register a JSON API source from configuration.

    Creates a unique subclass for the source and registers it with the registry.

    Args:
        source_config: Configuration for the source

    Returns:
        The registered source class

    Examples:
        >>> from linkml_reference_validator.models import JSONAPISourceConfig
        >>> from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
        >>> config = JSONAPISourceConfig(
        ...     prefix="EXAMPLE",
        ...     url_template="https://api.example.com/{id}",
        ...     fields={"title": "$.title"},
        ... )
        >>> # Clear existing to test registration
        >>> initial_count = len(ReferenceSourceRegistry.list_sources())
        >>> source_class = register_json_api_source(config)
        >>> source_class.prefix()
        'EXAMPLE'
        >>> len(ReferenceSourceRegistry.list_sources()) > initial_count
        True
    """
    # Create a unique class for this source configuration
    # This allows the registry to work with class-level prefix() method
    class_name = f"JSONAPISource_{source_config.prefix}"

    # Create a class that holds the configuration
    # We need to define proper methods, not lambdas, for correct binding

    class DynamicJSONAPISource(ReferenceSource):
        _source_config = source_config

        @classmethod
        def prefix(cls) -> str:
            return cls._source_config.prefix

        @classmethod
        def can_handle(cls, reference_id: str) -> bool:
            # Create instance to check (lightweight operation)
            instance = JSONAPISource(cls._source_config)
            return instance.can_handle(reference_id)

        def fetch(
            self, identifier: str, config: ReferenceValidationConfig
        ) -> Optional[ReferenceContent]:
            instance = JSONAPISource(self._source_config)
            return instance.fetch(identifier, config)

    # Give the class a unique name
    DynamicJSONAPISource.__name__ = class_name
    DynamicJSONAPISource.__qualname__ = class_name

    ReferenceSourceRegistry.register(DynamicJSONAPISource)
    return DynamicJSONAPISource
