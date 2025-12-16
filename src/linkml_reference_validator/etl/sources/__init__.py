"""Reference source plugins.

This package provides pluggable reference sources for fetching content
from various origins (PubMed, Crossref, local files, URLs).

Examples:
    >>> from linkml_reference_validator.etl.sources import ReferenceSourceRegistry
    >>> sources = ReferenceSourceRegistry.list_sources()
    >>> len(sources) >= 4
    True
"""

from linkml_reference_validator.etl.sources.base import (
    ReferenceSource,
    ReferenceSourceRegistry,
)

# Import sources to register them
from linkml_reference_validator.etl.sources.pmid import PMIDSource
from linkml_reference_validator.etl.sources.doi import DOISource
from linkml_reference_validator.etl.sources.file import FileSource
from linkml_reference_validator.etl.sources.url import URLSource

__all__ = [
    "ReferenceSource",
    "ReferenceSourceRegistry",
    "PMIDSource",
    "DOISource",
    "FileSource",
    "URLSource",
]
