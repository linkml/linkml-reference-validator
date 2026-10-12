"""SVG content extractor: the text a figure renders, and nothing else (#104).

A ``file:`` reference may point at a diagram. A quote is then matched against
what a reader of the figure can see, so this extractor is an integrity check as
much as a parser: attribute values, ``<desc>``/``<title>``/``<metadata>``,
comments, ``<defs>`` and ``<symbol>`` content not drawn by a ``<use>``, and text
that is hidden, transparent or zero-size never reach the output.

Output is one paragraph per label, with a blank line between labels, so that
a quote can be held to one label: labels adjacent in document order may sit
anywhere in the figure. A ``<text>`` element is one label and one line, its
``<tspan>`` runs joined. A run positioned with ``x``, ``y`` or ``dy`` is a
visual line break and is joined with a space; other runs (a bold syllable,
say) run on. A ``<foreignObject>``, where drawio's SVG export puts its labels,
is one label of one line per block, as
:func:`~linkml_reference_validator.etl.extract.html.html_to_text` would read it.

After them come edge lines, one label each: ``"<source> <edge label>
<target>"`` for a connector that names its nodes with ``data-source`` and
``data-target`` (their ids). Those attributes are not drawn, so an edge line
is emitted only when the drawing agrees with them: the connector, its
painted stroke and its label, and both nodes and their labels, are rendered,
and the stroked path joins the two nodes' boxes (see
:mod:`~linkml_reference_validator.etl.extract.svg_geometry`). Drawn
arrowheads give the direction, as in drawio: one at either end reads from the
other node to the one it points at, whatever the attributes say, and one at
each end reads both ways. A line with no arrowhead reads in the attributes'
order, ``data-source`` first, since nothing drawn says otherwise.

Visibility follows the CSS cascade as far as it matters here: presentation
attributes, then ``<style>`` rules by specificity and order, then the ``style``
attribute, then ``!important``. ``display``, ``opacity`` and
``content-visibility`` hide a whole subtree; ``visibility``, ``fill``,
``fill-opacity``, ``stroke``, ``stroke-opacity``, ``stroke-width``,
``font-size``, ``color`` and ``-webkit-text-fill-color`` are inherited and a
child may restore them.

Where the rendered text cannot be determined statically the extractor **fails
closed** and returns ``None``, rather than guess:

- a stylesheet rule that sets one of those properties through a selector other
  than a type, class or id selector (or a list of them), inside an at-rule such
  as ``@media``, or an ``@import``/``<?xml-stylesheet?>``/``<link>`` stylesheet;
- one of those properties set with ``var()``, ``calc()`` or another value
  computed at render time;
- generated ``content``, a string ``list-style-type`` or ``quotes``,
  ``-webkit-text-security``, or a bidi override, ``<bdo>`` or bidi control
  character, which add to, mask or reverse the characters drawn;
- any ``<script>``, or an animation of a property, ``class``, ``style`` or
  ``href``;
- ``<use>`` expansion past a size or depth budget (a ``<use>`` bomb);
- an external entity, which is never loaded.

Known limits: a label drawn as several ``<text>`` elements, one per line, is
read as several labels. HTML text truncated by ``text-overflow`` or
``-webkit-line-clamp`` is read in full. Text clipped by ``clip-path`` or ``mask``, placed outside the
``viewBox``, scaled to nothing by ``transform``, covered by another shape,
drawn in the background colour or in a tiny but non-zero size is still
emitted. ``<switch>`` is evaluated for an English-language reader. Text
converted to outlines is not text and is not emitted.

Changing what this yields for the same input may make already-cached text
wrong; see :mod:`linkml_reference_validator.etl.extract` and bump
``SVG_EXTRACTION_CACHE_VERSION``.

Examples:
    >>> svg = b'''<svg xmlns="http://www.w3.org/2000/svg">
    ...   <desc>not drawn</desc>
    ...   <text x="0" y="10"><tspan x="0">loss of PTEN</tspan><tspan x="0" dy="12">activates AKT</tspan></text>
    ...   <text display="none">hidden</text>
    ... </svg>'''
    >>> SVGExtractor().extract(svg)
    'loss of PTEN activates AKT'
"""

import logging
import re
from dataclasses import dataclass, replace
from typing import Optional, Union

from xml.sax.saxutils import escape as xml_escape

from lxml import etree  # type: ignore[import-untyped]
from lxml import html as lxml_html  # type: ignore[import-untyped]

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry
from linkml_reference_validator.etl.extract.html import NON_CONTENT_TAGS, TEXT_BREAK_TAGS
from linkml_reference_validator.etl.extract.svg_geometry import (
    SHAPES,
    connector_endpoints,
    declares_geometry,
    node_bbox,
    touches,
)
from linkml_reference_validator.matching import SVG_LABEL_SEPARATOR

logger = logging.getLogger(__name__)

SVG_NS = "http://www.w3.org/2000/svg"
XHTML_NS = "http://www.w3.org/1999/xhtml"
XLINK_HREF = "{http://www.w3.org/1999/xlink}href"

#: SVG elements whose content is never painted where it stands. ``<defs>`` and
#: ``<symbol>`` content is drawn only through ``<use>``, which reads it from the
#: element itself; ``<tref>`` is unsupported by browsers.
NON_RENDERED_SVG = frozenset({
    "defs", "symbol", "desc", "title", "metadata", "clipPath", "mask", "marker",
    "pattern", "linearGradient", "radialGradient", "filter", "style", "script",
    "font", "font-face", "glyph", "missing-glyph", "cursor", "view", "tref",
    "set", "animate", "animateColor", "animateMotion", "animateTransform",
})

#: HTML elements in a ``<foreignObject>`` that never display their text: a
#: browser's default styles hide them, or draw the element rather than its
#: fallback content.
NON_RENDERED_HTML = frozenset(NON_CONTENT_TAGS) | {
    "head", "title", "datalist", "rp", "canvas", "video", "audio", "object",
    "iframe",
}

#: The properties that decide whether text is visible.
VISIBILITY_PROPERTIES = frozenset({
    "display", "visibility", "opacity", "content-visibility", "fill",
    "fill-opacity", "stroke", "stroke-opacity", "stroke-width", "font-size",
    "font", "color", "-webkit-text-fill-color",
})

#: Each visibility property's initial value, which ``initial`` and ``revert``
#: stand for. ``revert`` means the browser's default style, which for these
#: properties on SVG text and inline HTML is the same.
INITIAL_VALUES = {
    "display": "inline", "visibility": "visible", "opacity": "1",
    "content-visibility": "visible", "fill": "black", "fill-opacity": "1",
    "stroke": "none", "stroke-opacity": "1", "stroke-width": "1",
    "font-size": "medium", "color": "black",
    "-webkit-text-fill-color": "currentcolor",
}

