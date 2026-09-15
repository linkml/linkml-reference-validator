"""JATS/PMC XML content extractor.

Changing what this yields for the same input may make already-cached text wrong
rather than merely older; see :mod:`linkml_reference_validator.etl.extract` for
when to bump ``EXTRACTOR_CACHE_VERSION``.
"""

import logging
from typing import Optional, Union

from bs4 import BeautifulSoup  # type: ignore

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)

#: Phrases appearing in the placeholder documents PMC serves in place of an
#: article whose full text it cannot supply. Deliberately broad, because the
#: length gate below - not the wording - is what keeps matching safe. PMC
#: phrases these notices several ways ("access to this article is
#: restricted", "full text is restricted", ...), and an exhaustive list would
#: trade the old false positives for false negatives.
STUB_NOTICE_PHRASES = (
    "restricted",
    "does not allow downloading",
    "cannot be obtained",
    "not available from pmc",
)

#: Longest a placeholder notice can plausibly be. Stub phrases are only
#: honoured below this length: a real article runs to tens of thousands of
#: characters and may legitimately use the same words - Morris 2019 restricts
#: an analysis "to up to 13,977,204 high quality HRC imputed variants", and a
#: bare substring scan discarded the entire 155 KB paper for saying so.
MAX_STUB_NOTICE_CHARS = 1000

#: Shortest text any source will accept as full text rather than a stub.
#: Kept here beside MAX_STUB_NOTICE_CHARS, and imported by every gate, so the
#: two can be reasoned about together in one place.
#:
#: They move together, but their safe directions are opposite. Raising the
#: notice length to catch a longer wording is safe. LOWERING it - the tempting
#: fix for a short erratum discarded for saying "restricted" - would drag this
#: floor down too and start admitting stubs in the band it just vacated. Only
#: the XML path runs is_stub_notice, so on the HTML paths this floor is the
#: sole defence. Lower the notice length only by pinning this to a literal
#: first.
MIN_FULLTEXT_CHARS = MAX_STUB_NOTICE_CHARS


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
        >>> is_stub_notice("Access to this article is restricted.")
        True
        >>> is_stub_notice("A brief note about the assay.")
        False

        The same words inside a real article body are not a stub, however
        many ways PMC might have phrased its notice:

        >>> article = "Analysis was restricted to imputed variants. " + "Body. " * 200
        >>> is_stub_notice(article)
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

    def extract(
        self, data: Union[bytes, str], *, content_type: Optional[str] = None
    ) -> Optional[str]:
        # Passed through untouched, bytes or str. Decoding bytes here would
        # assume UTF-8 and raise on any article declaring another encoding;
        # re-encoding str here would leave that declaration contradicting the
        # bytes. The parser gets both cases right on its own.
        soup = BeautifulSoup(data, "xml")
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
            # Logged at info, not debug: silently discarding an article is what
            # made the original over-matching bug so hard to spot.
            logger.info(
                "Discarding a %d-character PMC placeholder notice; no full text "
                "was served for this article",
                len(text),
            )
            return None

        return text
