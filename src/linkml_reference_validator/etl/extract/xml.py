"""JATS/PMC XML content extractor.

Changing what this yields for the same input may make already-cached text wrong
rather than merely older; see :mod:`linkml_reference_validator.etl.extract` for
when to bump cache versions. Changes confined to XML output use
``XML_EXTRACTION_CACHE_VERSION`` so PDF and HTML entries remain current.
"""

import codecs
import logging
import re
from html.entities import html5
from typing import Optional, Union

from bs4 import BeautifulSoup, CData, NavigableString, Tag  # type: ignore
from lxml import etree  # type: ignore[import-untyped]

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry
from linkml_reference_validator.etl.extract.untrusted_xml import (
    encode_for_parser,
    untrusted_xml_parser,
)
from linkml_reference_validator.etl.rules import STUB_NOTICE_PHRASES

logger = logging.getLogger(__name__)

#: Longest a placeholder notice can plausibly be. Stub phrases
#: (:data:`~linkml_reference_validator.etl.rules.STUB_NOTICE_PHRASES`) are only
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


#: Bound cached table evidence; headers count and truncation is always explicit.
MAX_TABLE_ROWS = 200


#: Elements that end a run of text. Their content is padded with spaces so a
#: neighbour never welds onto it: adjacent list items once read "itembeta".
#: Inline markup (italic, sub, xref, ...) is deliberately absent, so H<sub>2</sub>O
#: stays H2O.
BLOCK_ELEMENTS = frozenset(
    {
        "p",
        "break",
        "br",
        "list-item",
        "title",
        "label",
        "caption",
        "def-item",
        "term",
        "def",
        "disp-quote",
        "disp-formula",
        "fig",
        "boxed-text",
    }
)


def _block_text(node: Tag) -> str:
    """Keep inline text contiguous, separating blocks and excluding nested tables.

    Examples:
        >>> soup = BeautifulSoup("<p>a<break/>b <list><list-item>c</list-item>"
        ...     "<list-item>d</list-item></list> H<sub>2</sub>O</p>", "xml")
        >>> _block_text(soup.p)
        'a b c d H2O'
    """

    def walk(tag: Tag) -> str:
        """Render descendants without mutating the parsed document."""
        parts = []
        for child in tag.children:
            if type(child) in (NavigableString, CData):
                parts.append(str(child))
            elif isinstance(child, Tag) and child.name not in {"table", "table-wrap"}:
                value = walk(child)
                if child.name in BLOCK_ELEMENTS:
                    value = " " + value + " "
                parts.append(value)
        return "".join(parts)

    return " ".join(walk(node).split())


def _rendered_by_enclosing_paragraph(p: Tag) -> bool:
    """Whether an outer ``<p>`` already renders this one.

    JATS nests paragraphs (a ``<list>`` or ``<fig>`` inside ``<p>``), and the
    outer paragraph's text includes them, so emitting both repeated the text.
    Tables are the exception: :func:`_block_text` leaves them to the table
    pass, so a paragraph inside one is not covered by an outer paragraph.
    """
    for parent in p.parents:
        if parent.name in {"table", "table-wrap"}:
            return False
        if parent.name == "p":
            return True
    return False


#: Named entities XML predefines; these already mean what they say.
_XML_PREDEFINED_ENTITIES = frozenset({"amp", "lt", "gt", "quot", "apos"})

#: HTML named entities as numeric character references. JATS and PMC define
#: these in an external DTD that is never loaded, so without this the parser
#: drops ``&nbsp;`` and ``&mdash;`` and welds the words either side together.
_HTML_ENTITY_REFS = {
    name[:-1]: "".join(f"&#{ord(char)};" for char in value)
    for name, value in html5.items()
    if name.endswith(";") and name[:-1] not in _XML_PREDEFINED_ENTITIES
}

#: CDATA sections and comments are matched first so they are left verbatim.
_ENTITY_REFERENCE = re.compile(
    r"<!\[CDATA\[.*?\]\]>|<!--.*?-->|&([A-Za-z][A-Za-z0-9]*);", re.DOTALL
)
_ENTITY_DECLARATION = re.compile(r"<!ENTITY\s+([A-Za-z_][\w.-]*)")