#: Properties that can add characters to a label or reorder them; see
#: :func:`_changes_text`.
TEXT_CHANGING_PROPERTIES = frozenset({
    "content", "unicode-bidi", "list-style-type", "list-style", "quotes",
    "-webkit-text-security",
})

#: Animation targets that can change what is visible.
ANIMATED_VISIBILITY = VISIBILITY_PROPERTIES | {"class", "style", "href", "xlink:href"}

#: At-rules that cannot change visibility, whatever they contain.
HARMLESS_AT_RULES = frozenset({"font-face", "charset", "namespace", "page"})

#: Expanding ``<use>`` may visit at most this many nodes per node of the
#: document, so a ``<use>`` bomb fails closed instead of running for hours.
VISIT_BUDGET_PER_NODE = 10
#: Nesting deeper than this, through elements and ``<use>``, fails closed. It
#: keeps the recursive walk well inside Python's recursion limit.
MAX_DEPTH = 256

#: A selector that ends in a ``::before`` or ``::after`` pseudo-element.
_GENERATED_BOX = re.compile(r"::?(?:before|after)\s*$", re.IGNORECASE)
_SIMPLE_SELECTOR = re.compile(r"(\*|[A-Za-z_][\w-]*)?((?:[.#][A-Za-z_-][\w-]*)*)")
_NUMBER = re.compile(r"\s*([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)\s*([a-zA-Z%]*)\s*$")
_RELATIVE_FONT_UNITS = frozenset({"em", "%", "ex", "ch", "cap", "ic", "lh"})
_FONT_SIZE_TOKEN = re.compile(
    r"(?:^|\s)((?:\d+\.?\d*|\.\d+)(?:px|pt|pc|em|rem|ex|ch|%|vw|vh|vmin|vmax|mm|cm|in|q)"
    r"|0*\.?0+)(?:/\S+)?(?=\s|$)",
    re.IGNORECASE,
)
#: A CSS comment, or a quoted string (group 1) that may contain "/*".
_CSS_COMMENT = re.compile(r"""("(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*')|/\*.*?\*/""", re.S)

#: Embeddings, overrides and isolates: they draw a run in another order, as
#: ``unicode-bidi`` does. Marks (U+200E, U+200F) only resolve neutrals.
_BIDI_CONTROL = re.compile("[\u202a-\u202e\u2066-\u2069]")

#: CSS functions whose result this extractor does not compute.
_COMPUTED_VALUE = re.compile(r"\b(?:var|calc|env|attr|min|max|clamp)\(", re.IGNORECASE)
_COLOR_FUNCTION = re.compile(r"^(?:rgba?|hsla?)\((.*)\)$")


class Unrenderable(Exception):
    """The text this SVG renders cannot be determined statically."""


@dataclass(frozen=True)
class _Rule:
    """One simple selector of a stylesheet rule, with its declarations."""

    tag: Optional[str]
    classes: tuple[str, ...]
    ids: tuple[str, ...]
    order: int
    declarations: tuple[tuple[str, str, bool], ...]

    @property
    def specificity(self) -> tuple[int, int, int]:
        """CSS specificity: (ids, classes, types)."""
        return (len(self.ids), len(self.classes), 1 if self.tag else 0)

    @property
    def key(self) -> tuple[str, str]:
        """One part every element this selects must have, for indexing.

        Examples:
            >>> _Rule("text", ("a",), ("t",), 0, ()).key
            ('id', 't')
            >>> _Rule("text", ("a",), (), 0, ()).key
            ('class', 'a')
            >>> _Rule(None, (), (), 0, ()).key
            ('*', '')
        """
        if self.ids:
            return ("id", self.ids[0])
        if self.classes:
            return ("class", self.classes[0])
        if self.tag:
            return ("tag", self.tag)
        return ("*", "")

    def matches(self, element: etree._Element) -> bool:
        """Whether this selector selects ``element``."""
        if self.tag and etree.QName(element).localname != self.tag:
            return False
        if self.ids and any(element.get("id") != i for i in self.ids):
            return False
        element_classes = set((element.get("class") or "").split())
        return all(c in element_classes for c in self.classes)


@dataclass(frozen=True)
class _State:
    """The inherited properties that decide whether text is painted."""

    visible: bool = True
    fill: str = "black"
    fill_opacity: float = 1.0
    stroke: str = "none"
    stroke_opacity: float = 1.0
    stroke_width_zero: bool = False
    font_size_zero: bool = False
    color: str = "black"
    #: Paints HTML text in place of ``color`` unless it is ``currentcolor``.
    text_fill: str = "currentcolor"


def _declarations(text: str) -> list[tuple[str, str, bool]]:
    """Parse ``prop: value [!important]`` declarations.

    Examples:
        >>> _declarations("fill: none; Opacity:0 !important;")
        [('fill', 'none', False), ('opacity', '0', True)]
    """
    parsed = []
    for declaration in text.split(";"):
        prop, sep, value = declaration.partition(":")
        if not sep:
            continue
        value, important = re.subn(r"\s*!\s*important\s*$", "", value, flags=re.I)
        parsed.append((prop.strip().lower(), value.strip(), bool(important)))
    return parsed


def _declares_visibility(body: str) -> bool:
    """Whether CSS text sets any of the ``VISIBILITY_PROPERTIES``, or changes text."""
    return any(
        re.search(rf"(?<![\w-]){re.escape(prop)}\s*:", body, re.I)
        for prop in VISIBILITY_PROPERTIES | TEXT_CHANGING_PROPERTIES
    )


def _changes_text(prop: str, value: str) -> bool:
    """Whether a declaration adds, replaces or reorders the characters drawn.

    ``content`` puts text into a ``::before`` or ``::after``; a string
    ``list-style-type`` makes it a list marker, and ``quotes`` puts it around
    a ``<q>``. A bidi override draws a run's characters reversed, and
    ``-webkit-text-security`` draws each as a dot. Either way the label a
    reader sees is not the label in the markup, so the extractor fails closed.

    Examples:
        >>> _changes_text("content", '"never "'), _changes_text("content", '""')
        (True, False)
        >>> _changes_text("unicode-bidi", "bidi-override"), _changes_text("unicode-bidi", "isolate")
        (True, False)
        >>> _changes_text("list-style", "'not ' inside"), _changes_text("list-style-type", "decimal")
        (True, False)
    """
    value = value.strip().lower()
    if prop == "content":
        return value not in ("none", "normal", "", '""', "''")
    if prop == "unicode-bidi":
        return "override" in value
    if prop in ("list-style-type", "list-style"):
        return '"' in value or "'" in value
    if prop == "quotes":
        return value not in ("none", "auto", "")
    if prop == "-webkit-text-security":
        return value not in ("none", "")
    return False


