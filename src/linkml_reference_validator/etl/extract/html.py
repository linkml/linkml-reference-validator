"""HTML content extractor."""

import copy
import logging
from typing import Optional, Union

from bs4 import BeautifulSoup, Tag  # type: ignore

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)

#: Tags whose boundaries are real text breaks. Used by the whole-document
#: fallback to separate blocks without touching inline markup, so that a
#: separator never lands between a gene symbol and its surrounding
#: punctuation.
BLOCK_LEVEL_TAGS = (
    "address", "article", "aside", "blockquote", "div", "dd", "dl", "dt",
    "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "pre", "section",
    "table", "td", "th", "tr", "ul",
)


@ExtractorRegistry.register
class HTMLExtractor(Extractor):
    """Extract readable text from HTML markup, as bytes or as a string.

    Prefers an ``<article>`` or main content region; falls back to all paragraph
    text, then to the whole document text. Callers holding an already-parsed
    region of their own use :meth:`extract_scope` instead.

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

    def extract(
        self, data: Union[bytes, str], *, content_type: Optional[str] = None
    ) -> Optional[str]:
        soup = BeautifulSoup(data, "html.parser")
        region = soup.find("article") or soup.find("main")
        return self.extract_scope(region if region is not None else soup)

    def extract_scope(self, scope: Tag) -> Optional[str]:
        """Extract text from an already-selected region of parsed markup.

        Callers that have chosen their own region - a PMC ``div.article-body``,
        say - pass the tag straight in. Serialising it back to markup for
        ``extract`` would parse the whole body a second time, and would re-run
        the ``<article>``/``<main>`` selection *inside* a region the caller had
        already settled, silently narrowing to a nested one.

        The caller's tag is left untouched: extraction needs to strip markup
        and mark block boundaries, and doing that in place would edit a
        document the caller still holds, as well as making a second call on
        the same region return different text from the first.

        Args:
            scope: A BeautifulSoup tag or soup to take the text of

        Returns:
            The region's text, or None if it holds none

        Examples:
            >>> from bs4 import BeautifulSoup
            >>> region = BeautifulSoup(
            ...     "<div><p>near (<i>GUSB</i>, <i>GRN</i>) here</p></div>",
            ...     "html.parser",
            ... ).find("div")
            >>> HTMLExtractor().extract_scope(region)
            'near (GUSB, GRN) here'
        """
        # Copied rather than edited in place. Cheaper than the serialise-and-
        # reparse this method replaced (measured ~14ms vs ~24ms on a 76 KB
        # body), and negligible beside the network fetch that produced the
        # markup - so purity here costs nothing that matters.
        scope = copy.copy(scope)

        # Dropped here rather than in extract(), because the PMC paths enter
        # through this method and a JSON-LD blob or stylesheet landing in
        # cached article text would corrupt every snippet checked against it.
        # bs4's get_text() also skips Script/Stylesheet strings by default,
        # but that is a library default to rely on, not a guarantee this
        # extractor makes.
        for tag in scope(["script", "style"]):
            tag.decompose()

        # Before either branch, so both agree: <br> carries no text of its own,
        # so bare get_text() would weld the lines it separates into
        # "Line oneLine two" - the same welding this extractor exists to avoid.
        for line_break in scope.find_all("br"):
            line_break.replace_with("\n")

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

        # Same hazard as the paragraph branch, one level down: a blanket
        # separator lands between *every* pair of markup-delimited runs, so
        # "(<i>GUSB</i>, <i>GRN</i>)" would come out as "(\nGUSB\n,\nGRN\n)".
        # Marking block boundaries first means get_text() can then run bare,
        # keeping the source's own spacing inside each block.
        for block in scope.find_all(BLOCK_LEVEL_TAGS):
            block.insert_after("\n")

        text = scope.get_text().strip()
        return text if text else None
