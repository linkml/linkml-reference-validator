"""Base class and registry for full-text providers.

A provider, given cross-walked identifiers, returns a FullTextLocation that points
to (or directly contains) the full text of a reference. Providers are tried in a
configured order until one yields usable text.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)

logger = logging.getLogger(__name__)


class FullTextProvider(ABC):
    """Abstract base class for full-text providers."""

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """Return the provider name used in the configured chain (e.g. 'unpaywall')."""
        ...

    @abstractmethod
    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        """Return a FullTextLocation, or None if this provider cannot supply one."""
        ...


class FullTextProviderRegistry:
    """Registry mapping provider names to provider instances.

    Examples:
        >>> from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
        >>> FullTextProviderRegistry.get("nope") is None
        True
    """

    _by_name: dict[str, FullTextProvider] = {}

    @classmethod
    def register(cls, provider_class: type[FullTextProvider]) -> type[FullTextProvider]:
        """Register a provider class (usable as a decorator)."""
        cls._by_name[provider_class.name()] = provider_class()
        logger.debug(f"Registered full-text provider: {provider_class.name()}")
        return provider_class

    @classmethod
    def register_instance(cls, name: str, provider: FullTextProvider) -> None:
        """Register a pre-built provider instance under ``name`` (for custom providers)."""
        cls._by_name[name] = provider
        logger.debug(f"Registered full-text provider instance: {name}")

    @classmethod
    def get(cls, name: str) -> Optional[FullTextProvider]:
        """Return the provider registered under ``name``, or None."""
        return cls._by_name.get(name)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered providers (for testing)."""
        cls._by_name = {}
