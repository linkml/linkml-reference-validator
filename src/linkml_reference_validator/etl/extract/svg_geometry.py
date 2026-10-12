"""Just enough SVG geometry to check that a connector joins two nodes (#104).

An edge line ("PTEN inhibits AKT") is emitted only when a connector's path
visibly starts on one node and ends on the other. This module works out the
two things that takes: where a path begins and ends, and the box a node
occupies, both in the coordinates of the root ``<svg>``, with every
``transform`` on the way applied.

Anything it cannot place exactly - a length in ``%`` or ``em``, a malformed
path or transform, an element inside a nested ``<svg>``, ``<symbol>`` or
``<pattern>`` (which set up coordinates of their own) - gives ``None``, and
the caller emits no edge. The geometry only ever withholds an edge line.

Examples:
    >>> path_endpoints("M0 0 L10 0 L10 10")
    ((0.0, 0.0), (10.0, 10.0))
"""

import math
import re
from dataclasses import dataclass
from typing import Container, Optional

from lxml import etree  # type: ignore[import-untyped]

Point = tuple[float, float]
Box = tuple[float, float, float, float]

#: Shapes whose geometry makes up a node's box. Text is left out: its extent
#: depends on font metrics, and a label may sit outside the box it names.
SHAPES = frozenset({"rect", "circle", "ellipse", "line", "polyline", "polygon", "path"})

#: CSS properties that place, size or reshape an element, or clip, mask or
#: filter what it draws. This module reads geometry from attributes only, so an
#: element or ancestor that sets one of these in its ``style`` cannot be placed.
#: :func:`declares_geometry` checks stylesheets for the same properties.
GEOMETRY_PROPERTIES = frozenset({
    "transform", "translate", "rotate", "scale", "transform-origin", "transform-box",
    "offset", "offset-path", "offset-distance", "offset-rotate", "offset-anchor",
    "x", "y", "cx", "cy", "r", "rx", "ry", "width", "height", "d",
    "clip-path", "mask", "filter",
})

#: Attributes that clip, mask or filter what an element draws.
OBSCURING_ATTRIBUTES = ("clip-path", "mask", "filter")

#: Elements that set up a coordinate system of their own (a viewport or a
#: reference), which this module does not model.
NEW_VIEWPORTS = frozenset({"svg", "symbol", "pattern", "marker", "clipPath", "mask", "use"})

_NUMBER = r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?"
_TRANSFORM = re.compile(r"\s*(matrix|translate|scale|rotate|skewX|skewY)\s*\(([^)]*)\)\s*,?")
_LENGTH = re.compile(rf"\s*({_NUMBER})\s*(px)?\s*$")

#: Numbers each path command takes per segment.
_ARITY = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4, "Q": 4, "T": 2, "A": 7, "Z": 0}


@dataclass(frozen=True)
class Matrix:
    """An affine transform ``[a c e; b d f; 0 0 1]``, as SVG writes it."""

    a: float = 1.0
    b: float = 0.0
    c: float = 0.0
    d: float = 1.0
    e: float = 0.0
    f: float = 0.0

    def then(self, inner: "Matrix") -> "Matrix":
        """This transform applied after ``inner``: ``self × inner``."""
        return Matrix(
            self.a * inner.a + self.c * inner.b,
            self.b * inner.a + self.d * inner.b,
            self.a * inner.c + self.c * inner.d,
            self.b * inner.c + self.d * inner.d,
            self.a * inner.e + self.c * inner.f + self.e,
            self.b * inner.e + self.d * inner.f + self.f,
        )

    def apply(self, x: float, y: float) -> Point:
        """Map a point."""
        return (self.a * x + self.c * y + self.e, self.b * x + self.d * y + self.f)


def parse_transform(value: Optional[str]) -> Optional[Matrix]:
    """Parse a ``transform`` attribute, or None if it is malformed.

    Functions compose left to right, as SVG applies them: in
    ``translate(10 20) scale(2)`` the scale acts first.

    Examples:
        >>> parse_transform("translate(10)").apply(0, 0)
        (10.0, 0.0)
        >>> parse_transform("rotate(90)").apply(1, 0)
        (6.123233995736766e-17, 1.0)
        >>> parse_transform("bogus(1)") is None
        True
    """
    matrix = Matrix()
    text = (value or "").strip()
    position = 0
    while position < len(text):
        match = _TRANSFORM.match(text, position)
        if not match:
            return None
        args = [float(n) for n in re.findall(_NUMBER, match.group(2))]
        step = _transform_function(match.group(1), args)
        if step is None:
            return None
        matrix = matrix.then(step)
        position = match.end()
    return matrix


