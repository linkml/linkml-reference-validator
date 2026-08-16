"""JATS/PMC XML content extractor."""

import logging
from typing import Optional

from bs4 import BeautifulSoup  # type: ignore

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)

#: Phrases appearing in the placeholder documents PMC serves in place of an
#: article whose full text it cannot supply.
STUB_NOTICE_PHRASES = (
    "does not allow downloading",
    "cannot be obtained",
    "not available from pmc",
    "full text is restricted",
    "access to the full text is restricted",
)

#: Longest a placeholder notice can plausibly be. Stub phrases are only
#: honoured below this length: a real article runs to tens of thousands of
#: characters and may legitimately use the same words - Morris 2019 restricts
#: an analysis "to up to 13,977,204 high quality HRC imputed variants", and a
#: bare substring scan discarded the entire 155 KB paper for saying so.
MAX_STUB_NOTICE_CHARS = 1000


def is_stub_notice(text: str) -> bool:
    """Report whether extracted text is a PMC placeholder rather than an article.

    Both conditions must hold: the text carries a placeholder phrase *and* it is
    short enough to be one. Length is what makes the phrases safe to match, so
    prose in a real article body can never be mistaken for a stub.

    Args:
        text: Text extracted from the article body

    Returns:
        True if the text is a placeholder notice rather than article content

    Examples:
        >>> is_stub_notice("The full text cannot be obtained from PMC.")
        True
        >>> is_stub_notice("Analysis was restricted to imputed variants.")
        False
        >>> long_article = "Analysis cannot be obtained here. " + "body text. " * 200
        >>> is_stub_notice(long_article)
        False
    """
    if len(text) > MAX_STUB_NOTICE_CHARS:
        return False

    lowered = text.lower()
    return any(phrase in lowered for phrase in STUB_NOTICE_PHRASES)


@ExtractorRegistry.register
class XMLExtractor(Extractor):
    """Extract body text from JATS/PMC article XML.

    Returns the concatenated text of paragraphs within the article ``<body>``.
    Returns None when there is no body content, and when the body holds one of
    PMC's placeholder notices instead of the article itself.

    Examples:
        >>> xml = b"<article><body><p>Hello body.</p></body></article>"
        >>> XMLExtractor().extract(xml)
        'Hello body.'
        >>> stub = b"<article><body><p>Text cannot be obtained from PMC.</p></body></article>"
        >>> XMLExtractor().extract(stub) is None
        True
    """

    @classmethod
    def formats(cls) -> list[str]:
        return ["xml"]

    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        text_data = data.decode("utf-8") if isinstance(data, bytes) else data

        soup = BeautifulSoup(text_data, "xml")
        body = soup.find("body")
        if not body:
            return None

        paragraphs = body.find_all("p")
        if not paragraphs:
            return None

        text = "\n\n".join(p.get_text() for p in paragraphs if p.get_text().strip())
        if not text.strip():
            return None

        # Judged on the extracted body, not the raw markup: a citation title or
        # a methods sentence elsewhere in the document says nothing about
        # whether PMC served us the article.
        if is_stub_notice(text):
            logger.debug("Discarding PMC placeholder notice instead of article text")
            return None

        return text
