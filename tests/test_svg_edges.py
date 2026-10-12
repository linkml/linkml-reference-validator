"""Edge lines: "<source> <edge label> <target>" from a connector (#104, phase 2).

A connector names its nodes with ``data-source`` and ``data-target``. Those
attributes are not drawn, so on their own they would be a hidden channel: an
edge line is emitted only when what is drawn agrees with them. The connector's
path must visibly start on the source node's box and end on the target's, and
the nodes, the connector and their labels must all be rendered.
"""

from __future__ import annotations

import pytest

from linkml_reference_validator.etl.extract.svg import SVGExtractor
from linkml_reference_validator.etl.extract.svg_geometry import (
    connector_endpoints,
    node_bbox,
    parse_transform,
    path_endpoints,
)
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

from lxml import etree  # type: ignore[import-untyped]

SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg">'
PTEN = '<g id="pten"><rect x="0" y="0" width="60" height="30"/><text x="10" y="20">PTEN</text></g>'
AKT = '<g id="akt"><rect x="200" y="0" width="60" height="30"/><text x="210" y="20">AKT</text></g>'


def connector(d: str = "M60 15 L200 15", label: str = "inhibits", attrs: str = "", path_attrs: str = "") -> str:
    """A connector from #pten to #akt drawn along ``d``."""
    text = f'<text x="120" y="10">{label}</text>' if label else ""
    return (
        f'<g data-source="pten" data-target="akt" {attrs}>'
        f'<path d="{d}" stroke="black" fill="none" {path_attrs}/>{text}</g>'
    )


def extract(body: str) -> str | None:
    return SVGExtractor().extract(f"{SVG_OPEN}{body}</svg>".encode())


def quotable(body: str, quote: str) -> bool:
    text = extract(body)
    if text is None:
        return False
    reference = ReferenceContent(reference_id="file:fig.svg", content=text, content_type="local_svg")
    return SupportingTextValidator(ReferenceValidationConfig()).find_text_in_reference(quote, reference).found


# ---------------------------------------------------------------- edge lines


def test_a_connector_touching_both_nodes_yields_an_edge_line():
    body = PTEN + AKT + connector()
    assert extract(body) == "PTEN\n\nAKT\n\ninhibits\n\nPTEN inhibits AKT"
    assert quotable(body, "PTEN inhibits AKT")


def test_an_edge_line_is_its_own_label():
    body = PTEN + AKT + connector() + '<text x="0" y="200">mTOR</text>'
    assert not quotable(body, "PTEN inhibits AKT mTOR")


@pytest.mark.parametrize(
    "d",
    [
        "M60 15 L120 15 L120 60 L200 15",  # an elbow
        "M 62 15 C 100 -40, 160 -40, 198 15",  # a curve, ending just short of the box (an arrowhead)
        "m60 15 l140 0",  # relative commands
        "M60 15 H200",
        "M60 15 h70 v10 v-10 h70",
    ],
)
def test_connector_paths_of_any_shape_count_by_their_endpoints(d):
    assert quotable(PTEN + AKT + connector(d=d), "PTEN inhibits AKT")


def test_a_line_element_can_be_the_connector():
    body = (
        PTEN + AKT + '<g data-source="pten" data-target="akt">'
        '<line x1="60" y1="15" x2="200" y2="15" stroke="black"/><text>inhibits</text></g>'
    )
    assert quotable(body, "PTEN inhibits AKT")


def test_nodes_may_be_circles_ellipses_and_polygons():
    body = (
        '<g id="pten"><circle cx="30" cy="15" r="15"/><text>PTEN</text></g>'
        '<g id="akt"><polygon points="200,0 260,0 260,30 200,30"/><text>AKT</text></g>'
        + connector(d="M45 15 L200 15")
    )
    assert quotable(body, "PTEN inhibits AKT")


def test_transforms_are_applied_to_nodes_and_connector():
    body = (
        '<g transform="translate(100 50)">'
        '<g id="pten" transform="scale(2)"><rect width="30" height="15"/><text>PTEN</text></g>'
        '<g id="akt" transform="translate(200 0)"><rect width="60" height="30"/><text>AKT</text></g>'
        "</g>"
        '<g data-source="pten" data-target="akt"><path d="M160 65 L300 65" stroke="black"/>'
        "<text>inhibits</text></g>"
    )
    assert quotable(body, "PTEN inhibits AKT")


# ---------------------------------------------------------------- no edge line


