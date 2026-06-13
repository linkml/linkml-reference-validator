"""JATS/PMC XML content extractor."""

import logging
from typing import Optional

from bs4 import BeautifulSoup  # type: ignore

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)


@ExtractorRegistry.register
class XMLExtractor(Extractor):
    """Extract body text from JATS/PMC article XML.

    Returns the concatenated text of paragraphs within the article ``<body>``.
    Returns None when there is no body content (e.g. restricted articles).

    Examples:
        >>> xml = b"<article><body><p>Hello body.</p></body></article>"
        >>> XMLExtractor().extract(xml)
        'Hello body.'
    """

    @classmethod
    def formats(cls) -> list[str]:
        return ["xml"]

    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        text_data = data.decode("utf-8") if isinstance(data, bytes) else data

        if "cannot be obtained" in text_data.lower() or "restricted" in text_data.lower():
            return None

        soup = BeautifulSoup(text_data, "xml")
        body = soup.find("body")
        if not body:
            return None

        paragraphs = body.find_all("p")
        if not paragraphs:
            return None

        text = "\n\n".join(p.get_text() for p in paragraphs if p.get_text().strip())
        return text if text.strip() else None
