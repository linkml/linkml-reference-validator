"""Base class and registry for content extractors.

An extractor turns raw downloaded bytes (PDF/HTML/XML/text) into plain text.

Examples:
    >>> from linkml_reference_validator.etl.extract.base import Extractor
    >>> issubclass(Extractor, object)
    True
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class Extractor(ABC):
    """Abstract base class for content extractors.

    Subclasses declare the formats they handle and implement ``extract``.
    """

    @classmethod
    @abstractmethod
    def formats(cls) -> list[str]:
        """Return the format keys this extractor handles (e.g. ['pdf'])."""
        ...

    @abstractmethod
    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        """Extract plain text from ``data``; return None if nothing usable."""
        ...


class ExtractorRegistry:
    """Registry mapping format keys to extractor instances.

    Examples:
        >>> from linkml_reference_validator.etl.extract.base import ExtractorRegistry
        >>> ExtractorRegistry.get("nope") is None
        True
    """

    _by_format: dict[str, Extractor] = {}

    @classmethod
    def register(cls, extractor_class: type[Extractor]) -> type[Extractor]:
        """Register an extractor class (usable as a decorator)."""
        instance = extractor_class()
        for fmt in extractor_class.formats():
            cls._by_format[fmt] = instance
            logger.debug(f"Registered extractor for format: {fmt}")
        return extractor_class

    @classmethod
    def get(cls, fmt: str) -> Optional[Extractor]:
        """Return the extractor for ``fmt``, or None if none registered."""
        return cls._by_format.get(fmt)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered extractors (for testing)."""
        cls._by_format = {}
