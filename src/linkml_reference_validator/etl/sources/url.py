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

        if self._is_bot_challenge(content):
            # An HTTP 200 carrying a challenge page. Nothing about the reference
            # is known, so this is a transient failure, not an absence: caching
            # it would record an interstitial's <title> as the paper's title.
            logger.warning(
                "Bot-check page returned for %s; not caching it. Retry from an "
                "unblocked network, or cite the record by identifier (PMID, DOI) "
                "rather than by URL.",
                url,
            )
            return None

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

    #: Phrases a bot-check page carries. Matched against the ``<title>``, or
    #: against the whole document only when it is too short to be an article --
    #: a paper *about* CAPTCHAs contains these words in its prose, and
    #: discarding it would be worse than caching an interstitial.
    _BOT_CHALLENGE_PHRASES = (
        "checking your browser",
        "just a moment",
        "unusual traffic",
        "verifying you are human",
        "enable javascript and cookies",
        "please verify you are a human",
    )

    #: A challenge page is small. PMC's is ~21 KB against ~150-240 KB for an
    #: article, so this is well clear of both.
    _BOT_CHALLENGE_MAX_CHARS = 60_000

    @classmethod
    def _is_bot_challenge(cls, content: str) -> bool:
        """Is this a bot-check interstitial rather than the requested document?

        PMC and Cloudflare both serve these on an HTTP 200, so the status code
        cannot distinguish them and the title becomes the reference title
        (dismech#12867: "expected 'Pharmacotherapy for Alcohol Use Disorder...'
        but got 'Checking your browser'").

        Deliberately conservative -- it fires on the title, or on a body too
        short to be an article. A real paper discussing bot detection is longer
        than the cap and does not carry the phrase in its title.

        Args:
            content: The decoded response body

        Returns:
            True if the response looks like a challenge page

        Examples:
            >>> URLSource._is_bot_challenge(
            ...     "<title>Checking your browser before accessing</title>")
            True
            >>> URLSource._is_bot_challenge("<title>A real paper</title>" + "x" * 70000)
            False
        """
        lowered = content.lower()
        title_match = re.search(r"<title[^>]*>([^<]*)</title>", lowered, re.IGNORECASE)
        if title_match and any(
            phrase in title_match.group(1) for phrase in cls._BOT_CHALLENGE_PHRASES
        ):
            return True
        if len(content) <= cls._BOT_CHALLENGE_MAX_CHARS and any(
            phrase in lowered for phrase in cls._BOT_CHALLENGE_PHRASES
        ):
            return True
        return False

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
