"""Full-text providers (PMC, Unpaywall, OpenAlex, custom)."""

from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)

# Import providers to register them
from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider
from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

__all__ = [
    "FullTextProvider",
    "FullTextProviderRegistry",
    "UnpaywallProvider",
    "OpenAlexProvider",
]