def _transform_function(name: str, args: list[float]) -> Optional[Matrix]:
    """One transform function as a matrix, or None if its arguments are wrong."""
    if name == "matrix" and len(args) == 6:
        return Matrix(*args)
    if name == "translate" and len(args) in (1, 2):
        return Matrix(e=args[0], f=args[1] if len(args) == 2 else 0.0)
    if name == "scale" and len(args) in (1, 2):
        return Matrix(a=args[0], d=args[1] if len(args) == 2 else args[0])
    if name == "rotate" and len(args) in (1, 3):
        angle = math.radians(args[0])
        rotation = Matrix(math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle))
        if len(args) == 1:
            return rotation
        cx, cy = args[1], args[2]
        return Matrix(e=cx, f=cy).then(rotation).then(Matrix(e=-cx, f=-cy))
    if name == "skewX" and len(args) == 1:
        return Matrix(c=math.tan(math.radians(args[0])))
    if name == "skewY" and len(args) == 1:
        return Matrix(b=math.tan(math.radians(args[0])))
    return None


def _length(element: etree._Element, name: str, default: Optional[float] = None) -> Optional[float]:
    """A length attribute in user units, or None if absent (without default) or relative."""
    value = element.get(name)
    if value is None:
        return default
    match = _LENGTH.match(value)
    return float(match.group(1)) if match else None


_SEPARATOR = re.compile(r"[\s,]*")
_NUMBER_AT = re.compile(_NUMBER)
_FLAG_AT = re.compile(r"[01]")
_COMMAND_AT = re.compile(r"[MmLlHhVvCcSsQqTtAaZz]")


def path_vertices(d: str) -> Optional[list[Point]]:
    """The points a path's segments start and end at, or None if it is malformed.

    Control points are left out: a curve does not pass through them. An
    arc's two flags are single characters, so ``a5 5 0 0010 10`` is flags
    ``0`` and ``0`` and the end point ``(10, 10)``.

    Examples:
        >>> path_vertices("M0 0 h10 v5")
        [(0.0, 0.0), (10.0, 0.0), (10.0, 5.0)]
    """
    vertices: list[Point] = []
    x = y = start_x = start_y = 0.0
    command = ""
    position = _SEPARATOR.match(d, 0).end()  # type: ignore[union-attr]
    while position < len(d):
        letter = _COMMAND_AT.match(d, position)
        if letter:
            command = letter.group()
            position = _SEPARATOR.match(d, letter.end()).end()  # type: ignore[union-attr]
        elif not command or command in "Zz":
            return None  # numbers with no command to take them
        if not vertices and command not in "Mm":
            return None  # a path must begin with a move
        upper = command.upper()
        if upper == "Z":
            x, y = start_x, start_y
            vertices.append((x, y))
            continue
        values = []
        for index in range(_ARITY[upper]):
            pattern = _FLAG_AT if upper == "A" and index in (3, 4) else _NUMBER_AT
            match = pattern.match(d, position)
            if not match:
                return None
            values.append(float(match.group()))
            position = _SEPARATOR.match(d, match.end()).end()  # type: ignore[union-attr]
        relative = command.islower()
        if upper == "H":
            x = values[0] + (x if relative else 0.0)
        elif upper == "V":
            y = values[0] + (y if relative else 0.0)
        else:
            end_x, end_y = values[-2], values[-1]
            x, y = (x + end_x, y + end_y) if relative else (end_x, end_y)
        vertices.append((x, y))
        if upper == "M":
            start_x, start_y = x, y
            command = "l" if relative else "L"  # further pairs are implicit line-tos
    return vertices or None


def path_endpoints(d: str) -> Optional[tuple[Point, Point]]:
    """Where a path starts and ends, or None if it is malformed.

    Examples:
        >>> path_endpoints("M5 5 C0 0 20 20 10 10")
        ((5.0, 5.0), (10.0, 10.0))
        >>> path_endpoints("L1 1") is None
        True
    """
    vertices = path_vertices(d)
    if not vertices:
        return None
    return vertices[0], vertices[-1]


def _lengths(element: etree._Element, *specs: tuple[str, Optional[float]]) -> Optional[list[float]]:
    """Several length attributes, each with its default, or None if any is missing or relative."""
    values = [_length(element, name, default) for name, default in specs]
    if any(v is None for v in values):
        return None
    return [v for v in values if v is not None]


def _box_corners(x0: float, y0: float, x1: float, y1: float) -> list[Point]:
    """The four corners of an axis-aligned box, so a transform can rotate it."""
    return [(x0, y0), (x1, y1), (x1, y0), (x0, y1)]