def _blocks(css: str) -> list[tuple[str, Optional[str]]]:
    """Split a stylesheet into top-level ``(prelude, body)`` pairs.

    A statement ending in ``;`` (``@import``) has a body of ``None``.

    Examples:
        >>> _blocks("@import 'x'; a{b:c} @media print{ .x{y:z} }")
        [("@import 'x'", None), ('a', 'b:c'), ('@media print', ' .x{y:z} ')]
    """
    blocks: list[tuple[str, Optional[str]]] = []
    start = 0
    i = 0
    while i < len(css):
        char = css[i]
        if char == ";":
            if css[start:i].strip():
                blocks.append((css[start:i].strip(), None))
            start = i + 1
        elif char == "{":
            depth = 1
            j = i + 1
            while j < len(css) and depth:
                depth += {"{": 1, "}": -1}.get(css[j], 0)
                j += 1
            blocks.append((css[start:i].strip(), css[i + 1 : j - 1]))
            start = i = j
            continue
        i += 1
    return blocks


def _parse_stylesheet(css: str, first_order: int) -> list[_Rule]:
    """Rules of a stylesheet that set visibility properties.

    Raises:
        Unrenderable: A rule sets a visibility property in a way this
            extractor does not evaluate.

    Examples:
        >>> [r.classes for r in _parse_stylesheet(".a, text.b {fill:none} .c {font-weight:bold}", 0)]
        [('a',), ('b',)]
        >>> _parse_stylesheet("g > text {display:none}", 0)
        Traceback (most recent call last):
        ...
        linkml_reference_validator.etl.extract.svg.Unrenderable: stylesheet selector 'g > text' sets visibility
    """
    # Skip quoted strings, so a "/*" inside a value cannot swallow the rules
    # after it - a display:none among them - as though they were a comment.
    css = _CSS_COMMENT.sub(lambda m: m.group(1) or "", css)
    rules: list[_Rule] = []
    for prelude, body in _blocks(css):
        if prelude.startswith("@"):
            name = re.match(r"@([\w-]*)", prelude).group(1).lower()  # type: ignore[union-attr]
            if name == "import":
                raise Unrenderable("stylesheet imports another stylesheet")
            if name not in HARMLESS_AT_RULES and body and _declares_visibility(body):
                raise Unrenderable(f"@{name} rule sets visibility")
            continue
        if body is None:
            continue
        all_declarations = _declarations(body)
        for prop, value, _ in all_declarations:
            if _changes_text(prop, value):
                raise Unrenderable(f"stylesheet rule {prelude!r} sets {prop}: {value}")
        declarations = tuple(d for d in all_declarations if d[0] in VISIBILITY_PROPERTIES)
        if not declarations:
            continue
        for selector in prelude.split(","):
            selector = selector.strip()
            if _GENERATED_BOX.search(selector):
                # Styles only the ::before/::after box, whose text content has
                # already been checked; the element's own text is untouched.
                continue
            match = _SIMPLE_SELECTOR.fullmatch(selector)
            if not selector or not match:
                raise Unrenderable(f"stylesheet selector {selector!r} sets visibility")
            tag = match.group(1) if match.group(1) != "*" else None
            parts = re.findall(r"[.#][\w-]+", match.group(2))
            rules.append(
                _Rule(
                    tag=tag,
                    classes=tuple(p[1:] for p in parts if p[0] == "."),
                    ids=tuple(p[1:] for p in parts if p[0] == "#"),
                    order=first_order + len(rules),
                    declarations=declarations,
                )
            )
    return rules


def _fraction(value: str) -> Optional[float]:
    """An opacity value as a fraction, or None if it is not a number.

    Examples:
        >>> _fraction("0.5"), _fraction("40%"), _fraction("bogus")
        (0.5, 0.4, None)
    """
    match = _NUMBER.match(value)
    if not match or match.group(2) not in ("", "%"):
        return None
    number = float(match.group(1))
    return number / 100 if match.group(2) == "%" else number


def _is_transparent(paint: str) -> bool:
    """Whether a paint or colour value paints nothing.

    Examples:
        >>> [_is_transparent(p) for p in ["none", "#0000", "rgba(1,2,3,0)", "hsl(0 0% 0% / 0%)"]]
        [True, True, True, True]
        >>> [_is_transparent(p) for p in ["red", "#FFF", "rgb(0, 0, 0)", "rgba(0,0,0,0.5)"]]
        [False, False, False, False]
    """
    paint = paint.strip().lower()
    if paint in ("none", "transparent"):
        return True
    if re.fullmatch(r"#[0-9a-f]{3}0|#[0-9a-f]{6}00", paint):
        return True
    function = _COLOR_FUNCTION.match(paint)
    if not function:
        return False
    components = re.split(r"[\s,/]+", function.group(1).strip())
    return len(components) == 4 and _fraction(components[3]) == 0


def _font_size_zero(value: str, parent_zero: bool) -> bool:
    """Whether a ``font-size`` value computes to zero.

    Examples:
        >>> _font_size_zero("0px", False), _font_size_zero("2em", True), _font_size_zero("12px", True)
        (True, True, False)
    """
    lowered = value.strip().lower()
    if lowered in ("smaller", "larger"):
        return parent_zero
    match = _NUMBER.match(lowered)
    if not match:
        return False
    if float(match.group(1)) == 0:
        return True
    return parent_zero if match.group(2) in _RELATIVE_FONT_UNITS else False


def _declare(values: dict[str, str], prop: str, value: str) -> None:
    """Set a property in cascade order, expanding the ``font`` shorthand.

    The shorthand sets ``font-size`` where it stands, so it overrides an
    earlier ``font-size`` and is overridden by a later one.

    Examples:
        >>> values = {"font-size": "12px"}
        >>> _declare(values, "font", "italic 0/0 a")
        >>> values
        {'font-size': '0'}
        >>> _declare(values, "font", "caption")
        >>> values
        {'font-size': 'medium'}
    """
    if prop != "font":
        values[prop] = value
        return
    size = _FONT_SIZE_TOKEN.search(value)
    if size:
        values["font-size"] = size.group(1)
    elif _COMPUTED_VALUE.search(value) or value.strip().lower() in ("inherit", "unset"):
        values["font-size"] = value
    else:  # a system font, such as ``caption``
        values["font-size"] = "medium"


def _href(element: etree._Element) -> Optional[str]:
    """A ``<use>`` element's same-document target id, if it has one."""
    href = element.get("href") or element.get(XLINK_HREF) or ""
    return href[1:] if href.startswith("#") else None


def _is_drawable(node: etree._Element) -> bool:
    """Whether a node is an SVG element that can be drawn where it stands."""
    if not isinstance(node.tag, str):
        return False
    qname = etree.QName(node)
    return qname.namespace in (SVG_NS, None) and qname.localname not in NON_RENDERED_SVG


