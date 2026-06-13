"""PDF content extractor with a pluggable text backend.

The concrete text-extraction backend is selectable so heavier/structure-aware
backends (docling, grobid) can be swapped in later without touching callers.
"""

import io
import logging
from typing import Optional, Protocol

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)


class PDFTextBackend(Protocol):
    """Protocol for a PDF-to-text backend."""

    def extract_text(self, data: bytes) -> str:
        """Return extracted plain text for the given PDF bytes."""
        ...


class PypdfBackend:
    """Default PDF backend using ``pypdf`` (BSD-licensed, pure-python).

    Examples:
        >>> isinstance(PypdfBackend(), object)
        True
    """

    def extract_text(self, data: bytes) -> str:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)


_BACKENDS: dict[str, type] = {
    "pypdf": PypdfBackend,
}


@ExtractorRegistry.register
class PDFExtractor(Extractor):
    """Extract text from PDF bytes via a named backend.

    Examples:
        >>> PDFExtractor.formats()
        ['pdf']
    """

    def __init__(self, backend: str = "pypdf"):
        backend_class = _BACKENDS.get(backend)
        if backend_class is None:
            raise ValueError(
                f"Unknown pdf_backend '{backend}'. Available: {sorted(_BACKENDS)}"
            )
        self._backend = backend_class()

    @classmethod
    def formats(cls) -> list[str]:
        return ["pdf"]

    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        text = self._backend.extract_text(data)
        return text if text and text.strip() else None
