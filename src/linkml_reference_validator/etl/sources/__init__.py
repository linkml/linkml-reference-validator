"""Reference source plugins.

This package provides pluggable reference sources for fetching content
from various origins (PubMed, Crossref, local files, URLs, ClinicalTrials.gov).

Custom sources can be defined via YAML configuration using JSONAPISource.

Examples:
    >>> from linkml_reference_validator.etl.sources import ReferenceSourceRegistry
    >>> sources = ReferenceSourceRegistry.list_sources()
    >>> len(sources) >= 8
    True

    >>> # Register custom sources from config files
    >>> from linkml_reference_validator.etl.sources import register_custom_sources
    >>> count = register_custom_sources()
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
from linkml_reference_validator.etl.sources.entrez import (
    GEOSource,
    BioProjectSource,
    BioSampleSource,
)
from linkml_reference_validator.etl.sources.clinicaltrials import ClinicalTrialsSource

# Import JSON API source for programmatic use
from linkml_reference_validator.etl.sources.json_api import (
    JSONAPISource,
    register_json_api_source,
)

# Import loader for registering custom sources from config
from linkml_reference_validator.etl.sources.loader import (
    load_custom_sources,
    register_custom_sources,
)

__all__ = [
    "ReferenceSource",
    "ReferenceSourceRegistry",
    "PMIDSource",
    "DOISource",
    "FileSource",
    "URLSource",
    "GEOSource",
    "BioProjectSource",
    "BioSampleSource",
    "ClinicalTrialsSource",
    "JSONAPISource",
    "register_json_api_source",
    "load_custom_sources",
    "register_custom_sources",
]
