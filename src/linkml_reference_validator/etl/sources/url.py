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
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

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
        time.sleep(config.rate_limit_delay)

        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
        }

        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Failed to fetch URL:{url} - status {response.status_code}")
            return None

        content = response.text
        title = self._extract_title(content, url)

        return ReferenceContent(
            reference_id=f"url:{url}",
            title=title,
            content=content,
            content_type="url",
        )

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