#: Animations that move, resize or reshape what they animate.
MOVING_ANIMATIONS = frozenset({"animateTransform", "animateMotion"})

#: Attributes whose animation moves, resizes or reshapes a shape.
GEOMETRY_ATTRIBUTES = frozenset({
    "x", "y", "cx", "cy", "r", "rx", "ry", "width", "height", "d", "points",
    "x1", "y1", "x2", "y2", "transform", "clip-path", "mask", "filter", "style", "class",
})


def _geometry_is_static(root: etree._Element) -> bool:
    """Whether every shape is placed by its attributes alone, for good.

    False when a stylesheet sets a geometry property (see
    ``GEOMETRY_PROPERTIES``) or an animation moves or reshapes anything: the
    extractor cannot then say where shapes are drawn, so it confirms no edges.
    Labels are unaffected.
    """
    for element in root.iter():
        if not isinstance(element.tag, str):
            continue
        name = etree.QName(element).localname
        if name in MOVING_ANIMATIONS:
            return False
        if name in ("animate", "set") and element.get("attributeName", "").strip() in GEOMETRY_ATTRIBUTES:
            return False
        if name == "style":
            css = "".join(element.itertext())
            if declares_geometry(css) or re.search(
                r"(?<![\w-])(marker(-start|-end|-mid)?|stroke-dasharray)\s*:", css, re.I
            ):
                return False
    return True


def _marker(shape: etree._Element, at: str) -> Optional[str]:
    """The marker a shape draws at its ``start`` or ``end``, or None.

    Markers are inherited (see :func:`_inherited`); ``none`` means none.

    Examples:
        >>> g = etree.fromstring('<g marker-start="url(#a)"><path/></g>')
        >>> _marker(g[0], "start"), _marker(g[0], "end")
        ('url(#a)', None)
        >>> _marker(etree.fromstring('<path marker-end="url(#a)" style="marker-end:none"/>'), "end") is None
        True
    """
    value = _inherited(shape, f"marker-{at}", "marker")
    return None if value is None or value.lower() in ("none", "") else value


def _inherited(shape: etree._Element, *props: str) -> Optional[str]:
    """The value of an inherited property on a shape or its nearest ancestor.

    ``props`` are the names that set it, most specific first (for a marker,
    ``marker-end`` and then its shorthand ``marker``). On one element the
    last such declaration in ``style`` wins, then the attribute; ``inherit``
    or ``unset`` passes the question to the parent.

    Examples:
        >>> g = etree.fromstring('<g a="1"><path a="inherit" style="b:2; a:3"/></g>')
        >>> _inherited(g[0], "a"), _inherited(g[0], "a", "b")
        ('3', '3')
        >>> _inherited(etree.fromstring('<g a="1"><path a="inherit"/></g>')[0], "a")
        '1'
    """
    node: Optional[etree._Element] = shape
    while node is not None:
        value = None
        for prop, declared, _ in _declarations(node.get("style") or ""):
            if prop in props:
                value = declared
        if value is None:
            value = next((str(node.get(p)) for p in props if node.get(p) is not None), None)
        if value is not None and value.strip().lower() not in ("inherit", "unset"):
            return value.strip()
        node = node.getparent()
    return None


def _dashes_draw(shape: etree._Element) -> bool:
    """Whether a shape's dash pattern draws any of its stroke.

    A pattern whose dashes are all zero long, such as ``0 1000``, draws
    nothing. The pattern repeats twice over when it has an odd length, so
    the dashes are its even entries of the doubled list.

    Examples:
        >>> _dashes_draw(etree.fromstring('<path stroke-dasharray="0 9"/>'))
        False
        >>> _dashes_draw(etree.fromstring('<path stroke-dasharray="4 2"/>'))
        True
    """
    value = _inherited(shape, "stroke-dasharray")
    if value is None or value.lower() in ("none", ""):
        return True
    lengths = [float(n) for n in re.findall(r"[+-]?(?:\d+\.?\d*|\.\d+)", value)]
    if not lengths:
        return True
    if len(lengths) % 2:
        lengths = lengths * 2
    return any(length > 0 for length in lengths[0::2])


def _nested(source: etree._Element, target: etree._Element, connector: etree._Element) -> bool:
    """Whether one node holds the other, or either holds the connector.

    A node's labels and box are everything inside it, so a compartment
    holding its target would lend it the target's label and box, and a node
    holding the connector would take in the edge label - as a connector
    holding a node would take in the node's. A self-loop (one
    node as both source and target) is not nested.

    Examples:
        >>> outer = etree.fromstring('<g><g/><path/></g>')
        >>> inner, path = outer[0], outer[1]
        >>> _nested(outer, inner, path), _nested(inner, inner, path)
        (True, False)
    """
    def holds(outer: etree._Element, inner: etree._Element) -> bool:
        return outer is not inner and any(a is outer for a in inner.iterancestors())

    if holds(source, target) or holds(target, source):
        return True
    if connector in (source, target) or any(holds(connector, node) for node in (source, target)):
        return True  # the edge label would take in the node's labels
    return holds(source, connector) or holds(target, connector)


#: Shapes that can draw a connector between two nodes.
CONNECTOR_SHAPES = frozenset({"path", "line", "polyline"})

#: Elements inside a ``<marker>`` that draw nothing themselves. Anything else
#: that is not a shape (text, an image, a ``<use>``) may draw an arrowhead the
#: marker check can't see, which leaves the direction uncertain.
MARKER_CONTAINERS = frozenset({"g", "a", "switch"})


def _readings(forward: bool, backward: bool, at_start: bool, at_end: bool) -> list[bool]:
    """Which ways an edge reads: True for source first, False for target first.

    ``forward`` and ``backward`` say whether the path runs from the source's
    box to the target's, or the other way; ``at_start`` and ``at_end`` whether
    an arrowhead is drawn there. An arrowhead at one end points at the node
    there; at both ends the edge reads both ways; with none it reads source
    first. An arrowhead on a path that touches both nodes at both ends points
    at neither in particular, so it gives no reading.

    Examples:
        >>> _readings(True, False, False, True), _readings(True, False, True, False)
        ([True], [False])
        >>> _readings(False, True, False, True), _readings(True, False, True, True)
        ([False], [True, False])
        >>> _readings(False, True, False, False), _readings(True, True, False, True)
        ([True], [])
    """
    if at_start and at_end:
        return [True, False]
    if not (at_start or at_end):
        return [True]
    if forward == backward:
        return []
    return [forward == at_end]


def _words(labels: list[list[str]]) -> str:
    """Labels' lines run together with spaces, as one phrase."""
    return " ".join(line for label in labels for line in label)


