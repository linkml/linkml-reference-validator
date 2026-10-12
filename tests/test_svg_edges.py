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


def edges(body: str) -> list[str]:
    """The edge lines extracted from ``body``: every node and edge label here is one word."""
    return [label for label in (extract(body) or "").split("\n\n") if " " in label]


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


REVERSED = "M200 15 L60 15"  # drawn from AKT's box to PTEN's
START = 'marker-start="url(#arrow)"'
FORWARD, BACKWARD, BOTH = ["PTEN inhibits AKT"], ["AKT inhibits PTEN"], ["PTEN inhibits AKT", "AKT inhibits PTEN"]


@pytest.mark.parametrize(
    "d,marker,expected",
    [
        ("M60 15 L200 15", END, FORWARD),
        ("M60 15 L200 15", START, BACKWARD),  # the arrowhead points at PTEN
        ("M60 15 L200 15", f"{START} {END}", BOTH),
        ("M60 15 L200 15", 'style="marker-start: url(#arrow)"', BACKWARD),
        ("M60 15 L200 15", 'style="marker: url(#arrow)"', BOTH),  # the shorthand sets both ends
        (REVERSED, END, BACKWARD),
        (REVERSED, START, FORWARD),
    ],
    ids=["end", "start", "both", "style-start", "style-shorthand", "reversed-end", "reversed-start"],
)
def test_a_drawn_arrowhead_decides_the_direction(d, marker, expected):
    # The drawing wins over data-source and data-target, as in drawio.
    assert edges(PTEN + AKT + connector(d=d, marker=marker)) == expected


@pytest.mark.parametrize(
    "attrs,marker,expected",
    [
        (START, END, BOTH),  # marker-start inherited from the connector group
        (START, "", BACKWARD),
        ('style="marker: url(#arrow)"', "", BOTH),
        (END, "", FORWARD),
    ],
    ids=["start-and-own-end", "start", "shorthand", "end"],
)
def test_inherited_arrowheads_decide_the_direction(attrs, marker, expected):
    assert edges(PTEN + AKT + connector(attrs=attrs, marker=marker)) == expected


@pytest.mark.parametrize(
    "attrs,marker",
    [
        ("", ""),  # a plain line
        ("", 'marker-end="url(#nowhere)"'),  # a broken reference draws no arrowhead
        (END, 'marker-end="none"'),  # the shape turns off what it inherits
        ("", 'style="marker-end: none" marker-end="url(#arrow)"'),
    ],
    ids=["no-marker", "unresolved", "inherited-then-none", "style-beats-attribute"],
)
def test_without_a_drawn_arrowhead_the_line_reads_source_to_target(attrs, marker):
    assert edges(PTEN + AKT + connector(attrs=attrs, marker=marker)) == FORWARD
    # Which way the path runs is not drawn either.
    assert edges(PTEN + AKT + connector(d=REVERSED, attrs=attrs, marker=marker)) == FORWARD


def test_without_an_arrowhead_the_attributes_name_the_direction():
    swapped = connector(marker="").replace('data-source="pten" data-target="akt"', 'data-source="akt" data-target="pten"')
    assert edges(PTEN + AKT + swapped) == BACKWARD


@pytest.mark.parametrize(
    "head",
    [
        '<polygon points="60,15 70,10 70,20"/>',  # a triangle at PTEN: the drawing points back
        '<polygon points="200,15 190,10 190,20"/>',  # at AKT: agrees, but can't be told apart
        '<path d="M70 10 L60 15 L70 20" stroke="black" fill="none"/>',  # a stroked chevron
        '<use href="#tri" x="60" y="15"/>',  # a triangle at PTEN, drawn through <use>
        '<image href="data:," x="60" y="10" width="10" height="10"/>',  # an icon at PTEN
    ],
    ids=["at-source", "at-target", "chevron", "use", "image"],
)
def test_an_arrowhead_drawn_as_a_separate_shape_gives_no_direction(head):
    # The extractor can't tell which way a shape points, and reading the
    # attributes' order could contradict the drawn arrow.
    tri = '<defs><polygon id="tri" points="0,0 10,-5 10,5"/></defs>'
    body = tri + PTEN + AKT + connector(marker="").replace("<text", head + "<text")
    assert edges(body) == []


