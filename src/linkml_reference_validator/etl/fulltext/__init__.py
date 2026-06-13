"""Full-text providers (PMC, Unpaywall, OpenAlex, custom)."""

from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)

__all__ = ["FullTextProvider", "FullTextProviderRegistry"]
