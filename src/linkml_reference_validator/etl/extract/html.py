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

    Whitespace around inline markup is preserved, so text spanning italicised
    gene symbols survives extraction intact.

    Examples:
        >>> html = b"<html><body><p>Hi</p></body></html>"
        >>> HTMLExtractor().extract(html)
        'Hi'
        >>> genes = b"<html><body><p>near (<i>GUSB</i>, <i>GRN</i>) here</p></body></html>"
        >>> HTMLExtractor().extract(genes)
        'near (GUSB, GRN) here'
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
            # get_text() with no arguments, deliberately: strip=True would trim
            # every markup-delimited run before joining them, welding words to
            # their neighbours across inline tags. "(<i>GUSB</i>, <i>GRN</i>,
            # and <i>NEU1</i>)" became "(GUSB,GRN, andNEU1)", breaking every
            # curated snippet that spans an italicised gene symbol. Trimming
            # the finished paragraph instead keeps the source's own spacing.
            texts = (p.get_text().strip() for p in paragraphs)
            text = "\n\n".join(t for t in texts if t)
            if text:
                return text

        text = scope.get_text(separator="\n", strip=True)
        return text if text.strip() else None
