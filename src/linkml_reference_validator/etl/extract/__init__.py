"""Content extractors (PDF, HTML, XML).

Changing what these produce for the same input does not rewrite the text they
already wrote to the reference cache, which is served in preference to a fetch.
When a change means previously cached text is *wrong* rather than merely older,
bump ``EXTRACTOR_CACHE_VERSION`` in
:mod:`linkml_reference_validator.etl.reference_fetcher` so existing entries are
re-fetched instead of keeping the old output forever.
"""

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

# Import extractors to register them
from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.extract.xml import (
    MIN_FULLTEXT_CHARS,
    XMLExtractor,
)
from linkml_reference_validator.etl.extract.pdf import PDFExtractor

__all__ = [
    "MIN_FULLTEXT_CHARS",
    "Extractor",
    "ExtractorRegistry",
    "HTMLExtractor",
    "XMLExtractor",
    "PDFExtractor",
]
