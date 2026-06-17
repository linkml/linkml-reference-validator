"""URL reference source.

Fetches content from web URLs.

Examples:
    >>> from linkml_reference_validator.etl.sources.url import URLSource
    >>> URLSource.prefix()
    'url'
    >>> URLSource.can_handle("url:https://example.com")
    True
"""

import logging
import re
from typing import Optional

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry
from linkml_reference_validator.etl.acquire import ContentAcquirer
from linkml_reference_validator.etl.extract.pdf import PDFExtractor

logger = logging.getLogger(__name__)


@ReferenceSourceRegistry.register
class URLSource(ReferenceSource):
    """Fetch reference content from web URLs.

    Fetches HTML and plain text content. HTML is returned as-is (no parsing).
    Content is cached to disk like other sources.

    Examples:
        >>> source = URLSource()
        >>> source.prefix()
        'url'
        >>> source.can_handle("url:https://example.com")
        True
    """

    @classmethod
    def prefix(cls) -> str:
        """Return 'url' prefix.

        Examples:
            >>> URLSource.prefix()
            'url'
        """
        return "url"

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch content from a URL.

        Args:
            identifier: URL (without 'url:' prefix)
            config: Configuration including rate limiting

        Returns:
            ReferenceContent if successful, None otherwise

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> config = ReferenceValidationConfig()
            >>> source = URLSource()
            >>> # Would fetch in real usage:
            >>> # ref = source.fetch("https://example.com", config)
        """
        url = identifier.strip()

        # Stream through ContentAcquirer so the size cap, rate-limit delay, and
        # User-Agent are applied uniformly. A url: pointing at a large PDF would
        # otherwise be buffered entirely into memory by a plain requests.get.
        data, content_type = ContentAcquirer().fetch_bytes(url, config)
        if data is None:
            # non-200 or the size cap was exceeded (the acquirer logs the reason)
            return None

        content_type_header = (content_type or "").lower()
        is_pdf = data[:5] == b"%PDF-" or "application/pdf" in content_type_header

        if is_pdf:
            text = PDFExtractor(backend=config.pdf_backend).extract(
                data, content_type="application/pdf"
            )
            return ReferenceContent(
                reference_id=f"url:{url}",
                title=url,
                content=text,
                content_type="full_text_pdf" if text else "unavailable",
                full_text_url=url,
            )

        content = self._decode(data, content_type_header)
        title = self._extract_title(content, url)

        return ReferenceContent(
            reference_id=f"url:{url}",
            title=title,
            content=content,
            content_type="url",
        )

    def _decode(self, data: bytes, content_type: str) -> str:
        """Decode HTML/text bytes using the content-type charset, defaulting to UTF-8.

        Examples:
            >>> URLSource()._decode(b"caf\\xc3\\xa9", "text/html; charset=utf-8")
            'café'
            >>> URLSource()._decode(b"hi", "text/html")
            'hi'
        """
        charset = "utf-8"
        if "charset=" in content_type:
            candidate = content_type.split("charset=", 1)[1].split(";")[0].strip()
            if candidate:
                charset = candidate
        try:  # external system boundary: charset is server-declared and may be invalid
            return data.decode(charset, errors="replace")
        except LookupError:
            return data.decode("utf-8", errors="replace")

    def _extract_title(self, content: str, url: str) -> str:
        """Extract title from HTML content or use URL.

        Looks for <title> tag in HTML. Falls back to URL.

        Args:
            content: Page content
            url: URL of the page

        Returns:
            Extracted title or URL

        Examples:
            >>> source = URLSource()
            >>> source._extract_title("<html><title>Page Title</title></html>", "https://x.com")
            'Page Title'
            >>> source._extract_title("plain text", "https://example.com/doc.txt")
            'https://example.com/doc.txt'
        """
        # Look for HTML title tag (simple regex, no BeautifulSoup)
        match = re.search(r"<title[^>]*>([^<]+)</title>", content, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Fall back to URL
        return url
