"""Content extractors (PDF, HTML, XML)."""

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

# Import extractors to register them
from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.extract.xml import XMLExtractor
from linkml_reference_validator.etl.extract.pdf import PDFExtractor

__all__ = [
    "Extractor",
    "ExtractorRegistry",
    "HTMLExtractor",
    "XMLExtractor",
    "PDFExtractor",
]
