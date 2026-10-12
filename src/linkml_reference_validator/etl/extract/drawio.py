"""drawio extractor: the labels a ``.drawio`` diagram draws (#104).

A ``.drawio`` file is an ``<mxfile>`` of ``<diagram>`` pages. Each page holds
an ``<mxGraphModel>``, either as XML or compressed: base64 of raw-deflated,
URL-encoded XML. The model is a flat list of ``<mxCell>``, each naming its
``parent``; layers are the cells under the root cell, and the drawn cells are
those marked ``vertex`` or ``edge``. A cell may be wrapped in an
``<object>``/``<UserObject>`` that carries its id and label.

Output matches :class:`~linkml_reference_validator.etl.extract.svg.SVGExtractor`:
one paragraph per drawn label, lines joined by newlines, a blank line between
labels, then edge lines, ``"<source> <edge label> <target>"``. Here an edge's
``source`` and ``target`` are what drawio draws it between, so they need no
geometric check; the edge's stroke and both cells' labels must still be drawn.
The arrows give the direction: an edge drawn pointing back at its source reads
target first, and one pointing both ways or neither gives no edge line.

Only drawn text counts. Not read: cells that are ``visible="0"``, in a hidden
layer or group, or inside a ``collapsed`` group; labels switched off
(``noLabel``) or drawn with ``opacity``/``textOpacity`` 0, ``fontSize`` 0 or
no ``fontColor``; layer and page names, tooltips, styles and other attributes.
HTML labels (``html=1``) are read by
:func:`~linkml_reference_validator.etl.extract.svg.html_label_lines`, with the
same visibility rules as an SVG ``<foreignObject>``.

Fails closed (``None``) on a placeholder label (``placeholders="1"``), whose
text is computed from other attributes; on HTML that cannot be read
statically; on a page that is not valid base64, deflate or XML; and on a page
that inflates past ``MAX_DIAGRAM_BYTES``.

Changing what this yields may make cached text wrong; bump
``SVG_EXTRACTION_CACHE_VERSION``, which covers drawio as well.

Examples:
    >>> DrawioExtractor().extract(
    ...     b'<mxfile><diagram><mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/>'
    ...     b'<mxCell id="a" value="PTEN" vertex="1" parent="1"/></root></mxGraphModel></diagram></mxfile>')
    'PTEN'
"""

import base64
import binascii
import logging
import re
import zlib
from dataclasses import dataclass, field
from typing import Iterator, Optional, Union
from urllib.parse import unquote
from xml.sax.saxutils import escape as xml_escape

from lxml import etree  # type: ignore[import-untyped]

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry
from linkml_reference_validator.etl.extract.svg import (
    Unrenderable,
    html_label_lines,
    parse_untrusted_xml,
)
from linkml_reference_validator.matching import SVG_LABEL_SEPARATOR

logger = logging.getLogger(__name__)

#: The most a file's compressed pages may inflate to, together; past it, a
#: deflate bomb fails closed.
MAX_DIAGRAM_BYTES = 16 * 1024 * 1024

#: Elements that wrap a cell to give it an id, a label and other attributes.
CELL_WRAPPERS = frozenset({"object", "UserObject"})


@dataclass
class _Cell:
    """One ``<mxCell>``, with what a wrapper adds to it."""

    id: str
    parent: str
    label: str
    style: dict[str, str]
    attrs: dict[str, str]
    lines: list[str] = field(default_factory=list)

    @property
    def drawn(self) -> bool:
        return self.attrs.get("vertex") == "1" or self.attrs.get("edge") == "1"


def parse_style(style: str) -> dict[str, str]:
    """A drawio style string as a dict; bare names (shape names) map to "".

    Examples:
        >>> parse_style("text;html=1;fontColor=none;")
        {'text': '', 'html': '1', 'fontColor': 'none'}
    """
    parsed = {}
    for item in style.split(";"):
        key, _, value = item.partition("=")
        if key.strip():
            parsed[key.strip()] = value.strip()
    return parsed


