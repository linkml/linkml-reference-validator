"""HTML content extractor.

Changing what this yields for the same input may make already-cached text wrong
rather than merely older; see :mod:`linkml_reference_validator.etl.extract` for
when to bump ``EXTRACTOR_CACHE_VERSION``.
"""

import copy
import logging
import re
from typing import Optional, Union

from bs4 import (  # type: ignore
    BeautifulSoup,
    CData,
    Comment,
    NavigableString,
    Tag,
)
from bs4.element import PreformattedString  # type: ignore

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry
from linkml_reference_validator.etl.rules import ARTICLE_BODY_SELECTORS

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

#: One CSS selector list for the article-body containers in
#: :data:`~linkml_reference_validator.etl.rules.ARTICLE_BODY_SELECTORS`.
ARTICLE_BODY_SELECTOR = ", ".join(ARTICLE_BODY_SELECTORS)


#: Elements that never hold reference text. Page scripts routinely carry signed
#: asset URLs and API-key parameters, which must not reach a committed cache.
#: ``meta``, ``link`` and ``base`` hold nothing but attributes, so once those
#: are stripped they would remain only as empty tags.
NON_CONTENT_TAGS = ("script", "style", "noscript", "template", "meta", "link", "base")

#: The only attributes that carry meaning for a quoted excerpt: table structure.
KEPT_ATTRIBUTES = frozenset({"rowspan", "colspan", "scope"})


#: Tags that start a new line in :func:`html_to_text`: the extractor's block
#: tags, plus the document-level and form containers a whole page also has.
TEXT_BREAK_TAGS = frozenset(BLOCK_LEVEL_TAGS) | {
    "body", "caption", "center", "details", "dialog", "fieldset", "form",
    "head", "html", "legend", "menu", "option", "summary", "tbody", "textarea",
    "tfoot", "thead", "title",
}

#: Between the cells of a table row. Normalization drops punctuation, so a
#: quote copied from a rendered row, with the cells separated by spaces, still
#: matches.
CELL_SEPARATOR = " | "


def _without_non_content(content: str) -> BeautifulSoup:
    """Parse a page, dropping ``NON_CONTENT_TAGS`` and comments."""
    soup = BeautifulSoup(content, "html.parser")
    for tag in soup.find_all(NON_CONTENT_TAGS):
        if not tag.decomposed:  # already gone with an enclosing non-content tag
            tag.decompose()
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    return soup


def sanitize_html(content: str) -> str:
    """Strip an HTML page to its body markup and text, for caching.

    Drops ``NON_CONTENT_TAGS`` and comments, and every attribute not in
    ``KEPT_ATTRIBUTES``. Markup is kept, unlike :class:`HTMLExtractor`, which
    flattens to plain text; this is for ``url:`` pages stored as HTML.

    Examples:
        >>> sanitize_html('<p class="x" onclick="f()">Hi<script>k=1</script><!-- c --></p>')
        '<p>Hi</p>'
        >>> sanitize_html('<head><meta charset="utf-8"><link rel="x"><title>T</title></head>')
        '<head><title>T</title></head>'
        >>> sanitize_html('<td rowspan="2" style="s">A</td>')
        '<td rowspan="2">A</td>'
        >>> sanitize_html("<pre><b>x</b>    <b>y</b></pre>")
        '<pre><b>x</b>    <b>y</b></pre>'
    """
    soup = _without_non_content(content)
    for tag in soup.find_all(True):
        tag.attrs = {k: v for k, v in tag.attrs.items() if k in KEPT_ATTRIBUTES}
    # Removed elements leave runs of indentation behind. Collapse each
    # whitespace-only gap to one break so a second pass changes nothing.
    soup.smooth()
    for text in soup.find_all(string=True):
        if text.strip() or text in ("\n", " ") or text.find_parent("pre"):
            continue
        text.replace_with("\n" if "\n" in text else " ")
    return str(soup)


