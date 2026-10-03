"""Full-text providers (PMC, Unpaywall, OpenAlex, custom)."""

from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)

# Import providers to register them
from linkml_reference_validator.etl.fulltext.bioc import BioCFullTextProvider
from linkml_reference_validator.etl.fulltext.epmc import EuropePMCFullTextProvider
from linkml_reference_validator.etl.fulltext.epmc_preprint import EuropePMCPreprintProvider
from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider
from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider
from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider
from linkml_reference_validator.etl.fulltext.zotero import ZoteroFullTextProvider

__all__ = [
    "BioCFullTextProvider",
    "EuropePMCFullTextProvider",
    "EuropePMCPreprintProvider",
    "FullTextProvider",
    "FullTextProviderRegistry",
    "OpenAlexProvider",
    "PMCFullTextProvider",
    "UnpaywallProvider",
    "ZoteroFullTextProvider",
]
