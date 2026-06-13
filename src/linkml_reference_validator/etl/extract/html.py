"""HTML content extractor."""

import logging
from typing import Optional

from bs4 import BeautifulSoup  # type: ignore

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)


@ExtractorRegistry.register
class HTMLExtractor(Extractor):
    """Extract readable text from HTML bytes.

    Prefers an ``<article>`` or main content region; falls back to all paragraph
    text, then to the whole document text.

    Examples:
        >>> html = b"<html><body><p>Hi</p></body></html>"
        >>> HTMLExtractor().extract(html)
        'Hi'
    """

    @classmethod
    def formats(cls) -> list[str]:
        return ["html"]

    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        soup = BeautifulSoup(data, "html.parser")

        for tag in soup(["script", "style"]):
            tag.decompose()

        region = soup.find("article") or soup.find("main")
        scope = region if region is not None else soup

        paragraphs = scope.find_all("p")
        if paragraphs:
            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            if text.strip():
                return text

        text = scope.get_text(separator="\n", strip=True)
        return text if text.strip() else None
