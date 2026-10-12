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
from linkml_reference_validator.etl.extract.html import html_to_text
from linkml_reference_validator.etl.extract.pdf import PDFExtractor
from linkml_reference_validator.etl.rules import LANDING_PAGE_RULES

logger = logging.getLogger(__name__)

_META_TAG = re.compile(r"<meta\b[^>]*>", re.IGNORECASE)
# Attribute names follow whitespace. A \b boundary would also match inside
# data-name= and data-content=, since "-" is a word boundary.
_META_NAME = re.compile(r"""(?<=\s)name\s*=\s*["']citation_title["']""", re.IGNORECASE)
_META_CONTENT = re.compile(r"""(?<=\s)content\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)


@ReferenceSourceRegistry.register
class URLSource(ReferenceSource):
    """Fetch reference content from web URLs.

    Fetches HTML and plain text content. HTML is flattened to readable text
    (see :func:`html_to_text`), so page scripts and attributes do not reach the
    cache and a quote can run through a link or bold text. Plain text and XML
    are stored as fetched. Content is cached to disk like other sources.

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
        try:  # external system boundary: requests raises when offline or on timeout
            data, content_type = ContentAcquirer().fetch_bytes(url, config)
        except requests.RequestException as e:
            logger.warning(f"Failed to fetch {url}: {e}")
            return None
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
        # Before flattening: citation_title lives in a <meta> attribute.
        title = self._extract_title(content, url)
        if "html" in content_type_header or self._looks_like_html(data):
            content = html_to_text(content)

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
        for pattern, replacement in LANDING_PAGE_RULES.values():
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

    @staticmethod
    def _looks_like_html(data: bytes) -> bool:
        """Report whether a body is an HTML page, whatever its content type said.

        Skips a UTF-8 byte order mark and leading comments (a saved page often
        begins with one), then accepts a doctype, ``<html>``, ``<head>`` or
        ``<body>``. Text that merely mentions a tag is not a page.

        Examples:
            >>> URLSource._looks_like_html(b"\\xef\\xbb\\xbf<!DOCTYPE html><html>")
            True
            >>> URLSource._looks_like_html(b"<!-- saved -->\\n<html><body>")
            True
            >>> URLSource._looks_like_html(b"<head><title>T</title></head>")
            True
            >>> URLSource._looks_like_html(b"Notes on the <html> element")
            False
            >>> URLSource._looks_like_html(b'<?xml version="1.0"?><record/>')
            False
        """
        head = data[:8192].removeprefix(b"\xef\xbb\xbf").lstrip()
        while head.startswith(b"<!--"):
            end = head.find(b"-->")
            if end == -1:
                return False
            head = head[end + 3 :].lstrip()
        return sniff_format(head) == "html" or head[:5].lower() in (b"<head", b"<body")

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
