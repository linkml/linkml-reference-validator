"""URL reference source.

Fetches content from web URLs.

Examples:
    >>> from linkml_reference_validator.etl.sources.url import URLSource
    >>> URLSource.prefix()
    'url'
    >>> URLSource.can_handle("url:https://example.com")
    True
"""

import html
import logging
import re
from typing import Optional

import requests

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry
from linkml_reference_validator.etl.acquire import ContentAcquirer, sniff_format
from linkml_reference_validator.etl.extract.html import sanitize_html
from linkml_reference_validator.etl.extract.pdf import PDFExtractor

logger = logging.getLogger(__name__)

# Publishers that serve a PDF at one URL and its metadata page at a predictable
# sibling. Each rule is (pattern, replacement) for ``re.sub`` on the PDF URL.
# The landing page is consulted only for its ``citation_title`` meta tag.
LANDING_PAGE_RULES: list[tuple[str, str]] = [
    # J-STAGE: .../<article>/_pdf[/-char/ja] -> .../<article>/_article[/-char/ja]
    (r"^(https?://www\.jstage\.jst\.go\.jp/article/.+)/_pdf(/.*)?$", r"\1/_article\2"),
]

_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
_META_NAME = re.compile(r"""\bname\s*=\s*["']citation_title["']""", re.IGNORECASE)
_META_CONTENT = re.compile(r"""\bcontent\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)


@ReferenceSourceRegistry.register
class URLSource(ReferenceSource):
    """Fetch reference content from web URLs.

    Fetches HTML and plain text content. HTML keeps its markup but is
    sanitized (see :func:`sanitize_html`) so page scripts and attributes do not
    reach the cache. Plain text and XML are stored as fetched. Content is cached
    to disk like other sources.

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
                title=self._recover_pdf_title(url, data, config),
                content=text,
                content_type="full_text_pdf" if text else "unavailable",
                full_text_url=url,
            )

        content = self._decode(data, content_type_header)
        # Before sanitizing: citation_title lives in a <meta> attribute.
        title = self._extract_title(content, url)
        if "html" in content_type_header or sniff_format(data) == "html":
            content = sanitize_html(content)

        return ReferenceContent(
            reference_id=f"url:{url}",
            title=title,
            content=content,
            content_type="url",
        )

    def _recover_pdf_title(
        self, url: str, data: bytes, config: ReferenceValidationConfig
    ) -> str:
        """Find a real title for a PDF, falling back to its URL.

        Tries, in order: the ``citation_title`` of a landing page found by
        ``LANDING_PAGE_RULES``, then the PDF's embedded ``/Title``. When both
        fail the URL is returned, so ``title == url`` still means none was found.
        """
        landing = self._landing_page_url(url)
        if landing is not None:
            title = self._landing_page_title(landing, config)
            if title:
                return title
            logger.debug(f"No citation_title at landing page {landing} for {url}")

        embedded = PDFExtractor(backend=config.pdf_backend).extract_title(data)
        return embedded or url

    def _landing_page_title(
        self, landing: str, config: ReferenceValidationConfig
    ) -> Optional[str]:
        """Return the ``citation_title`` of a landing page, or None if it cannot be had."""
        try:  # external system boundary: the title is best-effort, the PDF is not
            page, content_type = ContentAcquirer().fetch_bytes(landing, config)
        except requests.RequestException as e:
            logger.debug(f"Landing page {landing} could not be fetched: {e}")
            return None
        if page is None:
            return None
        return self._citation_title(self._decode(page, (content_type or "").lower()))

    @staticmethod
    def _landing_page_url(url: str) -> Optional[str]:
        """Return the landing page for a PDF URL, if a rule in ``LANDING_PAGE_RULES`` matches.

        Examples:
            >>> URLSource._landing_page_url(
            ...     "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_pdf/-char/ja")
            'https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_article/-char/ja'
            >>> URLSource._landing_page_url("https://example.org/paper.pdf") is None
            True
        """
        for pattern, replacement in LANDING_PAGE_RULES:
            if re.match(pattern, url):
                return re.sub(pattern, replacement, url)
        return None

    @staticmethod
    def _citation_title(content: str) -> Optional[str]:
        """Return the ``citation_title`` meta tag's content, if present.

        Examples:
            >>> URLSource._citation_title('<meta name="citation_title" content="A &amp; B">')
            'A & B'
            >>> URLSource._citation_title("<meta content='Reversed' name='citation_title'>")
            'Reversed'
            >>> URLSource._citation_title("<title>Only a title</title>") is None
            True
        """
        for tag in _META_TAG.findall(content):
            if _META_NAME.search(tag):
                match = _META_CONTENT.search(tag)
                if match:
                    title = " ".join(html.unescape(match.group(2)).split())
                    if title:
                        return title
        return None

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

        Prefers a ``citation_title`` meta tag, then the <title> tag. Falls back to URL.

        Args:
            content: Page content
            url: URL of the page

        Returns:
            Extracted title or URL

        Examples:
            >>> source = URLSource()
            >>> source._extract_title("<html><title>Page Title</title></html>", "https://x.com")
            'Page Title'
            >>> source._extract_title(
            ...     '<title>Journal | Home</title><meta name="citation_title" content="Article">',
            ...     "https://x.com")
            'Article'
            >>> source._extract_title("plain text", "https://example.com/doc.txt")
            'https://example.com/doc.txt'
        """
        citation_title = self._citation_title(content)
        if citation_title:
            return citation_title

        # Look for HTML title tag (simple regex, no BeautifulSoup)
        match = re.search(r"<title[^>]*>([^<]+)</title>", content, re.IGNORECASE)
        if match:
            return match.group(1).strip()

        # Fall back to URL
        return url
