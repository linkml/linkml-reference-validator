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


#: An arrowhead marker; every figure below defines it.
ARROW_DEFS = '<defs><marker id="arrow"><path d="M0 0 L10 5 L0 10 z"/></marker></defs>'
END = 'marker-end="url(#arrow)"'


def connector(
    d: str = "M60 15 L200 15",
    label: str = "inhibits",
    attrs: str = "",
    path_attrs: str = "",
    marker: str = END,
) -> str:
    """A connector from #pten to #akt drawn along ``d``, an arrowhead at its end."""
    text = f'<text x="120" y="10">{label}</text>' if label else ""
    return (
        f'<g data-source="pten" data-target="akt" {attrs}>'
        f'<path d="{d}" stroke="black" fill="none" {marker} {path_attrs}/>{text}</g>'
    )


def extract(body: str) -> str | None:
    return SVGExtractor().extract(f"{SVG_OPEN}{ARROW_DEFS}{body}</svg>".encode())


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
        f'<line x1="60" y1="15" x2="200" y2="15" stroke="black" {END}/><text>inhibits</text></g>'
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
        f'<g data-source="pten" data-target="akt"><path d="M160 65 L300 65" stroke="black" {END}/>'
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


# The visible AKT box sits at x=2000, far from where the connector ends.
FAR_AKT = '<g id="akt"><rect x="2000" y="0" width="60" height="30"/><text x="2010" y="20">AKT</text>{extra}</g>'


@pytest.mark.parametrize(
    "extra",
    [
        '<rect x="0" y="0" width="3000" height="3000" display="none"/>',
        '<rect x="0" y="0" width="3000" height="3000" fill="none"/>',
        '<rect x="0" y="0" width="3000" height="3000" opacity="0"/>',
        '<rect x="0" y="0" width="3000" height="3000" visibility="hidden"/>',
        '<g display="none"><rect x="0" y="0" width="3000" height="3000"/></g>',
    ],
    ids=["display-none", "no-paint", "opacity-0", "hidden", "hidden-group"],
)
def test_shapes_that_are_not_drawn_do_not_stretch_a_node(extra):
    body = PTEN + FAR_AKT.format(extra=extra) + connector()
    assert not quotable(body, "PTEN inhibits AKT")


def test_a_stroked_but_unfilled_shape_still_draws_a_node():
    body = PTEN + AKT.replace("<rect", '<rect fill="none" stroke="black"') + connector()
    assert quotable(body, "PTEN inhibits AKT")


@pytest.mark.parametrize(
    "where",
    ["connector", "node"],
)
@pytest.mark.parametrize("effect", ["clip-path", "mask", "filter"])
def test_clipped_masked_or_filtered_geometry_confirms_nothing(where, effect):
    defs = '<defs><clipPath id="fx"><rect width="0" height="0"/></clipPath></defs>'
    attr = f'{effect}="url(#fx)"'
    if where == "connector":
        body = defs + PTEN + AKT + connector(path_attrs=attr)
    else:
        body = defs + PTEN + AKT.replace("<rect", f"<rect {attr}") + connector()
    assert not quotable(body, "PTEN inhibits AKT")


@pytest.mark.parametrize(
    "body",
    [
        PTEN + AKT.replace('id="akt"', 'id="akt" style="transform: translate(5000px, 5000px)"') + connector(),
        PTEN + AKT.replace("<rect", '<rect style="x: 5000px"') + connector(),
        PTEN + AKT + connector(path_attrs="style=\"d: path('M0 0 L1 1')\""),
        "<style>#akt { transform: translate(5000px, 0) }</style>" + PTEN + AKT + connector(),
        "<style>rect { x: 5000px }</style>" + PTEN + AKT + connector(),
        PTEN + AKT.replace("</g>", '<animateTransform attributeName="transform" type="translate" to="5000 0"/></g>') + connector(),
        PTEN + AKT.replace("</g>", '<animateMotion path="M0 0 L5000 0"/></g>') + connector(),
        PTEN + AKT.replace("<rect", '<rect><animate attributeName="x" to="5000"/></rect><rect') + connector(),
    ],
    ids=[
        "css-transform", "css-x", "css-d", "stylesheet-transform", "stylesheet-x",
        "animateTransform", "animateMotion", "animate-x",
    ],
)
def test_geometry_set_or_moved_by_css_or_animation_confirms_nothing(body):
    # The extractor places shapes by their attributes; anything else may put
    # them elsewhere, so it gives no edge rather than a wrong one.
    assert not quotable(body, "PTEN inhibits AKT")


@pytest.mark.parametrize(
    "path_attrs",
    [
        'marker-start="url(#arrow)"',
        'marker-start="url(#arrow)" marker-end="url(#arrow)"',
        'style="marker-start: url(#arrow)"',
        'style="marker: url(#arrow)"',
    ],
)
def test_an_arrowhead_at_the_source_contradicts_the_direction(path_attrs):
    assert not quotable(PTEN + AKT + connector(path_attrs=path_attrs, marker=""), "PTEN inhibits AKT")