def test_a_shape_away_from_the_line_ends_and_nodes_is_not_an_arrowhead():
    # A label background in mid-line, as many exporters draw one.
    background = '<rect x="110" y="0" width="40" height="12" fill="white"/>'
    body = PTEN + AKT + connector(marker="").replace("<text", background + "<text")
    assert edges(body) == FORWARD


def test_a_plain_stroke_beside_one_with_an_unsure_marker_gives_no_direction():
    unsure = '<defs><marker id="unsure"><use href="#arrow"/></marker></defs>'
    body = unsure + PTEN + AKT + (
        '<g data-source="pten" data-target="akt">'
        '<path d="M60 15 L200 15" stroke="black" marker-start="url(#unsure)"/>'
        '<path d="M60 15 L200 15" stroke="black"/><text>inhibits</text></g>'
    )
    assert edges(body) == []


def test_an_arrowhead_on_overlapping_nodes_gives_no_direction():
    # Both ends touch both boxes, so the drawing can't say which node it points at.
    overlapping = AKT.replace('x="200"', 'x="0"').replace('x="210"', 'x="10"')
    assert edges(PTEN + overlapping + connector(d="M30 15 L40 15")) == []
    assert edges(PTEN + overlapping + connector(d="M30 15 L40 15", marker="")) == FORWARD


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


def test_a_connector_containing_its_nodes_yields_none():
    # The edge label would take in both node labels: "PTEN PTEN AKT inhibits AKT".
    body = (
        '<g data-source="pten" data-target="akt">' + PTEN + AKT
        + f'<path d="M60 15 L200 15" stroke="black" {END}/><text>inhibits</text></g>'
    )
    labels = (extract(body) or "").split("\n\n")
    assert not [label for label in labels if "PTEN" in label and "AKT" in label]


@pytest.mark.parametrize(
    "marker",
    [
        '<marker id="ghost"/>',
        '<marker id="ghost"><path d="M0 0 L10 5 L0 10 z" fill="none"/></marker>',
        '<marker id="ghost"><path d="M0 0 L10 5 L0 10 z" opacity="0"/></marker>',
        '<marker id="ghost" markerWidth="0"><path d="M0 0 L10 5 L0 10 z"/></marker>',
        '<marker id="ghost"><g display="none"><path d="M0 0 L10 5 L0 10 z"/></g></marker>',
        '<marker id="ghost" opacity="0"><path d="M0 0 L10 5 L0 10 z"/></marker>',
        '<marker id="ghost" viewBox="0 0 0 10"><path d="M0 0 L10 5 L0 10 z"/></marker>',
        '<marker id="ghost"><path d="M0 0 L10 5 L0 10 z" fill="context-fill"/></marker>',
        '<marker id="ghost"><path d="M0 0 L10 5 L0 10 z" fill="none" stroke="context-fill"/></marker>',
        '<g display="none" fill="none"><marker id="ghost"><path d="M0 0 L10 5 L0 10 z"/></marker></g>',
    ],
    ids=[
        "empty", "unpainted", "transparent", "zero-size", "hidden-group",
        "transparent-marker", "zero-viewbox", "context-fill", "context-fill-stroke",
        "unpainted-hidden-ancestor",
    ],
)
def test_an_arrowhead_marker_that_draws_nothing_gives_no_direction(marker):
    # Drawn, it would point at PTEN; drawing nothing, the line is undirected.
    body = f"<defs>{marker}</defs>" + PTEN + AKT + connector(marker='marker-start="url(#ghost)"')
    assert edges(body) == FORWARD


def test_a_marker_under_a_hidden_ancestor_still_draws():
    # Markers are drawn where they are used, whatever their ancestors' display.
    marker = '<defs><g display="none"><marker id="kept"><path d="M0 0 L10 5 L0 10 z"/></marker></g></defs>'
    assert edges(marker + PTEN + AKT + connector(marker='marker-start="url(#kept)"')) == BACKWARD