def _is_html(node: etree._Element, name: str) -> bool:
    """Whether a node is the XHTML element ``name``."""
    return isinstance(node.tag, str) and node.tag == f"{{{XHTML_NS}}}{name}"


def _english_reader(element: etree._Element) -> bool:
    """Whether a ``<switch>`` child's conditions hold for an English-language reader."""
    if (element.get("requiredExtensions") or "").strip():
        return False
    languages = element.get("systemLanguage")
    if languages is None:
        return True
    return any(lang.strip().lower().split("-")[0] == "en" for lang in languages.split(","))


class _RenderedText:
    """One walk of a parsed SVG, collecting its rendered lines."""

    def __init__(self, root: etree._Element, rules: list[_Rule]):
        nodes = list(root.iter())
        # The first element with an id is the one it names, as for getElementById.
        self.ids: dict[str, etree._Element] = {}
        for node in nodes:
            if isinstance(node.tag, str) and node.get("id"):
                self.ids.setdefault(node.get("id"), node)
        # Each rule is filed under one part every element it selects must have,
        # so an element is matched only against rules that could select it.
        self.rules: dict[tuple[str, str], list[_Rule]] = {}
        for rule in rules:
            self.rules.setdefault(rule.key, []).append(rule)
        # Each label is a list of lines; the last one is being filled.
        self.labels: list[list[str]] = [[]]
        self.budget = VISIT_BUDGET_PER_NODE * len(nodes) + 10_000
        self.path: set[int] = set()
        # For edge lines: the labels each drawn element holds, and whether each
        # drawn connector shape's stroke is painted. Recorded only outside
        # <use>, whose copies are drawn somewhere the geometry does not follow.
        # Keyed by the element itself, not id(): lxml frees an element's
        # Python proxy when nothing holds it, so its id() is not stable.
        self.use_depth = 0
        self.drawn_labels: dict[etree._Element, list[list[str]]] = {}
        self.stroked: dict[etree._Element, bool] = {}
        self.painted_shapes: set[etree._Element] = set()
        self.marker_drawn: dict[etree._Element, Optional[bool]] = {}

    def run(self, root: etree._Element) -> list[list[str]]:
        """Walk from the root element, returning each label's lines."""
        self.svg(root, _State())
        labels = [label for label in self.labels if label]
        return labels + [[line] for line in self.edge_lines(root)]

    # --- edge lines ----------------------------------------------------------

    def draws_arrowhead(self, shape: etree._Element, at: str) -> Optional[bool]:
        """Whether a shape's marker at ``at`` draws something there.

        The marker must name a ``<marker>`` in the figure that is not sized
        to nothing and holds a shape that paints; anything less draws no
        arrowhead. None when that can't be told from the markup, as for a
        ``var()`` value or a ``<use>`` inside the marker: then neither an
        arrowhead nor its absence is safe to read a direction from.
        """
        match = re.fullmatch(
            r"url\(\s*['\"]?#([^'\")]+)['\"]?\s*\)", _marker(shape, at) or ""
        )
        marker = self.ids.get(match.group(1)) if match else None
        if marker is None or etree.QName(marker).localname != "marker":
            return False
        if marker not in self.marker_drawn:
            try:
                self.marker_drawn[marker] = self._marker_paints(marker)
            except Unrenderable:
                # Only this arrowhead is uncertain, so only its edge is lost.
                self.marker_drawn[marker] = None
        return self.marker_drawn[marker]

    def _marker_paints(self, marker: etree._Element) -> Optional[bool]:
        """Whether a ``<marker>`` holds a shape that paints, with the cascade applied.

        ``display`` does not apply to a marker, though ``opacity`` does.
        ``context-fill`` counts as unpainted: it takes the connector's fill,
        which is not checked. None when the marker holds something else that
        may draw, which this check doesn't model.
        """
        for size in ("markerWidth", "markerHeight"):
            value = _NUMBER.match(marker.get(size) or "3")
            if value is None or float(value.group(1)) <= 0:
                return False
        view_box = [_NUMBER.match(v) for v in re.split(r"[\s,]+", (marker.get("viewBox") or "0 0 1 1").strip())]
        if len(view_box) != 4 or any(v is None or v.group(2) for v in view_box):
            return None
        if min(float(v.group(1)) for v in view_box[2:] if v is not None) <= 0:
            return False
        # Its content inherits from the marker's own ancestors, root first;
        # their display and opacity do not apply where the marker is drawn.
        state = _State()
        for element in reversed(list(marker.iterancestors())):
            _, state = self.cascade(element, state)
        displayed, state = self.cascade(marker, state, ignore_display=True)
        if not displayed:
            return False
        uncertain = False
        stack = [(child, state) for child in marker]
        while stack:
            element, parent_state = stack.pop()
            if not isinstance(element.tag, str):
                continue
            name = etree.QName(element).localname
            if name in NON_RENDERED_SVG:
                continue
            displayed, element_state = self.cascade(element, parent_state)
            if not displayed:
                continue
            if name in MARKER_CONTAINERS:
                stack.extend((child, element_state) for child in element)
            elif name not in SHAPES:
                uncertain = True
            elif self._marker_shape_paints(element, element_state):
                return True
        return None if uncertain else False

    def _marker_shape_paints(self, shape: etree._Element, state: _State) -> bool:
        """Whether a shape inside a marker paints, ``context-fill`` counting as none."""
        state = replace(
            state,
            fill="none" if state.fill.strip().lower() == "context-fill" else state.fill,
            stroke="none" if state.stroke.strip().lower() == "context-fill" else state.stroke,
        )
        # The fill alone, then the stroke, which also needs dashes that draw.
        filled = self.shape_painted(replace(state, stroke="none"))
        return filled or (self.stroke_painted(state) and _dashes_draw(shape))

    def edge_lines(self, root: etree._Element) -> list[str]:
        """``"<source> <edge label> <target>"`` for each connector the drawing confirms.

        A connector is an element with ``data-source`` and ``data-target``
        naming two node ids; its own labels are the edge label. The attributes
        are not drawn, so they count only when the drawing agrees with them:
        the connector, its stroke, its label and both nodes and their labels
        are rendered, and the stroked path joins the two nodes' boxes. Drawn
        arrowheads decide which way the line reads (see :func:`_readings`).
        """
        if not _geometry_is_static(root):
            return []
        boxes: dict[etree._Element, Optional[tuple[float, float, float, float]]] = {}

        def box(node: etree._Element) -> Optional[tuple[float, float, float, float]]:
            if node not in boxes:
                boxes[node] = node_bbox(node, root, self.painted_shapes)
            return boxes[node]

        lines: list[str] = []
        for element in root.iter():
            if not isinstance(element.tag, str):
                continue
            source = self.ids.get(element.get("data-source") or "")
            target = self.ids.get(element.get("data-target") or "")
            edge_labels = self.drawn_labels.get(element)
            if source is None or target is None or not edge_labels:
                continue
            if _nested(source, target, element):
                continue
            strokes = [
                e for e in element.iter()
                if isinstance(e.tag, str) and e.tag.split("}")[-1] in CONNECTOR_SHAPES
                and self.stroked.get(e)
            ]
            drawn = [e for e in element.iter() if e in self.painted_shapes]
            source_labels = self.drawn_labels.get(source)
            target_labels = self.drawn_labels.get(target)
            source_box, target_box = box(source), box(target)
            if not (source_labels and target_labels and source_box and target_box):
                continue
            # Any stroked shape of the connector may join the nodes: an
            # arrowhead drawn before the line must not hide the line.
            for stroke in strokes:
                if not _dashes_draw(stroke):
                    continue
                at_start = self.draws_arrowhead(stroke, "start")
                at_end = self.draws_arrowhead(stroke, "end")
                ends = connector_endpoints(stroke, root)
                if at_start is None or at_end is None or not ends:
                    continue
                # With no marker, another shape of the connector may be an
                # arrowhead drawn on its own, which may point either way.
                if not (at_start or at_end) and any(e is not stroke for e in drawn):
                    continue
                forward = touches(ends[0], source_box) and touches(ends[1], target_box)
                backward = source is not target and touches(ends[0], target_box) and touches(ends[1], source_box)
                if not (forward or backward):
                    continue
                readings = _readings(forward, backward, at_start, at_end)
                if not readings:
                    continue
                read: list[str] = []
                for source_first in readings:
                    first, last = (source_labels, target_labels) if source_first else (target_labels, source_labels)
                    line = " ".join(_words(x) for x in (first, edge_labels, last))
                    if line not in read:  # a self-loop reads the same both ways
                        read.append(line)
                lines.extend(read)
                break
        return lines

    # --- the cascade -------------------------------------------------------

    def cascade(
        self, element: etree._Element, parent: _State, ignore_display: bool = False
    ) -> tuple[bool, _State]:
        """Return whether ``element`` is displayed, and its inherited state.

        ``ignore_display`` leaves out ``display``, which does not apply to a
        ``<marker>``.
        """
        values: dict[str, str] = {}
        if etree.QName(element).namespace == XHTML_NS:
            if element.get("hidden") is not None:
                values["display"] = "none"
        else:
            for prop in VISIBILITY_PROPERTIES:
                if element.get(prop) is not None:
                    _declare(values, prop, element.get(prop))
        matched = sorted(
            {id(r): r for r in self.candidate_rules(element) if r.matches(element)}.values(),
            key=lambda r: (r.specificity, r.order),
        )
        inline = _declarations(element.get("style") or "")
        for important in (False, True):
            for rule in matched:
                for prop, value, imp in rule.declarations:
                    if imp == important:
                        _declare(values, prop, value)
            for prop, value, imp in inline:
                if imp == important and prop in VISIBILITY_PROPERTIES:
                    _declare(values, prop, value)
        if ignore_display:
            values.pop("display", None)
        return self.apply(values, parent)

    def candidate_rules(self, element: etree._Element) -> list[_Rule]:
        """The rules filed under the element's id, classes or tag, or under ``*``."""
        keys = [("*", ""), ("tag", etree.QName(element).localname)]
        if element.get("id"):
            keys.append(("id", element.get("id")))
        keys += [("class", c) for c in (element.get("class") or "").split()]
        return [rule for key in keys for rule in self.rules.get(key, [])]

    @staticmethod
    def apply(values: dict[str, str], parent: _State) -> tuple[bool, _State]:
        """Apply computed property values on top of the inherited state."""
        # inherit and unset leave the parent's value (or, for the properties
        # that are not inherited, the initial one). initial and revert become
        # the property's own initial value: stroke's is none, not painted.
        values = {p: v.strip() for p, v in values.items() if v.strip().lower() not in ("inherit", "unset")}
        values = {
            p: INITIAL_VALUES.get(p, v) if v.lower() in ("initial", "revert", "revert-layer") else v
            for p, v in values.items()
        }
        for prop, value in values.items():
            if _COMPUTED_VALUE.search(value):
                raise Unrenderable(f"{prop}: {value} is computed at render time")
        # A hidden element still hands its state on: a <marker> under it is
        # drawn where it is used, inheriting from it all the same.
        opacity = _fraction(values.get("opacity", "1"))
        displayed = (
            values.get("display", "").lower() != "none"
            and values.get("content-visibility", "").lower() != "hidden"
            and not (opacity is not None and opacity <= 0)
        )

        visible = parent.visible
        if "visibility" in values:
            visible = values["visibility"].lower() not in ("hidden", "collapse")
        fill_opacity = _fraction(values.get("fill-opacity", ""))
        stroke_opacity = _fraction(values.get("stroke-opacity", ""))
        stroke_width_zero = parent.stroke_width_zero
        if "stroke-width" in values:
            width = _NUMBER.match(values["stroke-width"])
            stroke_width_zero = width is not None and float(width.group(1)) == 0
        font_size_zero = parent.font_size_zero
        if "font-size" in values:
            font_size_zero = _font_size_zero(values["font-size"], parent.font_size_zero)
        state = _State(
            visible=visible,
            fill=values.get("fill", parent.fill),
            fill_opacity=parent.fill_opacity if fill_opacity is None else fill_opacity,
            stroke=values.get("stroke", parent.stroke),
            stroke_opacity=parent.stroke_opacity if stroke_opacity is None else stroke_opacity,
            stroke_width_zero=stroke_width_zero,
            font_size_zero=font_size_zero,
            color=values.get("color", parent.color),
            text_fill=values.get("-webkit-text-fill-color", parent.text_fill),
        )
        return displayed, state

    @staticmethod
    def _paint(paint: str, state: _State) -> str:
        """Resolve ``currentColor``."""
        return state.color if paint.strip().lower() == "currentcolor" else paint

    def svg_painted(self, state: _State) -> bool:
        """Whether SVG text in ``state`` paints anything."""
        if not state.visible or state.font_size_zero:
            return False
        filled = not _is_transparent(self._paint(state.fill, state)) and state.fill_opacity > 0
        stroked = (
            not _is_transparent(self._paint(state.stroke, state))
            and state.stroke_opacity > 0
            and not state.stroke_width_zero
        )
        return filled or stroked

    @classmethod
    def stroke_painted(cls, state: _State) -> bool:
        """Whether an SVG shape's stroke in ``state`` paints anything."""
        return (
            state.visible
            and not _is_transparent(cls._paint(state.stroke, state))
            and state.stroke_opacity > 0
            and not state.stroke_width_zero
        )

    @classmethod
    def shape_painted(cls, state: _State) -> bool:
        """Whether an SVG shape in ``state`` paints a fill or a stroke."""
        filled = not _is_transparent(cls._paint(state.fill, state)) and state.fill_opacity > 0
        return state.visible and (filled or cls.stroke_painted(state))

    @staticmethod
    def html_painted(state: _State) -> bool:
        """Whether HTML text in ``state`` paints anything."""
        paint = state.color if state.text_fill.strip().lower() == "currentcolor" else state.text_fill
        return state.visible and not state.font_size_zero and not _is_transparent(paint)

    # --- the walk ----------------------------------------------------------

    def spend(self) -> None:
        """Charge one visited node, rendered or not, against the budget.

        Every node is charged, including those skipped as hidden or not
        rendered: a ``<use>`` bomb can repeat them as easily as anything else.
        """
        self.budget -= 1
        if self.budget < 0:
            raise Unrenderable("<use> expansion exceeds the size budget")

    def enter(self, element: etree._Element) -> None:
        """Push ``element`` on the walk path."""
        if len(self.path) >= MAX_DEPTH:
            raise Unrenderable("nesting exceeds the depth budget")
        self.path.add(id(element))

    def svg(self, element: etree._Element, state: _State) -> None:
        """Walk an SVG element outside ``<text>``."""
        self.spend()
        if not _is_drawable(element):
            return
        displayed, state = self.cascade(element, state)
        if not displayed:
            return
        self.enter(element)
        name = etree.QName(element).localname
        recorded = self.use_depth == 0
        first_label = len(self.labels) - 1
        if recorded and name in CONNECTOR_SHAPES:
            self.stroked[element] = self.stroke_painted(state)
        if recorded and name in SHAPES and self.shape_painted(state):
            self.painted_shapes.add(element)
        if name == "text":
            parts: list[str] = []
            self.text_runs(element, state, parts)
            self.end_line(parts)
            self.end_label()
        elif name == "use":
            self.use(element, state)
        elif name == "switch":
            for child in element:
                # Like a browser, pass over children that are never drawn.
                if _is_drawable(child) and _english_reader(child):
                    self.svg(child, state)
                    break
        elif name == "foreignObject":
            line: list[str] = []
            for child in element:
                self.foreign(child, state, line)
            self.end_line(line)
            self.end_label()
        else:
            for child in element:
                self.svg(child, state)
        # Only nodes (named by an id) and connectors are ever looked up.
        if recorded and (element.get("id") is not None or element.get("data-source") is not None):
            self.drawn_labels[element] = [label for label in self.labels[first_label:] if label]
        self.path.discard(id(element))

    def use(self, element: etree._Element, state: _State) -> None:
        """Draw what a ``<use>`` references, unless that would cycle."""
        target = self.ids.get(_href(element) or "")
        if target is None or id(target) in self.path:
            return
        self.use_depth += 1
        if etree.QName(target).localname != "symbol":
            self.svg(target, state)
        else:
            displayed, state = self.cascade(target, state)
            if displayed:
                self.enter(target)
                for child in target:
                    self.svg(child, state)
                self.path.discard(id(target))
        self.use_depth -= 1

    def text_runs(self, element: etree._Element, state: _State, parts: list[str]) -> None:
        """Collect the painted characters of a ``<text>`` or one of its runs."""
        painted = self.svg_painted(state)
        if element.text and painted:
            parts.append(element.text)
        for child in element:
            self.spend()
            if _is_drawable(child):
                displayed, child_state = self.cascade(child, state)
                if displayed:
                    if any(child.get(a) is not None for a in ("x", "y", "dy")):
                        parts.append(" ")
                    self.enter(child)
                    self.text_runs(child, child_state, parts)
                    self.path.discard(id(child))
            if child.tail and painted:
                parts.append(child.tail)

    def foreign(self, element: etree._Element, state: _State, line: list[str]) -> None:
        """Walk an element inside ``<foreignObject>``."""
        self.spend()
        if not isinstance(element.tag, str):
            return
        qname = etree.QName(element)
        if qname.namespace == SVG_NS and qname.localname == "svg":
            # A nested SVG's labels are its own, not lines of this one.
            self.end_line(line)
            self.end_label()
            self.svg(element, state)
        elif qname.namespace == XHTML_NS:
            self.html(element, state, line)

    def html(self, element: etree._Element, state: _State, line: list[str]) -> None:
        """Walk an HTML element, starting a new line at each block."""
        name = etree.QName(element).localname.lower()
        if name in NON_RENDERED_HTML:
            return
        displayed, state = self.cascade(element, state)
        if not displayed:
            return
        self.enter(element)
        if name == "br" or name in TEXT_BREAK_TAGS:
            self.end_line(line)
        if name == "dialog" and element.get("open") is None:
            self.path.discard(id(element))
            return
        if name == "select":
            self.select(element, state, line)
            self.path.discard(id(element))
            return
        if name == "details" and element.get("open") is None:
            # A closed <details> shows its first <summary> and nothing else.
            summary = next((c for c in element if _is_html(c, "summary")), None)
            if summary is not None:
                self.foreign(summary, state, line)
            self.end_line(line)
            self.path.discard(id(element))
            return
        painted = self.html_painted(state)
        if element.text and painted:
            line.append(element.text)
        for child in element:
            self.foreign(child, state, line)
            if child.tail and painted:
                line.append(child.tail)
        if name in TEXT_BREAK_TAGS:
            self.end_line(line)
        self.path.discard(id(element))

    def select(self, element: etree._Element, state: _State, line: list[str]) -> None:
        """Read the one option a closed ``<select>`` draws.

        Each option marked ``selected`` deselects the one before, so the last
        one is drawn; with none, the first that is not ``disabled``. An
        option's ``label`` attribute is drawn in place of its text. A
        ``<select multiple>`` or with ``size`` draws a list of options and is
        read the same way, so it is under-read, never over-read.
        """
        options = [o for o in element.iter() if _is_html(o, "option")]
        selected = [o for o in options if o.get("selected") is not None]
        chosen = selected[-1] if selected else next(
            (o for o in options if o.get("disabled") is None), None
        )
        if chosen is None:
            return
        # Cascade through any <optgroup> between the <select> and the option.
        groups = []
        parent = chosen.getparent()
        while parent is not None and parent is not element:
            groups.append(parent)
            parent = parent.getparent()
        for group in reversed(groups):
            displayed, state = self.cascade(group, state)
            if not displayed:
                return
        if chosen.get("label") is None:
            self.foreign(chosen, state, line)
            return
        displayed, state = self.cascade(chosen, state)
        if displayed and self.html_painted(state):
            line.append(chosen.get("label"))

    def end_line(self, parts: list[str]) -> None:
        """Emit the collected characters as one line, whitespace collapsed."""
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        if _BIDI_CONTROL.search(text):
            raise Unrenderable("a bidi control character reorders the drawn text")
        if text:
            self.labels[-1].append(text)
        parts.clear()

    def end_label(self) -> None:
        """Close the label being built, so the next line starts a new one."""
        if self.labels[-1]:
            self.labels.append([])


