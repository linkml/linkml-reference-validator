"""Base class and registry for reference sources.

This module provides the plugin architecture for fetching reference content
from various sources (PMID, DOI, local files, URLs, etc.).

Examples:
    >>> from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
    >>> source = ReferenceSourceRegistry.get_source("PMID:12345678")
    >>> source.prefix()
    'PMID'
"""

import logging
import re
from abc import ABC, abstractmethod
from typing import Optional

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig

logger = logging.getLogger(__name__)


class ReferenceSource(ABC):
    """Abstract base class for reference content sources.

    Subclasses must implement:
    - prefix(): Return the prefix this source handles (e.g., 'PMID', 'DOI')
    - fetch(): Fetch content for a given identifier

    Examples:
        >>> class MySource(ReferenceSource):
        ...     @classmethod
        ...     def prefix(cls) -> str:
        ...         return "MY"
        ...     def fetch(self, identifier, config):
        ...         return None
        >>> MySource.prefix()
        'MY'
    """

    @classmethod
    @abstractmethod
    def prefix(cls) -> str:
        """Return the prefix this source handles.

        Returns:
            The prefix string (e.g., 'PMID', 'DOI', 'file', 'url')

        Examples:
            >>> from linkml_reference_validator.etl.sources.pmid import PMIDSource
            >>> PMIDSource.prefix()
            'PMID'
        """
        ...

    @classmethod
    def can_handle(cls, reference_id: str) -> bool:
        """Check if this source can handle the given reference ID.

        Default implementation checks if reference_id starts with the prefix.

        Args:
            reference_id: The full reference ID (e.g., 'PMID:12345678')

        Returns:
            True if this source can handle the reference

        Examples:
            >>> from linkml_reference_validator.etl.sources.pmid import PMIDSource
            >>> PMIDSource.can_handle("PMID:12345678")
            True
            >>> PMIDSource.can_handle("DOI:10.1234/test")
            False
        """
        prefix = cls.prefix()
        pattern = rf"^{re.escape(prefix)}[:\s]"
        return bool(re.match(pattern, reference_id, re.IGNORECASE))

    @abstractmethod
    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch content for the given identifier.

        Args:
            identifier: The identifier without prefix (e.g., '12345678' for PMID)
            config: Configuration for fetching

        Returns:
            ReferenceContent if successful, None otherwise
        """
        ...


class ReferenceSourceRegistry:
    """Registry of available reference sources.

    Sources are registered automatically when their modules are imported.
    The registry is used by ReferenceFetcher to dispatch to the appropriate source.

    Examples:
        >>> from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
        >>> sources = ReferenceSourceRegistry.list_sources()
        >>> len(sources) >= 4  # PMID, DOI, file, url
        True
    """

    _sources: list[type[ReferenceSource]] = []

    @classmethod
    def register(cls, source_class: type[ReferenceSource]) -> type[ReferenceSource]:
        """Register a source class.

        Can be used as a decorator.

        Args:
            source_class: The source class to register

        Returns:
            The source class (for decorator usage)

        Examples:
            >>> from linkml_reference_validator.etl.sources.base import (
            ...     ReferenceSource, ReferenceSourceRegistry
            ... )
            >>> @ReferenceSourceRegistry.register
            ... class TestSource(ReferenceSource):
            ...     @classmethod
            ...     def prefix(cls) -> str:
            ...         return "TEST"
            ...     def fetch(self, identifier, config):
            ...         return None
            >>> "TEST" in [s.prefix() for s in ReferenceSourceRegistry.list_sources()]
            True
        """
        if source_class not in cls._sources:
            cls._sources.append(source_class)
            logger.debug(f"Registered source: {source_class.prefix()}")
        return source_class

    @classmethod
    def get_source(cls, reference_id: str) -> Optional[type[ReferenceSource]]:
        """Find a source that can handle the given reference ID.

        Args:
            reference_id: The full reference ID (e.g., 'PMID:12345678')

        Returns:
            The source class if found, None otherwise

        Examples:
            >>> from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
            >>> ReferenceSourceRegistry.get_source("UNKNOWN:xyz") is None
            True
        """
        for source_class in cls._sources:
            if source_class.can_handle(reference_id):
                return source_class
        return None

    @classmethod
    def list_sources(cls) -> list[type[ReferenceSource]]:
        """List all registered sources.

        Returns:
            List of registered source classes

        Examples:
            >>> from linkml_reference_validator.etl.sources import ReferenceSourceRegistry
            >>> sources = ReferenceSourceRegistry.list_sources()
            >>> isinstance(sources, list)
            True
        """
        return list(cls._sources)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered sources (mainly for testing).

        Examples:
            >>> from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
            >>> ReferenceSourceRegistry.clear()
            >>> len(ReferenceSourceRegistry._sources)
            0
        """
        cls._sources = []