def _number(value: Optional[str], default: float) -> float:
    """A style number, or ``default`` if absent or not a number.

    Examples:
        >>> _number("0", 100), _number(None, 100), _number("x", 100)
        (0.0, 100, 100)
    """
    if value is None or not re.fullmatch(r"\s*[+-]?(\d+\.?\d*|\.\d+)\s*", value):
        return default
    return float(value)


def _label_shown(style: dict[str, str]) -> bool:
    """Whether a cell's style draws its label at all."""
    if style.get("noLabel") == "1":
        return False
    if _number(style.get("opacity"), 100) <= 0 or _number(style.get("textOpacity"), 100) <= 0:
        return False
    if _number(style.get("fontSize"), 11) <= 0:
        return False
    return style.get("fontColor", "").strip().lower() not in ("none", "transparent")


def _stroke_shown(style: dict[str, str]) -> bool:
    """Whether an edge's style draws its line."""
    if style.get("strokeColor", "").strip().lower() in ("none", "transparent"):
        return False
    return _number(style.get("opacity"), 100) > 0 and _number(style.get("strokeWidth"), 1) > 0


def _arrow_direction(style: dict[str, str]) -> Optional[bool]:
    """True if an edge is drawn pointing at its target, False if at its source.

    None when it points both ways or neither: the drawing then gives no
    direction to read the relation in. drawio draws an arrow at the target
    unless ``endArrow`` says otherwise, and none at the source.

    Examples:
        >>> _arrow_direction({}), _arrow_direction({"endArrow": "none", "startArrow": "block"})
        (True, False)
        >>> _arrow_direction({"endArrow": "none"}) is None
        True
    """
    at_target = style.get("endArrow", "classic").strip().lower() not in ("none", "")
    at_source = style.get("startArrow", "none").strip().lower() not in ("none", "")
    if at_target == at_source:
        return None
    return at_target


def _inflate(payload: str, limit: int) -> bytes:
    """Decode a compressed ``<diagram>`` payload to at most ``limit`` bytes.

    Raises:
        Unrenderable: Not base64, not raw deflate, or larger than ``limit``.
    """
    if limit <= 0:  # zlib reads a max_length of 0 as "no limit"
        raise Unrenderable("the diagram's pages inflate past the size limit")
    try:  # external input boundary: the payload is untrusted
        raw = base64.b64decode(re.sub(r"\s+", "", payload), validate=True)
        inflater = zlib.decompressobj(-15)
        data = inflater.decompress(raw, limit)
    except (binascii.Error, zlib.error) as e:
        raise Unrenderable(f"a diagram page is not base64 deflate: {e}") from e
    if inflater.unconsumed_tail:
        raise Unrenderable("the diagram's pages inflate past the size limit")
    if not inflater.eof:
        raise Unrenderable("a diagram page is a truncated deflate stream")
    return data


def _models(root: etree._Element) -> Iterator[etree._Element]:
    """The ``<mxGraphModel>`` of every page, one at a time.

    Compressed pages share one ``MAX_DIAGRAM_BYTES`` budget, so many pages
    each under it cannot add up to a deflate bomb, and each is inflated only
    when it is reached, so they are never all held at once.
    """
    name = etree.QName(root).localname
    if name == "mxGraphModel":
        yield root
        return
    if name != "mxfile":
        raise Unrenderable(f"not a drawio document: root element is <{name}>")
    budget = MAX_DIAGRAM_BYTES
    for diagram in root.iter("diagram"):
        inline = diagram.find("mxGraphModel")
        if inline is not None:
            yield inline
        elif (diagram.text or "").strip():
            data = _inflate(diagram.text, budget)
            budget -= len(data)
            yield _parse_page(unquote(data.decode("utf-8", errors="replace")))


def _parse_page(xml: str) -> etree._Element:
    """Parse an inflated page."""
    try:  # external input boundary
        model = parse_untrusted_xml(xml)
    except (etree.XMLSyntaxError, ValueError) as e:
        raise Unrenderable(f"a diagram page is not XML: {e}") from e
    if etree.QName(model).localname != "mxGraphModel":
        raise Unrenderable("a diagram page holds no mxGraphModel")
    return model