def _check_static(root: etree._Element) -> list[_Rule]:
    """Return the document's stylesheet rules, or fail closed.

    Raises:
        Unrenderable: Scripts, external stylesheets, visibility animations, or
            stylesheet rules this extractor cannot evaluate.
    """
    # Both scans are needed: root.iter() does not reach the processing
    # instructions before the root element, where xml-stylesheet usually is.
    for node in root.itersiblings(preceding=True):
        if isinstance(node, etree._ProcessingInstruction) and node.target == "xml-stylesheet":
            raise Unrenderable("<?xml-stylesheet?> applies an external stylesheet")
    rules: list[_Rule] = []
    for element in root.iter():
        if isinstance(element, etree._ProcessingInstruction) and element.target == "xml-stylesheet":
            raise Unrenderable("<?xml-stylesheet?> applies an external stylesheet")
        if not isinstance(element.tag, str):
            continue
        name = etree.QName(element).localname
        if name == "script":
            raise Unrenderable("the SVG contains a script")
        if name == "bdo" and etree.QName(element).namespace == XHTML_NS:
            raise Unrenderable("a <bdo> draws its text in reverse order")
        # unicode-bidi is the only one that is also a presentation attribute;
        # a content= attribute is RDFa or <meta>, not generated text.
        inline = [("unicode-bidi", element.get("unicode-bidi") or "")]
        inline += [(p, v) for p, v, _ in _declarations(element.get("style") or "")]
        for prop, value in inline:
            if _changes_text(prop, value):
                raise Unrenderable(f"<{name}> sets {prop}: {value}")
        if name == "link" and "stylesheet" in (element.get("rel") or "").lower():
            raise Unrenderable("the SVG links an external stylesheet")
        if name in ("set", "animate", "animateColor"):
            target = (element.get("attributeName") or "").strip().lower()
            if target in ANIMATED_VISIBILITY:
                raise Unrenderable(f"the SVG animates {target!r}")
        if name == "style":
            rules.extend(_parse_stylesheet("".join(element.itertext()), len(rules)))
    return rules