def define_html_entities(data: Union[bytes, str]) -> Union[bytes, str]:
    """Rewrite undeclared HTML named entities as numeric character references.

    Bytes are rewritten in place without decoding, so a declared encoding
    stays true: references are ASCII and are only found in ASCII-compatible
    encodings. An entity the document declares itself keeps its declaration.

    Examples:
        >>> define_html_entities(b"A&nbsp;B &amp; C&mdash;D")
        b'A&#160;B &amp; C&#8212;D'
        >>> define_html_entities('<!DOCTYPE a [<!ENTITY nbsp "x">]><a>&nbsp;</a>')
        '<!DOCTYPE a [<!ENTITY nbsp "x">]><a>&nbsp;</a>'
        >>> define_html_entities("<a><![CDATA[&nbsp;]]>&unknownname;</a>")
        '<a><![CDATA[&nbsp;]]>&unknownname;</a>'
    """
    # latin-1 maps every byte to one code point and back, so bytes round-trip
    # exactly whatever encoding they are really in.
    text = data.decode("latin-1") if isinstance(data, bytes) else data
    declared = set(_ENTITY_DECLARATION.findall(text))

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        if name is None or name in declared:
            return match.group(0)
        return _HTML_ENTITY_REFS.get(name, match.group(0))

    text = _ENTITY_REFERENCE.sub(replace, text)
    return text.encode("latin-1") if isinstance(data, bytes) else text


#: Byte-order marks that announce an encoding without a declaration.
_UNICODE_BOMS = (
    codecs.BOM_UTF32_LE,
    codecs.BOM_UTF32_BE,
    codecs.BOM_UTF16_LE,
    codecs.BOM_UTF16_BE,
)
_ENCODING_DECLARATION = re.compile(rb"\s*<\?xml[^>]*\bencoding\s*=")


def _decode_undeclared(data: bytes) -> Union[bytes, str]:
    r"""Decode bytes that declare no encoding and are not valid UTF-8.

    With no BOM or declaration XML is UTF-8, and lxml reads it so. Invalid
    UTF-8 is then most likely a legacy single-byte file, which lxml would
    fill with replacement characters; it is read as windows-1252, the last
    resort BeautifulSoup used. BeautifulSoup's own sniffing is not used: it
    read undeclared UTF-8 as MacRoman.

    Examples:
        >>> _decode_undeclared(b"<a>caf\xe9</a>")
        '<a>café</a>'
        >>> _decode_undeclared("<a>café</a>".encode())
        b'<a>caf\xc3\xa9</a>'
        >>> _decode_undeclared(b'<?xml version="1.0" encoding="ISO-8859-1"?><a>\xe9</a>')[-6:]
        b'>\xe9</a>'
    """
    if data.startswith(_UNICODE_BOMS) or _ENCODING_DECLARATION.match(
        data.removeprefix(codecs.BOM_UTF8)
    ):
        return data
    try:  # sniffing untrusted external bytes
        data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("windows-1252", errors="replace")
    return data


def _parse(data: Union[bytes, str]) -> Optional[BeautifulSoup]:
    """Parse untrusted article XML, returning None when it holds no document.

    lxml parses first, with the settings every XML extractor shares (see
    :mod:`~linkml_reference_validator.etl.extract.untrusted_xml`): internal
    entities are expanded, external ones (XXE) and the network are never
    read, and libxml2's amplification limit stops billion laughs. Handing raw
    bytes straight to BeautifulSoup lost the whole body when the document
    declared an entity. The expanded tree is then re-read by BeautifulSoup,
    which the rendering below is written against.
    """
    if isinstance(data, bytes):
        data = _decode_undeclared(data)
    data, encoding = encode_for_parser(define_html_entities(data))
    parser = untrusted_xml_parser(encoding=encoding, recover=True)
    try:  # untrusted external input: recover mode still rejects an empty document
        root = etree.fromstring(data, parser)
    except etree.XMLSyntaxError as e:
        logger.info("Could not parse XML: %s", e)
        return None
    if root is None:
        logger.info("XML held no root element")
        return None
    if parser.error_log:
        # A truncated download parses to a partial tree; say so, or a cut-off
        # body is cached as if it were the whole article.
        logger.info(
            "XML was malformed; recovered from %d error(s), first: %s",
            len(parser.error_log),
            parser.error_log[0].message,
        )
    return BeautifulSoup(etree.tostring(root), "xml")


