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
from dataclasses import dataclass
from typing import Optional, Union

from lxml import etree  # type: ignore[import-untyped]

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry
from linkml_reference_validator.etl.extract.html import NON_CONTENT_TAGS, TEXT_BREAK_TAGS
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


class _Unrenderable(Exception):
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
        _Unrenderable: A rule sets a visibility property in a way this
            extractor does not evaluate.

    Examples:
        >>> [r.classes for r in _parse_stylesheet(".a, text.b {fill:none} .c {font-weight:bold}", 0)]
        [('a',), ('b',)]
        >>> _parse_stylesheet("g > text {display:none}", 0)
        Traceback (most recent call last):
        ...
        linkml_reference_validator.etl.extract.svg._Unrenderable: stylesheet selector 'g > text' sets visibility
    """
    # Skip quoted strings, so a "/*" inside a value cannot swallow the rules
    # after it - a display:none among them - as though they were a comment.
    css = _CSS_COMMENT.sub(lambda m: m.group(1) or "", css)
    rules: list[_Rule] = []
    for prelude, body in _blocks(css):
        if prelude.startswith("@"):
            name = re.match(r"@([\w-]*)", prelude).group(1).lower()  # type: ignore[union-attr]
            if name == "import":
                raise _Unrenderable("stylesheet imports another stylesheet")
            if name not in HARMLESS_AT_RULES and body and _declares_visibility(body):
                raise _Unrenderable(f"@{name} rule sets visibility")
            continue
        if body is None:
            continue
        all_declarations = _declarations(body)
        for prop, value, _ in all_declarations:
            if _changes_text(prop, value):
                raise _Unrenderable(f"stylesheet rule {prelude!r} sets {prop}: {value}")
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
                raise _Unrenderable(f"stylesheet selector {selector!r} sets visibility")
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

    def run(self, root: etree._Element) -> list[list[str]]:
        """Walk from the root element, returning each label's lines."""
        self.svg(root, _State())
        return [label for label in self.labels if label]

    # --- the cascade -------------------------------------------------------

    def cascade(self, element: etree._Element, parent: _State) -> tuple[bool, _State]:
        """Return whether ``element`` is displayed, and its inherited state."""
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
        # "initial" and "revert" fall through as unrecognised values, which
        # every property below reads as its initial value: visible, painted.
        values = {p: v.strip() for p, v in values.items() if v.strip().lower() not in ("inherit", "unset")}
        for prop, value in values.items():
            if _COMPUTED_VALUE.search(value):
                raise _Unrenderable(f"{prop}: {value} is computed at render time")
        if values.get("display", "").lower() == "none":
            return False, parent
        if values.get("content-visibility", "").lower() == "hidden":
            return False, parent
        opacity = _fraction(values.get("opacity", "1"))
        if opacity is not None and opacity <= 0:
            return False, parent

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
        return True, state

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
            raise _Unrenderable("<use> expansion exceeds the size budget")

    def enter(self, element: etree._Element) -> None:
        """Push ``element`` on the walk path."""
        if len(self.path) >= MAX_DEPTH:
            raise _Unrenderable("nesting exceeds the depth budget")
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
        self.path.discard(id(element))

    def use(self, element: etree._Element, state: _State) -> None:
        """Draw what a ``<use>`` references, unless that would cycle."""
        target = self.ids.get(_href(element) or "")
        if target is None or id(target) in self.path:
            return
        if etree.QName(target).localname != "symbol":
            self.svg(target, state)
            return
        displayed, state = self.cascade(target, state)
        if displayed:
            self.enter(target)
            for child in target:
                self.svg(child, state)
            self.path.discard(id(target))

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
            # A closed <select> draws only its chosen option: the first one
            # marked selected, or else the first.
            options = [o for o in element.iter() if _is_html(o, "option")]
            chosen = next((o for o in options if o.get("selected") is not None), None)
            if chosen is None and options:
                chosen = options[0]
            if chosen is not None:
                self.foreign(chosen, state, line)
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

    def end_line(self, parts: list[str]) -> None:
        """Emit the collected characters as one line, whitespace collapsed."""
        text = re.sub(r"\s+", " ", "".join(parts)).strip()
        if _BIDI_CONTROL.search(text):
            raise _Unrenderable("a bidi control character reorders the drawn text")
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
        _Unrenderable: Scripts, external stylesheets, visibility animations, or
            stylesheet rules this extractor cannot evaluate.
    """
    # Both scans are needed: root.iter() does not reach the processing
    # instructions before the root element, where xml-stylesheet usually is.
    for node in root.itersiblings(preceding=True):
        if isinstance(node, etree._ProcessingInstruction) and node.target == "xml-stylesheet":
            raise _Unrenderable("<?xml-stylesheet?> applies an external stylesheet")
    rules: list[_Rule] = []
    for element in root.iter():
        if isinstance(element, etree._ProcessingInstruction) and element.target == "xml-stylesheet":
            raise _Unrenderable("<?xml-stylesheet?> applies an external stylesheet")
        if not isinstance(element.tag, str):
            continue
        name = etree.QName(element).localname
        if name == "script":
            raise _Unrenderable("the SVG contains a script")
        if name == "bdo" and etree.QName(element).namespace == XHTML_NS:
            raise _Unrenderable("a <bdo> draws its text in reverse order")
        # unicode-bidi is the only one that is also a presentation attribute;
        # a content= attribute is RDFa or <meta>, not generated text.
        inline = [("unicode-bidi", element.get("unicode-bidi") or "")]
        inline += [(p, v) for p, v, _ in _declarations(element.get("style") or "")]
        for prop, value in inline:
            if _changes_text(prop, value):
                raise _Unrenderable(f"<{name}> sets {prop}: {value}")
        if name == "link" and "stylesheet" in (element.get("rel") or "").lower():
            raise _Unrenderable("the SVG links an external stylesheet")
        if name in ("set", "animate", "animateColor"):
            target = (element.get("attributeName") or "").strip().lower()
            if target in ANIMATED_VISIBILITY:
                raise _Unrenderable(f"the SVG animates {target!r}")
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
        except _Unrenderable as e:
            logger.warning(f"Not extracting SVG text, as what it renders is uncertain: {e}")
            return None
        return SVG_LABEL_SEPARATOR.join("\n".join(label) for label in labels) or None