def _parse(data: Union[bytes, str]) -> etree._Element:
    """Parse untrusted SVG without reading external entities or the network.

    Internal entities are expanded, as a browser expands them: leaving
    ``&not;`` out of a label would change what it says. An external entity
    (XXE) is never loaded, so it is undefined and the parse fails, and
    libxml2's amplification limit rejects an exponential internal one
    (billion laughs). Either way the extractor returns None.
    """
    encoding = None
    if isinstance(data, str):
        # The text is already decoded; its declaration no longer describes it.
        data, encoding = data.encode("utf-8"), "utf-8"
    parser = etree.XMLParser(
        encoding=encoding,
        resolve_entities="internal",
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_comments=True,
    )
    return etree.fromstring(data, parser)


def parse_untrusted_xml(data: Union[bytes, str]) -> etree._Element:
    """Parse untrusted XML as SVG is parsed: no external entities, no network.

    Raises ``etree.XMLSyntaxError`` or ``ValueError`` if it is malformed.
    """
    return _parse(data)


def html_label_lines(html: str) -> list[str]:
    """The lines an HTML label draws, read as a ``<foreignObject>`` label is.

    For labels kept as HTML outside an SVG, such as drawio's: the fragment is
    walked with the same visibility rules, so hidden HTML is not read and
    anything that cannot be read statically fails closed.

    Raises:
        Unrenderable: What the label draws cannot be determined statically.

    Examples:
        >>> html_label_lines("<b>PTEN</b><br>tumour <span style='display:none'>x</span>suppressor")
        ['PTEN', 'tumour suppressor']
    """
    if not html.strip():
        return []
    parts = []
    for fragment in lxml_html.fragments_fromstring(html):
        if isinstance(fragment, str):
            parts.append(xml_escape(fragment))
            continue
        for element in fragment.iter():
            if not isinstance(element.tag, str):
                continue
            # HTML has no namespaces: a browser draws <o:p> (Word leaves them
            # in pasted text) as an unknown inline element, so it becomes one
            # here rather than an undeclared XML prefix.
            if ":" in element.tag:
                element.tag = "span"
            for name in [n for n in element.attrib if ":" in n]:
                del element.attrib[name]
        parts.append(etree.tostring(fragment, method="xml", encoding="unicode", with_tail=True))
    document = (
        f'<svg xmlns="{SVG_NS}"><foreignObject><div xmlns="{XHTML_NS}">'
        f'{"".join(parts)}</div></foreignObject></svg>'
    )
    try:  # external input boundary: the label is untrusted HTML
        root = _parse(document)
    except (etree.XMLSyntaxError, ValueError) as e:
        raise Unrenderable(f"an HTML label does not convert to XHTML: {e}") from e
    labels = _RenderedText(root, _check_static(root)).run(root)
    return [line for label in labels for line in label]