def html_to_text(content: str) -> str:
    r"""Flatten a whole HTML page to readable text, for caching ``url:`` pages.

    Drops what :func:`sanitize_html` drops, then unwraps every inline tag in
    place and starts a new line at each block-level tag and ``<br>``. A table
    row becomes one line, its cells joined by ``CELL_SEPARATOR``. ``<pre>``
    keeps its whitespace; elsewhere whitespace runs collapse to one space, as
    a browser would render them. Entities are unescaped.

    Unlike :class:`HTMLExtractor`, which serves article text, nothing is
    narrowed to ``<article>`` or ``<main>`` and no ``<p>``-only shortcut is
    taken. Every text node of the sanitized markup appears, contiguous, in
    the result, so a quote that matched the markup still matches, and a quote
    through a link or bold text now matches too.

    Examples:
        >>> html_to_text('<p>Produced by <a href="/x">the City of Flint</a>.</p>')
        'Produced by the City of Flint.'
        >>> html_to_text("<p>The <b>Flint water crisis</b> was</p><ul><li>one</li><li>two</li></ul>")
        'The Flint water crisis was\none\ntwo'
        >>> html_to_text("<p>Line one<br>Line two</p>")
        'Line one\nLine two'
        >>> html_to_text("<table><tr><th>Gene</th><th>Finding</th></tr><tr><td>POLG</td><td>A &amp; B</td></tr></table>")
        'Gene | Finding\nPOLG | A & B'
        >>> html_to_text("<pre>x    y\n  z</pre>")
        'x    y\n  z'
        >>> html_to_text("<p>near (<i>GUSB</i>, <i>GRN</i>)\n   here</p><script>k=1</script>")
        'near (GUSB, GRN) here'
    """
    return "\n".join(_lines(_without_non_content(content)))


def _lines(node: Tag) -> list[str]:
    """The non-blank lines of ``node``'s text, the last one included."""
    lines: list[str] = []
    line: list[str] = []
    _flatten(node, lines, line)
    _end_line(lines, line)
    return lines


def _flatten(node: Tag, lines: list[str], line: list[str]) -> None:
    """Append ``node``'s text to ``lines``; ``line`` holds the line being built."""
    for child in node.children:
        if isinstance(child, PreformattedString) and not isinstance(child, CData):
            continue  # a doctype, declaration or processing instruction: not text
        elif isinstance(child, NavigableString):
            line.append(re.sub(r"\s+", " ", str(child)))
        elif not isinstance(child, Tag):
            continue
        elif child.name == "br":
            _end_line(lines, line)
        elif child.name == "pre":
            _end_line(lines, line)
            lines.extend(child.get_text().strip("\n").splitlines())
        elif child.name == "tr":
            _end_line(lines, line)
            cells = [_cell_text(cell) for cell in child.find_all(["td", "th"], recursive=False)]
            row = CELL_SEPARATOR.join(cell for cell in cells if cell)
            if row:
                lines.append(row)
        elif child.name in TEXT_BREAK_TAGS:
            _end_line(lines, line)
            _flatten(child, lines, line)
            _end_line(lines, line)
        else:
            _flatten(child, lines, line)


def _end_line(lines: list[str], line: list[str]) -> None:
    """Move the line being built onto ``lines``, unless it holds only whitespace."""
    text = re.sub(r" +", " ", "".join(line)).strip()
    if text:
        lines.append(text)
    line.clear()


def _cell_text(cell: Tag) -> str:
    """One table cell's text on one line, whatever blocks it holds.

    Examples:
        >>> _cell_text(BeautifulSoup("<td><p>a</p><p>b <i>c</i></p></td>", "html.parser").td)
        'a b c'
    """
    return " ".join(_lines(cell))


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
            '[role="navigation"], [role="doc-abstract"], '
            '[class*="abstract" i], [id*="abstract" i]'
        ):
            if tag.parent is not None:
                tag.decompose()

        body = soup.select_one(ARTICLE_BODY_SELECTOR)

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
                # A separately identified article body is a stronger boundary
                # than heading rank. Do not treat Methods/Results alone as one:
                # those headings may belong to a structured abstract.
                if body is not None and isinstance(sibling, Tag) and (
                    sibling is body or any(parent is sibling for parent in body.parents)
                ):
                    break
                if (
                    isinstance(sibling, Tag)
                    and re.fullmatch(r"h[1-6]", sibling.name)
                    and int(sibling.name[1]) <= level
                ):
                    break
                sibling.extract()
            heading.decompose()

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
            if heading.parent is None:
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

        # Headings establish that the selected region has a research body; they
        # must not filter its content. Otherwise Main/Case presentation or an
        # intervening Limitations section silently disappears from accepted text.
        if not sections and (
            body is None
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
