"""HTML content extractor.

Changing what this yields for the same input may make already-cached text wrong
rather than merely older; see :mod:`linkml_reference_validator.etl.extract` for
when to bump ``EXTRACTOR_CACHE_VERSION``.
"""

import copy
import logging
import re
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
        # Straight to the private form: this soup was parsed here and is
        # discarded here, so the defensive copy extract_scope makes for
        # caller-owned tags would protect nobody and cost a full tree walk.
        return self._extract_scope(region if region is not None else soup)

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
        return self._extract_scope(copy.copy(scope))

    def extract_full_text(self, data: Union[bytes, str]) -> Optional[str]:
        """Extract an identifiable research body, rejecting ambiguous landing pages.

        This stricter entry point is for full-text acquisition only. A main or
        article tag, citation metadata, and a long abstract are not evidence of
        a full article. Prefer publisher body regions, otherwise require a
        narrative research section with paragraphs. Abstracts and navigation
        cannot supply that evidence. Unrecognised layouts conservatively return
        None so the caller can try another provider; no links are followed.

        Examples:
            >>> HTMLExtractor().extract_full_text('<main><p>Metadata</p></main>') is None
            True
        """
        soup = BeautifulSoup(data, "html.parser")
        for tag in soup.select(
            'nav, header, footer, aside, script, style, form, dialog, '
            '[role="navigation"], .abstract, #abstract, [role="doc-abstract"], '
            '[id^="Abs"], [class*="abstract"], [id*="abstract"]'
        ):
            if tag.parent is not None:
                tag.decompose()

        # Some publishers mark abstracts only by a heading. Remove that heading
        # and its following siblings through the next same-or-higher heading;
        # nested Methods/Results subheadings belong to the abstract, not the body.
        for heading in list(soup.find_all(re.compile(r"^h[1-6]$"))):
            if heading.parent is None or heading.get_text(" ", strip=True).lower() not in {
                "abstract", "summary"
            }:
                continue
            level = int(heading.name[1])
            for sibling in list(heading.next_siblings):
                if (
                    isinstance(sibling, Tag)
                    and re.fullmatch(r"h[1-6]", sibling.name)
                    and int(sibling.name[1]) <= level
                ):
                    break
                sibling.extract()
            heading.decompose()

        body = soup.select_one(
            '[itemprop="articleBody"], .article-text, #artText, '
            '.article-body, .article__body'
        )
        region = body if body is not None else soup.find("article") or soup.find("main")
        if region is None:
            return None

        research_heading = re.compile(
            r"^(?:\d+[.\s]*)?(?:introduction|background|(?:materials and |patients and )?methods|"
            r"results(?: and discussion)?|discussion|conclusions?)(?:\s*[:.]|$)",
            re.I,
        )
        sections = []
        for heading in region.find_all(re.compile(r"^h[2-6]$")):
            if not research_heading.match(heading.get_text(" ", strip=True)):
                continue
            section = heading.parent
            if section is None:
                continue
            # Copy the heading's bounded sibling run, also supporting flat
            # article layouts without a div/section around each heading.
            section = soup.new_tag("section")
            for sibling in heading.next_siblings:
                if (
                    isinstance(sibling, Tag)
                    and re.fullmatch(r"h[1-6]", sibling.name)
                    and int(sibling.name[1]) <= int(heading.name[1])
                ):
                    break
                section.append(copy.copy(sibling))
            if section.find("p"):
                sections.append(section)

        if sections:
            # Keep only the research sections when the outer region is a generic
            # article/main: repository metadata elsewhere must not be included.
            if body is None:
                texts = (self._extract_scope(s) for s in sections)
                return "\n\n".join(filter(None, texts)) or None
        elif (
            body is None
            or region.find(re.compile(r"^h[1-6]$"))
            or len(region.find_all("p")) < 2
        ):
            return None

        return self._extract_scope(region)

    def _extract_scope(self, scope: Tag) -> Optional[str]:
        """Extract text from a region this extractor is free to modify.

        For callers that own the tree and do not mind it being edited.
        Separated from :meth:`extract_scope` so the copy is paid for only
        where it buys something: a caller-owned tag. ``extract`` parses and
        discards its own soup, so it enters here directly. Anything reaching
        for this instead of the public method is opting out of that
        protection deliberately.
        """
        # Dropped here rather than in extract(), because the PMC paths enter
        # through this method and a JSON-LD blob or stylesheet landing in
        # cached article text would corrupt every snippet checked against it.
        # bs4's get_text() also skips Script/Stylesheet strings by default,
        # but that is a library default to rely on, not a guarantee this
        # extractor makes.
        for tag in scope.find_all(["script", "style"]):
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