def test_an_arrowhead_at_the_target_agrees():
    assert quotable(PTEN + AKT + connector(), "PTEN inhibits AKT")


@pytest.mark.parametrize(
    "attrs,marker",
    [
        ('marker-start="url(#arrow)"', END),  # inherited from the connector group
        ('style="marker: url(#arrow)"', ""),
    ],
)
def test_an_inherited_arrowhead_at_the_source_contradicts_the_direction(attrs, marker):
    assert not quotable(PTEN + AKT + connector(attrs=attrs, marker=marker), "PTEN inhibits AKT")


def test_an_inherited_arrowhead_at_the_target_agrees():
    assert quotable(PTEN + AKT + connector(attrs=END, marker=""), "PTEN inhibits AKT")


@pytest.mark.parametrize(
    "attrs,marker",
    [
        ("", ""),  # a plain line: nothing drawn says which way it reads
        ("", 'marker-end="url(#nowhere)"'),  # a broken reference draws no arrowhead
        (END, 'marker-end="none"'),  # the shape turns off what it inherits
        ("", 'style="marker-end: none" marker-end="url(#arrow)"'),
    ],
    ids=["no-marker", "unresolved", "inherited-then-none", "style-beats-attribute"],
)
def test_without_a_drawn_arrowhead_at_the_target_there_is_no_direction(attrs, marker):
    # Swapping data-source and data-target would otherwise reverse the line
    # for the same picture: undrawn attributes must not decide the direction.
    assert not quotable(PTEN + AKT + connector(attrs=attrs, marker=marker), "PTEN inhibits AKT")
    assert not quotable(PTEN + AKT + connector(attrs=attrs, marker=marker), "AKT inhibits PTEN")


def test_markers_set_by_a_stylesheet_confirm_nothing():
    body = "<style>path { marker-start: url(#arrow) }</style>" + PTEN + AKT + connector()
    assert not quotable(body, "PTEN inhibits AKT")


def test_labels_are_still_read_when_edges_cannot_be_confirmed():
    body = "<style>#akt { transform: translate(5000px, 0) }</style>" + PTEN + AKT + connector()
    assert extract(body) == "PTEN\n\nAKT\n\ninhibits"


def test_any_stroked_shape_of_the_connector_may_confirm_it():
    # An arrowhead drawn before the line must not hide the line.
    body = (
        PTEN + AKT + '<g data-source="pten" data-target="akt">'
        '<path d="M195 10 L200 15 L195 20" stroke="black" fill="none"/>'
        f'<path d="M60 15 L200 15" stroke="black" {END}/><text>inhibits</text></g>'
    )
    assert quotable(body, "PTEN inhibits AKT")


def test_a_node_containing_the_other_yields_none():
    # The compartment's labels and box would take in TP53's.
    body = (
        '<g id="pten"><rect x="0" y="0" width="300" height="100"/><text>Nucleus</text>'
        '<g id="akt"><rect x="200" y="0" width="60" height="30"/><text>TP53</text></g></g>'
        + connector()
    )
    assert not quotable(body, "TP53 inhibits TP53")
    assert not quotable(body, "Nucleus TP53 inhibits TP53")


def test_a_node_containing_the_connector_yields_none():
    # PTEN's labels would take in the edge label: "PTEN inhibits inhibits AKT".
    body = PTEN.replace("</g>", connector() + "</g>") + AKT
    labels = (extract(body) or "").split("\n\n")
    assert not [label for label in labels if "PTEN" in label and "AKT" in label]


def test_a_drawn_self_loop_is_an_edge():
    loop = (
        '<g data-source="pten" data-target="pten">'
        f'<path d="M30 0 C30 -40, 50 -40, 50 0" stroke="black" fill="none" {END}/><text>activates</text></g>'
    )
    assert quotable(PTEN + loop, "PTEN activates PTEN")


def test_a_missing_node_yields_none():
    assert not quotable(PTEN + connector(), "PTEN inhibits AKT")


def test_a_node_drawn_only_through_use_yields_none():
    # Its geometry depends on the <use>; the extractor does not follow it for edges.
    body = PTEN + f"<defs>{AKT}</defs>" + '<use href="#akt"/>' + connector()
    assert not quotable(body, "PTEN inhibits AKT")


def test_units_the_extractor_cannot_place_yield_none():
    body = PTEN.replace('width="60"', 'width="10%"') + AKT + connector()
    assert not quotable(body, "PTEN inhibits AKT")


def test_svg_entry_without_edge_lines_is_stale():
    from linkml_reference_validator.etl.reference_fetcher import (
        EXTRACTOR_CACHE_VERSION,
        ReferenceFetcher,
    )

    entry = (
        f"---\nreference_id: file:/x/fig.svg\nextractor_version: {EXTRACTOR_CACHE_VERSION}\n"
        "svg_extraction_version: 2\ncontent_type: local_svg\n---\n\n## Content\n\nPTEN"
    )
    assert ReferenceFetcher._is_stale_cache_entry(entry)


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