def _table_heading(wrap: Tag) -> str:
    """Read only the label/caption owned by this wrapper, not nested wrappers."""
    parts = []
    for name in ("label", "caption"):
        node = next(
            (n for n in wrap.find_all(name) if n.find_parent("table-wrap") is wrap),
            None,
        )
        if node is not None:
            parts.append(_block_text(node))
    return " ".join(part for part in parts if part)


def _tables_as_text(soup: BeautifulSoup) -> list[str]:
    """Render each table once in document order, using source cells, not a grid.

    Row/column spans are explicit annotations; values are never replicated or
    assigned to inferred columns. Header rows count toward the 200-row limit.
    """
    sections = []
    for table in soup.find_all(["table-wrap", "table", "table-wrap-foot"]):
        if table.find_parent(["sub-article", "response"]):
            continue
        if table.name == "table-wrap":
            heading = _table_heading(table)
            if heading:
                sections.append("## " + heading)
            continue
        wrap = table.find_parent("table-wrap")
        if wrap is None:
            # This pass targets JATS tables, not arbitrary XML layout tables.
            continue
        if table.name == "table-wrap-foot":
            note = _block_text(table)
            if note:
                sections.append(note)
            continue
        # Named wrapper headings were emitted at their own document position.
        heading = "" if _table_heading(wrap) else "Table"
        if table.find_parent(["table", "table-wrap"]) is not wrap:
            heading = "Nested table"
        rows = [
            row for row in table.find_all("tr") if row.find_parent("table") is table
        ]
        rendered = []
        for row in rows[:MAX_TABLE_ROWS]:
            cells = []
            for cell in row.find_all(["th", "td"]):
                if (
                    cell.find_parent("tr") is not row
                    or cell.find_parent("table") is not table
                ):
                    continue
                value = _block_text(cell).replace("\\", "\\\\").replace("|", "\\|")
                for span in ("rowspan", "colspan"):
                    if cell.has_attr(span) and str(cell[span]) != "1":
                        value += f" [{span}={cell[span]}]"
                cells.append(value)
            if cells:
                rendered.append("| " + " | ".join(cells) + " |")
        if len(rows) > MAX_TABLE_ROWS:
            rendered.append(f"[Table truncated after {MAX_TABLE_ROWS} rows.]")
        if rendered:
            sections.append(
                ("## " + heading + "\n\n" if heading else "") + "\n".join(rendered)
            )
    return sections


@ExtractorRegistry.register
class XMLExtractor(Extractor):
    """Extract body text from JATS/PMC article XML.

    Returns main-article body paragraphs followed by labeled tables and notes,
    including floats-group content. Sub-article and response content is excluded.
    Table cells retain inline text and explicitly annotate spans; the first 200
    source rows per table are retained, with a notice when rows are omitted.
    Returns None when neither body paragraphs nor table content exists, and when
    the body holds one of
    PMC's placeholder notices instead of the article itself.

    Examples:
        >>> xml = b"<article><body><p>Hello body.</p></body></article>"
        >>> XMLExtractor().extract(xml)
        'Hello body.'
        >>> table = "<article><table-wrap><table><tr><td>Yes</td></tr></table></table-wrap></article>"
        >>> XMLExtractor().extract(table)
        '## Table\\n\\n| Yes |'
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
        soup = _parse(data)
        if soup is None:
            return None
        body = next(
            (
                node
                for node in soup.find_all("body")
                if not node.find_parent(["sub-article", "response"])
            ),
            None,
        )
        paragraphs = (
            [
                p
                for p in body.find_all("p")
                if not p.find_parent(["sub-article", "response"])
                and not _rendered_by_enclosing_paragraph(p)
            ]
            if body
            else []
        )
        text = "\n\n".join(
            rendered
            for p in paragraphs
            if not p.find_parent("table-wrap") and (rendered := _block_text(p))
        )

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

        # Keep existing attribution/alternative prose that the renderer does not
        # emit. Table content must not inflate the stub check above.
        text = "\n\n".join(
            rendered
            for p in paragraphs
            if (rendered := _block_text(p))
            and not (
                p.find_parent("table-wrap")
                and p.find_parent(["label", "caption", "table", "table-wrap-foot"])
            )
        )
        return (
            "\n\n".join(part for part in [text, *_tables_as_text(soup)] if part) or None
        )