def _local_points(element: etree._Element) -> Optional[list[Point]]:
    """The points that bound a shape, in its own coordinates."""
    name = etree.QName(element).localname
    if name == "rect":
        rect = _lengths(element, ("x", 0.0), ("y", 0.0), ("width", None), ("height", None))
        if rect is None:
            return None
        x, y, width, height = rect
        return _box_corners(x, y, x + width, y + height)
    if name == "circle":
        circle = _lengths(element, ("cx", 0.0), ("cy", 0.0), ("r", None))
        if circle is None:
            return None
        cx, cy, r = circle
        return _box_corners(cx - r, cy - r, cx + r, cy + r)
    if name == "ellipse":
        ellipse = _lengths(element, ("cx", 0.0), ("cy", 0.0), ("rx", None), ("ry", None))
        if ellipse is None:
            return None
        cx, cy, rx, ry = ellipse
        return _box_corners(cx - rx, cy - ry, cx + rx, cy + ry)
    if name == "line":
        line = _lengths(element, ("x1", 0.0), ("y1", 0.0), ("x2", 0.0), ("y2", 0.0))
        if line is None:
            return None
        return [(line[0], line[1]), (line[2], line[3])]
    if name in ("polyline", "polygon"):
        numbers = re.findall(_NUMBER, element.get("points") or "")
        if not numbers or len(numbers) % 2:
            return None
        values = [float(n) for n in numbers]
        return list(zip(values[0::2], values[1::2]))
    if name == "path":
        return path_vertices(element.get("d") or "")
    return None


def declares_geometry(css: str) -> bool:
    """Whether CSS text sets any of the ``GEOMETRY_PROPERTIES``.

    Examples:
        >>> declares_geometry("rect { x: 5px }"), declares_geometry("rect { fill: red }")
        (True, False)
        >>> declares_geometry("p { max-width: 5px; font-weight: bold }")
        False
    """
    return any(
        re.search(rf"(?:^|[;{{\s]){re.escape(prop)}\s*:", css, re.IGNORECASE)
        for prop in GEOMETRY_PROPERTIES
    )


def current_transform(element: etree._Element, root: etree._Element) -> Optional[Matrix]:
    """The transform from ``element``'s coordinates to the root's, or None.

    None when the element or an ancestor sets up a viewport or reference of
    its own, such as a nested ``<svg>``; carries a malformed transform; is
    clipped, masked or filtered; or places itself with CSS instead of
    attributes (see ``GEOMETRY_PROPERTIES``).
    """
    chain = []
    node: Optional[etree._Element] = element
    while node is not None:
        if any(node.get(a) is not None for a in OBSCURING_ATTRIBUTES):
            return None
        if declares_geometry(node.get("style") or ""):
            return None
        if node is root:
            break
        if etree.QName(node).localname in NEW_VIEWPORTS:
            return None
        chain.append(node)
        node = node.getparent()
    if node is None:
        return None
    matrix = Matrix()
    for ancestor in reversed(chain):
        step = parse_transform(ancestor.get("transform"))
        if step is None:
            return None
        matrix = matrix.then(step)
    return matrix


def node_bbox(
    node: etree._Element,
    root: etree._Element,
    drawn: Optional[Container[etree._Element]] = None,
) -> Optional[Box]:
    """The box ``node``'s shapes occupy in root coordinates, or None.

    The union of every shape in ``node`` (or ``node`` itself), each mapped
    through its transforms; with ``drawn``, only the shapes in it, so a shape
    that is hidden or paints nothing cannot stretch the box. Text is not part
    of it. None when there is no such shape, or any cannot be placed exactly.
    """
    points: list[Point] = []
    for element in node.iter():
        if not isinstance(element.tag, str) or etree.QName(element).localname not in SHAPES:
            continue
        if drawn is not None and element not in drawn:
            continue
        if any(etree.QName(a).localname == "text" for a in element.iterancestors()):
            continue
        local = _local_points(element)
        matrix = current_transform(element, root)
        if local is None or matrix is None:
            return None
        points.extend(matrix.apply(x, y) for x, y in local)
    if not points:
        return None
    xs, ys = [p[0] for p in points], [p[1] for p in points]
    return (min(xs), min(ys), max(xs), max(ys))


def connector_endpoints(element: etree._Element, root: etree._Element) -> Optional[tuple[Point, Point]]:
    """Where a ``<path>``, ``<line>`` or ``<polyline>`` starts and ends, in root coordinates."""
    if etree.QName(element).localname not in ("path", "line", "polyline"):
        return None
    local = _local_points(element)
    matrix = current_transform(element, root)
    if not local or matrix is None:
        return None
    return matrix.apply(*local[0]), matrix.apply(*local[-1])


#: How far outside a node's box a connector may end and still touch it, as a
#: share of the box's shorter side: an arrowhead usually stops a little short.
EDGE_TOLERANCE = 0.15


def touches(point: Point, box: Box) -> bool:
    """Whether ``point`` lies on ``box``, or just outside it.

    Examples:
        >>> touches((61, 15), (0, 0, 60, 30)), touches((70, 15), (0, 0, 60, 30))
        (True, False)
    """
    margin = EDGE_TOLERANCE * min(box[2] - box[0], box[3] - box[1])
    x, y = point
    return box[0] - margin <= x <= box[2] + margin and box[1] - margin <= y <= box[3] + margin