@ExtractorRegistry.register
class SVGExtractor(Extractor):
    """Extract the text an SVG figure renders.

    Examples:
        >>> SVGExtractor.formats()
        ['svg']
        >>> SVGExtractor().extract(b'<svg xmlns="http://www.w3.org/2000/svg"><text>A</text></svg>')
        'A'
        >>> SVGExtractor().extract(b'<svg xmlns="http://www.w3.org/2000/svg"><desc>A</desc></svg>') is None
        True
    """

    @classmethod
    def formats(cls) -> list[str]:
        """Return ['svg']."""
        return ["svg"]

    def extract(
        self, data: Union[bytes, str], *, content_type: Optional[str] = None
    ) -> Optional[str]:
        """Return the rendered labels, a blank line between them, or None if there are none.

        Also None when the SVG is malformed, or when what it renders cannot be
        determined statically (see the module docstring).
        """
        try:  # external input boundary: the file is untrusted and may be malformed
            root = _parse(data)
        except (etree.XMLSyntaxError, ValueError) as e:
            logger.warning(f"Could not parse SVG: {e}")
            return None
        if etree.QName(root).localname != "svg":
            logger.warning(f"Not an SVG document: root element is <{etree.QName(root).localname}>")
            return None
        try:  # fail closed: these are the cases this module documents
            labels = _RenderedText(root, _check_static(root)).run(root)
        except Unrenderable as e:
            logger.warning(f"Not extracting SVG text, as what it renders is uncertain: {e}")
            return None
        return SVG_LABEL_SEPARATOR.join("\n".join(label) for label in labels) or None
