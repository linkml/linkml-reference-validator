"""PDF content extractor with a pluggable text backend.

The concrete text-extraction backend is selectable so heavier/structure-aware
backends (docling, grobid) can be swapped in later without touching callers.
"""

import io
import logging
from typing import Optional, Protocol, Union

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry
from linkml_reference_validator.etl.rules import PDF_PLACEHOLDER_TITLE

logger = logging.getLogger(__name__)


class UnreadablePDFError(ValueError):
    """The bytes are not a PDF a backend can read: truncated, corrupt or empty."""


class PDFTextBackend(Protocol):
    """Protocol for a PDF-to-text backend.

    PDF bytes come from the network, so they may be truncated or corrupt. A
    backend raises :class:`UnreadablePDFError` for those, whatever its parser
    raises, and never returns a title it could not read.
    """

    def extract_text(self, data: bytes) -> str:
        """Return extracted plain text for the given PDF bytes.

        Raises:
            UnreadablePDFError: The bytes cannot be read as a PDF.
        """
        ...

    def extract_title(self, data: bytes) -> Optional[str]:
        """Return the embedded document title, or None if there is none or it cannot be read."""
        ...


class PypdfBackend:
    """Default PDF backend using ``pypdf`` (BSD-licensed, pure-python).

    Examples:
        >>> isinstance(PypdfBackend(), object)
        True
    """

    def extract_text(self, data: bytes) -> str:
        """Extract the text of every page.

        Examples:
            >>> try:
            ...     PypdfBackend().extract_text(b"%PDF-1.7 truncated")
            ... except UnreadablePDFError:
            ...     print("unreadable")
            unreadable
        """
        from pypdf import PdfReader

        # External data. Damaged input raises PyPdfError, but also KeyError,
        # AttributeError, ValueError, TypeError or IndexError from deep inside
        # the parser (seen on a fuzzed corpus, pinned in the tests), so every
        # failure is caught here, as the fetcher's full-text path does (#122).
        try:
            reader = PdfReader(io.BytesIO(data))
            return "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            raise UnreadablePDFError(f"{type(e).__name__}: {e}") from e

    def extract_title(self, data: bytes) -> Optional[str]:
        """Read ``/Title`` from the document information dictionary.

        Examples:
            >>> PypdfBackend().extract_title(b"%PDF-1.4 truncated") is None
            True
        """
        from pypdf import PdfReader

        # External data: a PDF can carry text yet have a broken trailer, and,
        # as for the text, pypdf raises more than PyPdfError on damaged input.
        try:
            metadata = PdfReader(io.BytesIO(data)).metadata
            title = metadata.title if metadata is not None else None
        except Exception as e:
            logger.debug(f"Could not read PDF metadata: {type(e).__name__}: {e}")
            return None
        # pypdf returns /Title as whatever object it holds; only text is a title.
        return str(title) if isinstance(title, str) else None


def clean_pdf_title(title: Optional[str]) -> Optional[str]:
    """Return ``title`` stripped, or None if it is empty or a known placeholder.

    Placeholders are :data:`~linkml_reference_validator.etl.rules.PDF_PLACEHOLDER_TITLE`.

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
    if not title or PDF_PLACEHOLDER_TITLE.match(title):
        return None
    return title


UNMAPPED_GLYPH = "\ufffd"
"""Stand-in for a glyph the PDF gave no Unicode mapping (U+FFFD)."""


def replace_unmapped_glyphs(text: str) -> tuple[str, int]:
    """Replace NUL characters with U+FFFD and return the text and the count.

    pypdf emits ``\\x00`` for glyphs with no ToUnicode mapping, usually
    fi/fl/ffi ligatures but sometimes digits or minus signs, so the right
    character cannot be guessed. U+FFFD keeps the loss visible and countable
    while making the text valid for tools like grep, which treat NUL as binary.

    Examples:
        >>> replace_unmapped_glyphs("in\\x00ammation")
        ('in\ufffdammation', 1)
        >>> replace_unmapped_glyphs("inflammation")
        ('inflammation', 0)
    """
    count = text.count("\x00")
    return text.replace("\x00", UNMAPPED_GLYPH), count


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
        self,
        data: Union[bytes, str],
        *,
        content_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Optional[str]:
        """Extract text from PDF bytes; ``source`` (e.g. a URL) names it in logs.

        Returns None for a PDF with no text, and for bytes that cannot be read
        as one (a truncated download, a corrupt or empty file), with a warning:
        callers then record the reference as unavailable (#122). A caller that
        must tell those two apart uses :meth:`read_text`.

        Examples:
            >>> PDFExtractor().extract(b"%PDF-1.7 truncated") is None
            True
        """
        try:
            return self.read_text(data, source=source)
        except UnreadablePDFError as e:
            origin = f" from {source}" if source else ""
            logger.warning(f"Could not read PDF{origin}: {e}")
            return None

    def read_text(self, data: Union[bytes, str], *, source: Optional[str] = None) -> Optional[str]:
        """Like :meth:`extract`, but raise for bytes that cannot be read as a PDF.

        The full-text chain treats an unreadable download as a transient error
        worth retrying, not as "this article has no text", so it needs the
        difference.

        Raises:
            UnreadablePDFError: The bytes cannot be read as a PDF.

        Examples:
            >>> try:
            ...     PDFExtractor().read_text(b"")
            ... except UnreadablePDFError:
            ...     print("unreadable")
            unreadable
        """
        # The base accepts str for text formats, but a PDF is binary: decoded
        # text cannot be reparsed as one, so say so rather than failing deep
        # inside the backend.
        if isinstance(data, str):
            raise TypeError("PDF extraction requires bytes, not decoded text")
        # Replace here rather than in a backend so every backend gets it.
        text, unmapped = replace_unmapped_glyphs(self._backend.extract_text(data))
        if unmapped:
            origin = f" from {source}" if source else ""
            logger.warning(
                f"PDF text{origin} has {unmapped} unmapped glyph(s), replaced with U+FFFD"
            )
        return text if text and text.strip() else None

    def extract_title(self, data: bytes) -> Optional[str]:
        """Return the PDF's embedded title, or None if absent or a placeholder.

        Examples:
            >>> PDFExtractor().extract_title(b"%PDF-1.4 truncated") is None
            True
        """
        return clean_pdf_title(self._backend.extract_title(data))