def test_display_does_not_hide_a_marker():
    marker = '<defs><marker id="kept" display="none"><path d="M0 0 L10 5 L0 10 z"/></marker></defs>'
    assert edges(marker + PTEN + AKT + connector(marker='marker-start="url(#kept)"')) == BACKWARD


@pytest.mark.parametrize(
    "marker",
    [
        '<marker id="unsure"><path d="M0 0 L10 5 L0 10 z" fill="var(--edge)"/></marker>',
        '<marker id="unsure" viewBox="0 0 10px 10"><path d="M0 0 L10 5 L0 10 z"/></marker>',
        '<marker id="unsure"><use href="#head"/></marker><path id="head" d="M0 0 L10 5 L0 10 z"/>',
        '<marker id="unsure"><text>&gt;</text></marker>',
        '<marker id="unsure"><image href="data:," width="10" height="10"/></marker>',
    ],
    ids=["computed-value", "bad-viewbox", "use", "text", "image"],
)
def test_a_marker_that_may_draw_loses_only_the_edge_line(marker):
    # Whether the arrowhead is drawn is unknown, so neither direction is safe.
    body = f"<defs>{marker}</defs>" + PTEN + AKT + connector(marker='marker-start="url(#unsure)"')
    text = extract(body)
    assert text is not None
    assert {"PTEN", "AKT", "inhibits"} <= set(text.split("\n\n"))
    assert edges(body) == []


def test_a_later_shorthand_in_one_style_wins():
    path_style = 'style="marker-start: url(#arrow); marker: none"'
    assert edges(PTEN + AKT + connector(marker="", path_attrs=path_style)) == FORWARD


def test_inherit_keeps_walking_up_for_dashes_and_markers():
    dashes = connector(attrs='stroke-dasharray="0 1000"', path_attrs='stroke-dasharray="inherit"')
    assert not quotable(PTEN + AKT + dashes, "PTEN inhibits AKT")
    starts = connector(attrs=START, marker="", path_attrs='marker-start="inherit"')
    assert edges(PTEN + AKT + starts) == BACKWARD


def test_a_drawn_self_loop_is_an_edge():
    loop = (
        '<g data-source="pten" data-target="pten">'
        f'<path d="M30 0 C30 -40, 50 -40, 50 0" stroke="black" fill="none" {END}/><text>activates</text></g>'
    )
    assert quotable(PTEN + loop, "PTEN activates PTEN")


def test_a_self_loop_with_arrowheads_at_both_ends_is_one_line():
    loop = (
        '<g data-source="pten" data-target="pten">'
        f'<path d="M30 0 C30 -40, 50 -40, 50 0" stroke="black" fill="none" {START} {END}/><text>activates</text></g>'
    )
    assert edges(PTEN + loop) == ["PTEN activates PTEN"]


@pytest.mark.parametrize(
    "dashes",
    ['stroke-dasharray="0 1000"', 'stroke-dasharray="0,5,0,5"', 'style="stroke-dasharray: 0 10"'],
)
def test_a_stroke_of_zero_length_dashes_draws_nothing(dashes):
    assert not quotable(PTEN + AKT + connector(path_attrs=dashes), "PTEN inhibits AKT")


def test_an_inherited_zero_dash_stroke_draws_nothing():
    assert not quotable(PTEN + AKT + connector(attrs='stroke-dasharray="0 9"'), "PTEN inhibits AKT")


def test_a_dashed_stroke_still_draws():
    assert quotable(PTEN + AKT + connector(path_attrs='stroke-dasharray="4 2"'), "PTEN inhibits AKT")


def test_a_stylesheet_dash_pattern_confirms_nothing():
    body = "<style>path { stroke-dasharray: 0 99 }</style>" + PTEN + AKT + connector()
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


@pytest.mark.parametrize(
    "d,expected",
    [
        ("M0 0 a5 5 0 0010 10", ((0, 0), (10, 10))),  # flags run into the end point
        ("M0 0 A5 5 0 1 1 20 0", ((0, 0), (20, 0))),
        ("M0 0 a5,5,30,1,0,-3,4", ((0, 0), (-3, 4))),
    ],
)
def test_arc_flags_are_single_characters(d, expected):
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
