"""PDF content extractor with a pluggable text backend.

The concrete text-extraction backend is selectable so heavier/structure-aware
backends (docling, grobid) can be swapped in later without touching callers.
"""

import io
import logging
import re
from typing import Optional, Protocol, Union

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)


class PDFTextBackend(Protocol):
    """Protocol for a PDF-to-text backend."""

    def extract_text(self, data: bytes) -> str:
        """Return extracted plain text for the given PDF bytes."""
        ...

    def extract_title(self, data: bytes) -> Optional[str]:
        """Return the embedded document title, or None if there is none."""
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

    def extract_title(self, data: bytes) -> Optional[str]:
        """Read ``/Title`` from the document information dictionary.

        Examples:
            >>> PypdfBackend().extract_title(b"%PDF-1.4 truncated") is None
            True
        """
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError

        try:  # external data: a PDF can carry text yet have a broken trailer
            metadata = PdfReader(io.BytesIO(data)).metadata
        except PyPdfError as e:
            logger.debug(f"Could not read PDF metadata: {e}")
            return None
        if metadata is None:
            return None
        # pypdf returns /Title as whatever object it holds; only text is a title.
        title = metadata.title
        return str(title) if isinstance(title, str) else None


# Authoring tools stamp these into /Title in place of a real one.
_PLACEHOLDER_TITLE = re.compile(
    r"^(untitled(\s+document)?|microsoft (word|powerpoint) - .*|.*\.(pdf|docx?|rtf|odt|tex|indd))$",
    re.IGNORECASE,
)


def clean_pdf_title(title: Optional[str]) -> Optional[str]:
    """Return ``title`` stripped, or None if it is empty or a known placeholder.

    Examples:
        >>> clean_pdf_title("  Canine Distemper in Dogs ")
        'Canine Distemper in Dogs'
        >>> clean_pdf_title("Microsoft Word - draft_v3.doc") is None
        True
        >>> clean_pdf_title("paper.pdf") is None
        True
        >>> clean_pdf_title("Untitled") is None
        True
        >>> clean_pdf_title("") is None
        True
        >>> clean_pdf_title(None) is None
        True
    """
    if title is None:
        return None
    title = " ".join(title.split())
    if not title or _PLACEHOLDER_TITLE.match(title):
        return None
    return title


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

    def extract(
        self, data: Union[bytes, str], *, content_type: Optional[str] = None
    ) -> Optional[str]:
        # The base accepts str for text formats, but a PDF is binary: decoded
        # text cannot be reparsed as one, so say so rather than failing deep
        # inside the backend.
        if isinstance(data, str):
            raise TypeError("PDF extraction requires bytes, not decoded text")
        text = self._backend.extract_text(data)
        return text if text and text.strip() else None

    def extract_title(self, data: bytes) -> Optional[str]:
        """Return the PDF's embedded title, or None if absent or a placeholder.

        Examples:
            >>> PDFExtractor().extract_title(b"%PDF-1.4 truncated") is None
            True
        """
        return clean_pdf_title(self._backend.extract_title(data))