def _cells(model: etree._Element) -> list[_Cell]:
    """The cells of a page, in document order."""
    cells = []
    for element in model.iter("mxCell"):
        wrapper = element.getparent()
        wrapped = wrapper is not None and etree.QName(wrapper).localname in CELL_WRAPPERS
        attrs = dict(element.attrib)
        if wrapped:
            if wrapper.get("placeholders") == "1" and "%" in (wrapper.get("label") or ""):
                raise Unrenderable("a label is computed from placeholders")
            label = wrapper.get("label") or ""
            cell_id = wrapper.get("id") or ""
        else:
            label = element.get("value") or ""
            cell_id = element.get("id") or ""
        cells.append(
            _Cell(
                id=cell_id,
                parent=attrs.get("parent", ""),
                label=label,
                style=parse_style(attrs.get("style", "")),
                attrs=attrs,
            )
        )
    return cells


def _hidden(cell: _Cell, by_id: dict[str, _Cell]) -> bool:
    """Whether a cell, or a layer or group it sits in, is not drawn."""
    if cell.attrs.get("visible") == "0":
        return True
    seen = {cell.id}
    parent = by_id.get(cell.parent)
    while parent is not None and parent.id not in seen:
        if parent.attrs.get("visible") == "0" or parent.attrs.get("collapsed") == "1":
            return True
        seen.add(parent.id)
        parent = by_id.get(parent.parent)
    return False


def _label_lines(cell: _Cell) -> list[str]:
    """The lines a cell's label draws, as HTML or as plain text."""
    if not cell.label or not _label_shown(cell.style):
        return []
    if cell.style.get("html") == "1":
        return html_label_lines(cell.label)
    return html_label_lines(xml_escape(cell.label).replace("\n", "<br>"))


def _page_labels(model: etree._Element) -> list[list[str]]:
    """A page's labels, then its edge lines."""
    cells = _cells(model)
    by_id = {cell.id: cell for cell in cells if cell.id}
    drawn = [cell for cell in cells if cell.drawn and not _hidden(cell, by_id)]
    for cell in drawn:
        cell.lines = _label_lines(cell)
    labels = [cell.lines for cell in drawn if cell.lines]

    shown = {cell.id: cell for cell in drawn}
    children: dict[str, list[_Cell]] = {}
    for cell in drawn:
        children.setdefault(cell.parent, []).append(cell)
    for edge in drawn:
        if edge.attrs.get("edge") != "1" or not _stroke_shown(edge.style):
            continue
        forward = _arrow_direction(edge.style)
        if forward is None:
            continue
        source = shown.get(edge.attrs.get("source", ""))
        target = shown.get(edge.attrs.get("target", ""))
        edge_words = edge.lines + [
            line for child in children.get(edge.id, []) if child is not edge for line in child.lines
        ]
        if source and target and source.lines and target.lines and edge_words:
            first, last = (source, target) if forward else (target, source)
            labels.append([" ".join(first.lines + edge_words + last.lines)])
    return labels


@ExtractorRegistry.register
class DrawioExtractor(Extractor):
    """Extract the labels a drawio diagram draws, and its edge lines."""

    @classmethod
    def formats(cls) -> list[str]:
        """Return ['drawio']."""
        return ["drawio"]

    def extract(
        self, data: Union[bytes, str], *, content_type: Optional[str] = None
    ) -> Optional[str]:
        """Return the drawn labels, a blank line between them, or None if there are none.

        Also None when the file is malformed, or when what it draws cannot be
        determined statically (see the module docstring).
        """
        try:  # external input boundary: the file is untrusted and may be malformed
            root = parse_untrusted_xml(data)
        except (etree.XMLSyntaxError, ValueError) as e:
            logger.warning(f"Could not parse drawio file: {e}")
            return None
        try:  # fail closed: the cases this module documents
            labels = [label for model in _models(root) for label in _page_labels(model)]
        except Unrenderable as e:
            logger.warning(f"Not extracting drawio text, as what it draws is uncertain: {e}")
            return None
        return SVG_LABEL_SEPARATOR.join("\n".join(label) for label in labels) or None