@pytest.mark.parametrize(
    "d",
    [
        "M60 100 L200 100",  # runs below both nodes
        "M60 15 L150 15",  # stops short of the target
        "M300 15 L200 15",  # starts beside the target, not at the source
        "M200 15 L60 15",  # runs from target to source: the attributes name the other direction
    ],
)
def test_a_connector_that_does_not_join_the_named_nodes_yields_none(d):
    assert not quotable(PTEN + AKT + connector(d=d), "PTEN inhibits AKT")


def test_attributes_alone_are_not_an_edge():
    # The two nodes are joined by nothing that is drawn.
    body = PTEN + AKT + '<text data-source="pten" data-target="akt">inhibits</text>'
    assert not quotable(body, "PTEN inhibits AKT")


@pytest.mark.parametrize(
    "body",
    [
        PTEN + AKT + connector(attrs='display="none"'),
        PTEN + AKT + connector(path_attrs='stroke-opacity="0"'),
        PTEN + AKT + connector(path_attrs='style="stroke:none"'),
        PTEN + AKT + connector(path_attrs='stroke-width="0"'),
        PTEN + AKT + connector(path_attrs='visibility="hidden"'),
        PTEN + '<g display="none">' + AKT + "</g>" + connector(),
        PTEN.replace("PTEN</text>", "PTEN</text>").replace("<text", '<text opacity="0"') + AKT + connector(),
        PTEN + AKT + connector(label=""),
        PTEN + AKT + connector().replace("<text", '<text fill="none"'),
    ],
    ids=[
        "hidden-connector", "transparent-stroke", "no-stroke", "zero-width", "invisible-path",
        "hidden-node", "hidden-node-label", "no-edge-label", "invisible-edge-label",
    ],
)
def test_nothing_hidden_takes_part_in_an_edge(body):
    assert not quotable(body, "PTEN inhibits AKT")


def test_a_missing_node_yields_none():
    assert not quotable(PTEN + connector(), "PTEN inhibits AKT")


def test_a_node_drawn_only_through_use_yields_none():
    # Its geometry depends on the <use>; the extractor does not follow it for edges.
    body = PTEN + f"<defs>{AKT}</defs>" + '<use href="#akt"/>' + connector()
    assert not quotable(body, "PTEN inhibits AKT")


def test_units_the_extractor_cannot_place_yield_none():
    body = PTEN.replace('width="60"', 'width="10%"') + AKT + connector()
    assert not quotable(body, "PTEN inhibits AKT")


# ---------------------------------------------------------------- geometry


def test_parse_transform_composes_left_to_right():
    matrix = parse_transform("translate(10 20) scale(2)")
    assert matrix is not None
    assert matrix.apply(1, 1) == (12, 22)


@pytest.mark.parametrize("value", ["bogus(1)", "translate(1 2", "matrix(1 2 3)"])
def test_unparseable_transforms_are_none(value):
    assert parse_transform(value) is None


@pytest.mark.parametrize(
    "d,expected",
    [
        ("M0 0 L10 0", ((0, 0), (10, 0))),
        ("M1,2 10,20", ((1, 2), (10, 20))),
        ("m1 2 l3 4", ((1, 2), (4, 6))),
        ("M0 0 Q 5 5 10 0 T 20 0", ((0, 0), (20, 0))),
        ("M0 0 A 5 5 0 0 1 10 0", ((0, 0), (10, 0))),
        ("M0 0 L10 0 Z", ((0, 0), (0, 0))),
        ("M0 0 c1 1 2 2 3 3 s4 4 5 5", ((0, 0), (8, 8))),
        ("M0 0 1e1 -2.5e0", ((0, 0), (10, -2.5))),
    ],
)
def test_path_endpoints(d, expected):
    assert path_endpoints(d) == expected


@pytest.mark.parametrize("d", ["", "L10 0", "M0 0 X5", "M0"])
def test_malformed_paths_have_no_endpoints(d):
    assert path_endpoints(d) is None


def test_node_bbox_unions_shapes_and_ignores_text():
    root = etree.fromstring(
        f'{SVG_OPEN}<g id="n"><rect x="10" y="10" width="20" height="10"/>'
        '<circle cx="50" cy="15" r="5"/><text x="500" y="500">far away</text></g></svg>'
    )
    assert node_bbox(root.find(".//{*}g"), root) == (10, 10, 55, 20)


def test_connector_endpoints_apply_ancestor_transforms():
    root = etree.fromstring(
        f'{SVG_OPEN}<g transform="translate(5 5)"><path d="M0 0 L10 0"/></g></svg>'
    )
    assert connector_endpoints(root.find(".//{*}path"), root) == ((5, 5), (15, 5))
