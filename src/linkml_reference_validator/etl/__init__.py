"""ETL modules for fetching and caching references."""

from linkml_reference_validator.etl.reference_fetcher import (
    FetchOutcome,
    ReferenceFetcher,
)
from linkml_reference_validator.etl.text_extractor import (
    ExtractedTextMatch,
    TextExtractor,
)

__all__ = ["ReferenceFetcher", "FetchOutcome", "TextExtractor", "ExtractedTextMatch"]
