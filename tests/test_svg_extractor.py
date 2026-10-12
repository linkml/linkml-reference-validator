"""SVG references are matched against the text the figure renders (#104).

A quote must not pass against text a reader of the figure cannot see, so the
extractor reads only rendered text: never attributes, ``<desc>``/``<title>``/
``<metadata>``, unreferenced ``<defs>``, or text that is hidden, transparent
or zero-size. Where the extractor cannot tell what renders (stylesheets with
selectors it does not evaluate, scripts, animations of visibility), it fails
closed and returns no text rather than guessing.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from linkml_reference_validator.etl.acquire import resolve_format, sniff_format
from linkml_reference_validator.etl.extract import ExtractorRegistry
from linkml_reference_validator.etl.extract.svg import SVGExtractor
from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    SVG_EXTRACTION_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.etl.sources.file import FileSource
from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceContent,
    ReferenceValidationConfig,
)
from linkml_reference_validator.validation.repairer import SupportingTextRepairer
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

SVG_OPEN = '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'


def svg(body: str) -> bytes:
    """Wrap ``body`` in an SVG root element."""
    return f"{SVG_OPEN}{body}</svg>".encode()


def extract(body: str) -> str | None:
    """Extract text from an SVG whose root holds ``body``."""
    return SVGExtractor().extract(svg(body), content_type="image/svg+xml")


def quotable(body: str, quote: str) -> bool:
    """Whether ``quote`` matches the text extracted from ``body``, as the validator matches."""
    text = extract(body)
    if text is None:
        return False
    reference = ReferenceContent(reference_id="file:fig.svg", content=text, content_type="local_svg")
    validator = SupportingTextValidator(ReferenceValidationConfig())
    return validator.find_text_in_reference(quote, reference).found


def _xhtml(inner: str) -> str:
    return f'<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">{inner}</div></foreignObject>'


# ---------------------------------------------------------------- registration


def test_registered_for_svg_format():
    assert isinstance(ExtractorRegistry.get("svg"), SVGExtractor)


def test_format_maps_know_svg():
    assert resolve_format("image/svg+xml", None, None) == "svg"
    assert resolve_format(None, "https://x/fig1.SVG", None) == "svg"


@pytest.mark.parametrize(
    "head",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><text>x</text></svg>',
        b'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg"/>',
        b'<?xml version="1.0"?><!-- Generator: Illustrator -->\n'
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd">\n<svg/>',
        b'<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x.dtd">\n<svg/>',
        b'\xef\xbb\xbf<?xml version="1.0"?><svg/>',
        b"\xef\xbb\xbf<svg/>",
    ],
)
def test_sniffs_svg_including_behind_an_xml_declaration(head):
    assert sniff_format(head) == "svg"


def test_sniffs_svg_behind_a_long_licence_comment():
    licence = "<!-- " + "Licensed under CC BY 4.0. " * 400 + "-->"
    assert sniff_format(f'<?xml version="1.0"?>{licence}<svg/>'.encode()) == "svg"


@pytest.mark.parametrize("before,after", [(1_000, 4_000), (60_000, 10_000)])
def test_svg_in_a_comment_that_outruns_the_window_is_not_the_root(before, after):
    # The comment is cut off by the sniffing window; its <svg> is still comment.
    comment = b"<!-- " + b"x" * before + b" <svg> " + b"x" * after + b" -->"
    assert sniff_format(b'<?xml version="1.0"?>' + comment + b"<article/>") == "xml"


def test_jats_still_sniffs_as_xml():
    assert sniff_format(b"<?xml version='1.0'?><article/>") == "xml"


# ---------------------------------------------------------------- text structure


def test_each_text_element_is_its_own_label():
    # Labels are separated by a blank line; a label's own lines by a newline.
    assert extract("<text>PTEN</text><text>AKT</text>") == "PTEN\n\nAKT"


def test_a_quote_cannot_run_from_one_label_into_the_next():
    # Adjacent in document order, but neither label says this.
    body = '<text x="10" y="10">PTEN</text><text x="300" y="200">activates AKT</text>'
    assert not quotable(body, "PTEN activates AKT")
    assert quotable(body, "PTEN")
    assert quotable(body, "activates AKT")


def test_an_explicit_omission_may_join_labels():
    body = "<text>PTEN</text><text>activates AKT</text>"
    assert quotable(body, "PTEN ... activates AKT")


def test_a_foreign_object_label_keeps_its_lines_together():
    body = _xhtml("<p>loss of PTEN</p><p>activates AKT</p>") + "<text>mTOR</text>"
    assert extract(body) == "loss of PTEN\nactivates AKT\n\nmTOR"
    assert quotable(body, "loss of PTEN activates AKT")
    assert not quotable(body, "activates AKT mTOR")


def test_an_svg_nested_in_a_foreign_object_has_labels_of_its_own():
    nested = '<svg xmlns="http://www.w3.org/2000/svg"><text>AKT</text></svg>'
    body = _xhtml(f"<p>PTEN</p>{nested}<p>mTOR</p>")
    assert extract(body) == "PTEN\n\nAKT\n\nmTOR"


def test_multi_tspan_label_is_quotable_across_the_line_break():
    body = (
        '<text x="0" y="10"><tspan x="0" y="10">loss of PTEN</tspan>'
        '<tspan x="0" dy="14">activates AKT</tspan></text>'
    )
    assert extract(body) == "loss of PTEN activates AKT"
    assert quotable(body, "loss of PTEN activates AKT")


def test_unpositioned_tspans_run_together_like_styled_runs():
    assert extract('<text><tspan font-weight="bold">PT</tspan><tspan>EN</tspan></text>') == "PTEN"


def test_pretty_printed_whitespace_collapses():
    assert extract("<text>\n   inhibits\n      signalling\n</text>") == "inhibits signalling"


def test_text_path_and_links_inside_text_are_read():
    body = '<text><a href="https://x"><textPath href="#p">along a curve</textPath></a></text>'
    assert extract(body) == "along a curve"


def test_entities_are_unescaped():
    assert extract("<text>A &amp; B &lt; C</text>") == "A & B < C"


def test_text_outside_text_elements_is_not_rendered():
    assert extract("<g>stray characters<text>label</text></g>") == "label"


def test_str_input_with_encoding_declaration():
    data = f'<?xml version="1.0" encoding="ISO-8859-1"?>{SVG_OPEN}<text>café</text></svg>'
    assert SVGExtractor().extract(data) == "café"


def test_no_text_yields_none():
    assert extract('<rect width="10" height="10"/>') is None


def test_malformed_svg_yields_none():
    assert SVGExtractor().extract(b"<svg><text>unclosed</svg") is None


# ---------------------------------------------------------------- not rendered


@pytest.mark.parametrize(
    "body",
    [
        "<desc>SECRET claim</desc>",
        "<title>SECRET claim</title>",
        "<metadata><rdf>SECRET claim</rdf></metadata>",
        "<!-- SECRET claim -->",
        "<defs><text id='t'>SECRET claim</text></defs>",
        "<symbol id='s'><text>SECRET claim</text></symbol>",
        "<text><title>SECRET claim</title>shown</text>",
        "<text><desc>SECRET claim</desc>shown</text>",
        "<clipPath id='c'><text>SECRET claim</text></clipPath>",
        "<mask id='m'><text>SECRET claim</text></mask>",
        "<pattern id='p'><text>SECRET claim</text></pattern>",
        "<marker id='k'><text>SECRET claim</text></marker>",
    ],
)
def test_non_rendered_text_is_not_quotable(body):
    assert not quotable(body + "<text>shown</text>", "SECRET claim")


@pytest.mark.parametrize(
    "body",
    [
        '<text id="SECRET claim">shown</text>',
        '<text fill="SECRET claim">shown</text>',
        '<rect id="SECRET-claim" class="SECRET claim"/><text>shown</text>',
        '<text font-family="SECRET claim" transform="translate(1 2)">shown</text>',
    ],
)
def test_attribute_values_are_not_quotable(body):
    assert extract(body) == "shown"
    assert not quotable(body, "SECRET claim")


# ---------------------------------------------------------------- hidden


@pytest.mark.parametrize(
    "body",
    [
        '<text display="none">SECRET claim</text>',
        '<text visibility="hidden">SECRET claim</text>',
        '<text visibility="collapse">SECRET claim</text>',
        '<text opacity="0">SECRET claim</text>',
        '<text opacity="0%">SECRET claim</text>',
        '<text style="display: none">SECRET claim</text>',
        '<text style="visibility:hidden">SECRET claim</text>',
        '<text style="opacity:0.0">SECRET claim</text>',
        '<text fill="none">SECRET claim</text>',
        '<text fill="transparent">SECRET claim</text>',
        '<text fill="rgba(0,0,0,0)">SECRET claim</text>',
        '<text fill="#0000">SECRET claim</text>',
        '<text fill="#00000000">SECRET claim</text>',
        '<text fill-opacity="0">SECRET claim</text>',
        '<text font-size="0">SECRET claim</text>',
        '<text style="font-size:0px">SECRET claim</text>',
        '<text><tspan display="none">SECRET claim</tspan></text>',
        '<text><tspan visibility="hidden">SECRET claim</tspan></text>',
    ],
)
def test_hidden_text_is_not_quotable(body):
    assert not quotable(body + "<text>shown</text>", "SECRET claim")


@pytest.mark.parametrize(
    "body",
    [
        '<g display="none"><text>SECRET claim</text></g>',
        '<g opacity="0"><text>SECRET claim</text></g>',
        '<g opacity="0"><text opacity="1">SECRET claim</text></g>',
        '<g display="none"><g><text display="inline">SECRET claim</text></g></g>',
        '<g visibility="hidden"><g><text>SECRET claim</text></g></g>',
        '<g fill="none"><text>SECRET claim</text></g>',
        '<g style="font-size:0"><text style="font-size:2em">SECRET claim</text></g>',
        '<a href="x" display="none"><text>SECRET claim</text></a>',
    ],
)
def test_visibility_is_inherited_from_ancestors(body):
    assert not quotable(body + "<text>shown</text>", "SECRET claim")


@pytest.mark.parametrize(
    "body",
    [
        '<g visibility="hidden"><text visibility="visible">claim shown</text></g>',
        '<g fill="none"><text fill="black">claim shown</text></g>',
        '<g fill-opacity="0"><text fill-opacity="1">claim shown</text></g>',
        '<g font-size="0"><text font-size="12">claim shown</text></g>',
        '<text fill="none" stroke="black">claim shown</text>',
        '<g opacity="0.3"><text>claim shown</text></g>',
    ],
)
def test_children_can_restore_inherited_properties(body):
    assert quotable(body, "claim shown")


@pytest.mark.parametrize(
    "body",
    [
        '<text font-size="12" style="font: 0px sans-serif">SECRET</text>',
        '<text style="font-size:12px; font: 0/0 a">SECRET</text>',
        '<style>.h{font: 0px serif}</style><text class="h" font-size="12">SECRET</text>',
    ],
)
def test_font_shorthand_applies_at_its_place_in_the_cascade(body):
    assert not quotable(body + "<text>shown</text>", "SECRET")


def test_later_font_size_overrides_font_shorthand():
    assert quotable('<text style="font: 0px serif; font-size: 12px">claim shown</text>', "claim shown")


def test_inline_style_beats_presentation_attribute():
    assert not quotable('<text display="inline" style="display:none">SECRET</text>', "SECRET")
    assert quotable('<text display="none" style="display:inline">shown</text>', "shown")


@pytest.mark.parametrize(
    "style,body",
    [
        (".hide{display:none}", '<text class="hide">SECRET claim</text>'),
        (".a, .b { visibility: hidden }", '<text class="x b">SECRET claim</text>'),
        ("#t{opacity:0}", '<text id="t">SECRET claim</text>'),
        ("text{fill:none}", "<text>SECRET claim</text>"),
        ("g.box{display:none}", '<g class="box"><text>SECRET claim</text></g>'),
        ("/* c */ .st0{fill:#FFFFFF;fill-opacity:0}", '<text class="st0">SECRET claim</text>'),
        (".h{display:none!important}", '<text class="h" style="display:inline">SECRET claim</text>'),
    ],
)
def test_stylesheet_rules_hide_text(style, body):
    assert not quotable(f"<style>{style}</style>{body}<text>shown</text>", "SECRET claim")


def test_comment_marker_inside_a_string_does_not_swallow_rules():
    style = """<style>.a{font-family:"x/*"} .h{display:none} .b{font-family:"*/"}</style>"""
    assert not quotable(style + '<text class="h">SECRET</text><text>shown</text>', "SECRET")


def test_stylesheet_specificity_is_respected():
    style = "<style>#t{display:inline} .h{display:none}</style>"
    assert quotable(style + '<text id="t" class="h">claim shown</text>', "claim shown")


def test_stylesheet_that_sets_only_harmless_properties_is_accepted():
    style = "<style>@font-face{font-family:X;src:url(x.woff)} .st0{font-family:Arial} p > b {font-weight:bold}</style>"
    assert extract(style + '<text class="st0">label</text>') == "label"


@pytest.mark.parametrize(
    "style",
    [
        "g > text { display: none }",
        "g text { visibility: hidden }",
        "[data-x] { opacity: 0 }",
        "text:first-child { fill: none }",
        "@media print { .a { display: none } }",
        '@import url("hide.css");',
    ],
)
def test_stylesheet_the_extractor_cannot_evaluate_fails_closed(style):
    assert extract(f"<style>{style}</style><text>shown</text>") is None


@pytest.mark.parametrize(
    "body",
    [
        '<style>.h{--c:none}</style><text class="h" style="fill:var(--c)">SECRET</text>',
        '<text style="opacity:var(--o, 1)">SECRET</text>',
        '<text style="display:var(--d)">SECRET</text>',
        '<text style="font-size:calc(1px - 1px)">SECRET</text>',
        '<text fill="env(x)">SECRET</text>',
    ],
)
def test_computed_visibility_values_fail_closed(body):
    # Whether these paint depends on values the extractor does not compute.
    assert extract(body + "<text>shown</text>") is None


def test_computed_values_of_other_properties_are_accepted():
    assert extract('<text style="--c:red; letter-spacing:calc(1px + 1px)">shown</text>') == "shown"


@pytest.mark.parametrize(
    "body",
    [
        "<script>document.querySelector('text').textContent='x'</script><text>shown</text>",
        '<text>shown<set attributeName="visibility" to="hidden" begin="1s"/></text>',
        '<text opacity="0">x<animate attributeName="opacity" from="0" to="1" dur="1s"/></text>',
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml"><script>x()</script>'
        "<p>shown</p></div></foreignObject>",
    ],
)
def test_scripts_and_visibility_animations_fail_closed(body):
    assert extract(body) is None


XHTML_LABEL = (
    '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">'
    '<span class="n">inhibits</span> mTOR</div></foreignObject>'
)


@pytest.mark.parametrize(
    "style",
    [
        '.n::before{content:"never "}',
        ".n:after { content: ' not' }",
        '@media screen { .n::before { content: "never " } }',
    ],
)
def test_generated_content_fails_closed(style):
    # Rendered "never inhibits mTOR"; read without it, the label inverts.
    assert extract(f"<style>{style}</style>{XHTML_LABEL}") is None


def test_content_that_generates_nothing_is_accepted():
    assert extract("<style>.n::before{content:none}</style>" + XHTML_LABEL) == "inhibits mTOR"


@pytest.mark.parametrize(
    "body",
    [
        '<text direction="rtl" unicode-bidi="bidi-override">PTEN</text>',
        '<text style="direction:rtl; unicode-bidi:bidi-override">PTEN</text>',
        "<style>.r{unicode-bidi:isolate-override;direction:rtl}</style><text class='r'>PTEN</text>",
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml"><bdo dir="rtl">PTEN</bdo></div></foreignObject>',
    ],
)
def test_bidi_overrides_that_reorder_characters_fail_closed(body):
    # Rendered "NETP": the characters are drawn in reverse.
    assert extract(body) is None


@pytest.mark.parametrize(
    "style,inner",
    [
        ('li{list-style-type:"not "}', "<ul><li>inhibits mTOR</li></ul>"),
        ("li{list-style: 'not ' inside}", "<ul><li>inhibits mTOR</li></ul>"),
        ('q{quotes:"never " ""}', "<q>inhibits</q> mTOR"),
        (".s{-webkit-text-security:disc}", '<span class="s">inhibits</span> mTOR'),
    ],
)
def test_other_css_that_changes_drawn_characters_fails_closed(style, inner):
    assert extract(f"<style>{style}</style>" + _xhtml(inner)) is None


@pytest.mark.parametrize(
    "style",
    ["li{list-style-type:decimal}", "li{list-style:none}", "q{quotes:auto}", ".s{-webkit-text-security:none}"],
)
def test_keyword_values_of_those_properties_are_accepted(style):
    assert extract(f"<style>{style}</style>" + _xhtml("<ul><li>inhibits mTOR</li></ul>")) == "inhibits mTOR"


@pytest.mark.parametrize("control", ["\u202e", "\u202d", "\u202b", "\u2067", "\u2068"])
def test_bidi_control_characters_fail_closed(control):
    # U+202E draws "PTEN" as "NETP", as unicode-bidi: bidi-override would.
    assert extract(f"<text>{control}PTEN</text>") is None


def test_rdfa_content_attributes_in_metadata_are_not_generated_content():
    body = '<metadata><rdf:Description xmlns:rdf="urn:rdf" property="dc:title" content="Figure 2"/></metadata>'
    assert extract(body + "<text>shown</text>") == "shown"


def test_empty_generated_content_is_accepted():
    # The clearfix pattern adds no characters.
    style = """<style>.cf::after{content:"";display:table} .b::before{content:''}</style>"""
    assert extract(style + XHTML_LABEL) == "inhibits mTOR"


def test_hiding_a_generated_box_does_not_hide_the_element():
    style = "<style>.n::before{display:none} .n{display:none}</style>"
    assert extract(style + XHTML_LABEL) == "mTOR"


def test_animation_of_unrelated_attribute_is_accepted():
    body = '<text>shown<animate attributeName="x" from="0" to="10" dur="1s"/></text>'
    assert extract(body) == "shown"


# ---------------------------------------------------------------- use / switch


def test_use_renders_referenced_defs_text():
    body = '<defs><text id="t">reused claim</text></defs><use href="#t"/>'
    assert quotable(body, "reused claim")


def test_use_with_xlink_href_renders_symbol():
    body = '<symbol id="s"><text>symbol claim</text></symbol><use xlink:href="#s"/>'
    assert quotable(body, "symbol claim")


def test_hidden_use_does_not_render_its_target():
    body = '<defs><text id="t">SECRET</text></defs><use href="#t" display="none"/><text>shown</text>'
    assert not quotable(body, "SECRET")


def test_use_inherits_properties_into_its_target():
    body = '<defs><text id="t">SECRET</text></defs><use href="#t" visibility="hidden"/><text>shown</text>'
    assert not quotable(body, "SECRET")


def test_use_resolves_a_duplicated_id_to_the_first_element():
    # As getElementById does: the second #a is never what the <use> draws.
    body = '<defs><text id="a">claim shown</text><text id="a">SECRET</text></defs><use href="#a"/>'
    assert extract(body) == "claim shown"


def test_use_cycle_terminates():
    body = '<g id="a"><text>cyclic</text><use href="#b"/></g><g id="b"><use href="#a"/></g>'
    assert quotable(body, "cyclic")


def test_use_expansion_bomb_fails_closed():
    levels = ['<defs><g id="l0"><text>boom</text></g>']
    for i in range(1, 12):
        uses = "".join(f'<use href="#l{i - 1}"/>' for _ in range(10))
        levels.append(f'<g id="l{i}">{uses}</g>')
    body = "".join(levels) + '</defs><use href="#l11"/>'
    assert extract(body) is None


def test_use_bomb_of_skipped_children_fails_closed():
    # Children that are not rendered still cost a visit on every expansion:
    # 1,000 <desc> expanded 1,024 times is a million visits from a 7 KB file.
    # Scaled up, the same shape runs for hours.
    levels = ['<defs><g id="l0"><text>boom</text>' + "<desc/>" * 1000 + "</g>"]
    for i in range(1, 11):
        levels.append(f'<g id="l{i}"><use href="#l{i - 1}"/><use href="#l{i - 1}"/></g>')
    body = "".join(levels) + '</defs><use href="#l10"/>'
    assert extract(body) is None


def test_switch_renders_only_the_first_matching_child():
    body = (
        '<switch><text systemLanguage="fr">SECRET french</text>'
        "<text>english claim</text><text>SECRET fallback</text></switch>"
    )
    assert quotable(body, "english claim")
    assert not quotable(body, "SECRET french")
    assert not quotable(body, "SECRET fallback")


@pytest.mark.parametrize(
    "skipped",
    ["<title>t</title>", "<desc>d</desc>", '<x:meta xmlns:x="urn:x">m</x:meta>', "<!-- c -->"],
)
def test_switch_passes_over_children_that_are_not_rendered(skipped):
    assert extract(f"<switch>{skipped}<text>shown</text><text>SECRET</text></switch>") == "shown"


# ---------------------------------------------------------------- foreignObject


DRAWIO_LABEL = (
    '<g><switch><foreignObject pointer-events="none" width="100%" height="100%" '
    'requiredFeatures="http://www.w3.org/TR/SVG11/feature#Extensibility" '
    'style="overflow: visible; text-align: left;">'
    '<div xmlns="http://www.w3.org/1999/xhtml" style="display: flex; align-items: unsafe center;">'
    '<div data-drawio-colors="color: rgb(0, 0, 0); " style="box-sizing: border-box; font-size: 0px;">'
    '<div style="display: inline-block; font-size: 12px; color: rgb(0, 0, 0);">'
    "PTEN<br/>tumour suppressor</div></div></div></foreignObject>"
    '<text x="60" y="34" fill="rgb(0, 0, 0)" font-size="12px">PTEN tumour s...</text>'
    "</switch></g>"
)


def test_drawio_foreign_object_label_is_quotable():
    assert quotable(DRAWIO_LABEL, "PTEN tumour suppressor")
    # the truncated <text> fallback is not rendered while foreignObject is
    assert extract(DRAWIO_LABEL) == "PTEN\ntumour suppressor"


@pytest.mark.parametrize(
    "inner",
    [
        '<div style="display:none">SECRET</div>',
        '<span style="visibility:hidden">SECRET</span>',
        '<p hidden="">SECRET</p>',
        '<span style="color:transparent">SECRET</span>',
        '<span style="opacity:0">SECRET</span>',
        "<noscript>SECRET</noscript>",
    ],
)
def test_hidden_html_in_foreign_object_is_not_quotable(inner):
    body = (
        '<foreignObject width="100" height="100">'
        f'<div xmlns="http://www.w3.org/1999/xhtml">{inner}<p>shown</p></div></foreignObject>'
    )
    text = extract(body)
    assert text is not None and "shown" in text
    assert not quotable(body, "SECRET")


def test_closed_details_shows_only_its_summary():
    body = _xhtml("<details><summary>PTEN</summary>SECRET <p>SECRET</p></details>")
    assert extract(body) == "PTEN"


def test_open_details_shows_everything():
    body = _xhtml('<details open=""><summary>PTEN</summary><p>tumour suppressor</p></details>')
    assert extract(body) == "PTEN\ntumour suppressor"


def test_html_style_element_in_foreign_object_is_evaluated():
    body = (
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">'
        '<style>.x{display:none}</style><p class="x">SECRET</p><p>shown</p></div></foreignObject>'
    )
    assert extract(body) == "shown"


# ---------------------------------------------------------------- hostile input


def test_external_entities_are_not_resolved(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("SECRET from disk")
    data = (
        f'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY x SYSTEM "file://{secret}">]>'
        f"{SVG_OPEN}<text>&x;shown</text></svg>"
    ).encode()
    text = SVGExtractor().extract(data)
    assert text is None or "SECRET" not in text


def test_internal_entities_expand_as_a_browser_renders_them():
    # Dropping &not; would make the figure read "PTEN does activate AKT".
    data = (
        '<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY not "not"><!ENTITY gene "PTEN">]>'
        f"{SVG_OPEN}<text>&gene; does &not; activate AKT</text></svg>"
    ).encode()
    assert SVGExtractor().extract(data) == "PTEN does not activate AKT"


def test_billion_laughs_does_not_expand():
    entities = '<!ENTITY a "lol">' + "".join(
        f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(9)
    )
    data = f'<?xml version="1.0"?><!DOCTYPE svg [{entities}]>{SVG_OPEN}<text>&j;</text></svg>'
    text = SVGExtractor().extract(data.encode())
    assert text is None or len(text) < 1000


# ---------------------------------------------------------------- file: routing


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)


def test_file_source_reads_svg_through_extractor(tmp_path, config):
    figure = tmp_path / "fig1.svg"
    figure.write_bytes(svg('<desc>SECRET</desc><text fill="red" id="n1">PTEN inhibits AKT</text>'))

    ref = FileSource().fetch(str(figure), config)

    assert ref is not None
    assert ref.content == "PTEN inhibits AKT"
    assert ref.content_type == "local_svg"
    assert ref.title == "fig1.svg"


def test_file_source_svg_with_no_rendered_text_is_unavailable(tmp_path, config):
    figure = tmp_path / "blank.svg"
    figure.write_bytes(svg("<desc>SECRET</desc>"))

    ref = FileSource().fetch(str(figure), config)

    assert ref is not None
    assert ref.content is None
    assert ref.content_type == "unavailable"


def test_file_source_leaves_other_formats_as_raw_text(tmp_path, config):
    page = tmp_path / "notes.html"
    page.write_text("<p>Text &amp; more</p>")
    ref = FileSource().fetch(str(page), config)
    assert ref is not None
    assert ref.content == "<p>Text &amp; more</p>"
    assert ref.content_type == "local_file"


def test_validator_matches_rendered_svg_text_end_to_end(tmp_path, config):
    figure = tmp_path / "pathway.svg"
    figure.write_bytes(
        svg(
            '<desc>AKT activates PTEN</desc>'
            '<text><tspan x="0" y="10">loss of PTEN</tspan><tspan x="0" dy="12">activates AKT</tspan></text>'
        )
    )
    validator = SupportingTextValidator(config)

    assert validator.validate("loss of PTEN activates AKT", f"file:{figure}").is_valid
    assert not validator.validate("AKT activates PTEN", f"file:{figure}").is_valid


@pytest.mark.parametrize(
    "content_type", ["image/svg+xml", "application/xml", "text/html", None]
)
def test_svg_at_a_full_text_location_is_not_full_text(config, content_type):
    # A provider URL that serves a figure or a logo is not the article.
    long_label = "PTEN activates AKT " * 200
    data = b'<?xml version="1.0"?>' + svg(f"<text>{long_label}</text>")
    fetcher = ReferenceFetcher(config)
    location = FullTextLocation(url="https://oa.example/fig1", provider="test")

    with patch.object(fetcher._acquirer, "fetch_bytes", return_value=(data, content_type)):
        text, fmt, pdf_bytes, error = fetcher._materialize(location)

    assert (text, fmt, pdf_bytes, error) == (None, "svg", None, False)


def test_repair_does_not_join_separate_labels():
    # Character normalization alone would turn this into a quote spanning two labels.
    reference = ReferenceContent(
        reference_id="file:fig.svg", content="CO₂ levels\n\nrose", content_type="local_svg"
    )
    result = SupportingTextRepairer(ReferenceValidationConfig()).attempt_repair(
        "CO2 levels rose", "file:fig.svg", reference
    )
    assert result.repaired_text != "CO₂ levels rose"


# ---------------------------------------------------------------- cache stamp


def _entry(reference_id: str, content_type: str, svg_version: int | None) -> str:
    lines = ["---", f"reference_id: {reference_id}", f"extractor_version: {EXTRACTOR_CACHE_VERSION}"]
    if svg_version is not None:
        lines.append(f"svg_extraction_version: {svg_version}")
    lines += [f"content_type: {content_type}", "---", "", "## Content", "", "body"]
    return "\n".join(lines)


def test_svg_file_entry_cached_as_raw_xml_is_stale():
    # Before #104 a file: SVG was cached as raw markup, desc and attributes included.
    assert ReferenceFetcher._is_stale_cache_entry(_entry("file:/x/fig.svg", "local_file", None))
    assert ReferenceFetcher._is_stale_cache_entry(_entry("file:/x/FIG.SVG", "local_file", None))


def test_svg_entry_without_label_boundaries_is_stale():
    # Version 1 joined labels with single newlines, so they could not be told apart.
    assert ReferenceFetcher._is_stale_cache_entry(_entry("file:/x/fig.svg", "local_svg", 1))


def test_current_svg_file_entry_is_fresh():
    entry = _entry("file:/x/fig.svg", "local_svg", SVG_EXTRACTION_CACHE_VERSION)
    assert not ReferenceFetcher._is_stale_cache_entry(entry)


def test_other_file_entries_need_no_svg_stamp():
    assert not ReferenceFetcher._is_stale_cache_entry(_entry("file:/x/notes.md", "local_file", None))


def test_fresh_svg_fetch_is_stamped_and_reloads(tmp_path, config):
    figure = tmp_path / "fig.svg"
    figure.write_bytes(svg("<text>stamped claim</text>"))
    fetcher = ReferenceFetcher(config)

    ref = fetcher.fetch(f"file:{figure}")

    assert ref is not None
    assert ref.metadata["svg_extraction_version"] == SVG_EXTRACTION_CACHE_VERSION
    written = next((tmp_path / "cache").glob("*.md")).read_text()
    assert f"svg_extraction_version: {SVG_EXTRACTION_CACHE_VERSION}" in written
    assert not ReferenceFetcher._is_stale_cache_entry(written)


def _write_raw_markup_entry(fetcher: ReferenceFetcher, figure) -> None:
    """Cache ``figure`` the way FileSource did before #104: raw markup, no SVG stamp."""
    reference_id = f"file:{figure}"
    path = fetcher.get_cache_path(reference_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _entry(reference_id, "local_file", None).replace(
            "body", "<svg><desc>AKT activates PTEN</desc></svg>"
        )
    )


def test_raw_markup_entry_is_not_preserved_when_refresh_finds_no_text(tmp_path, config):
    figure = tmp_path / "fig.svg"
    figure.write_bytes(svg("<script>x()</script><text>shown</text>"))
    fetcher = ReferenceFetcher(config)
    _write_raw_markup_entry(fetcher, figure)

    ref = fetcher.fetch(f"file:{figure}")

    assert ref is not None and ref.content_type == "unavailable"
    assert "AKT activates PTEN" not in fetcher.get_cache_path(f"file:{figure}").read_text()
    validator = SupportingTextValidator(config)
    assert not validator.validate("AKT activates PTEN", f"file:{figure}").is_valid


def test_raw_markup_entry_is_not_served_when_the_file_is_gone(tmp_path, config):
    figure = tmp_path / "moved.svg"
    fetcher = ReferenceFetcher(config)
    _write_raw_markup_entry(fetcher, figure)

    assert fetcher.fetch(f"file:{figure}") is None
    validator = SupportingTextValidator(config)
    assert not validator.validate("AKT activates PTEN", f"file:{figure}").is_valid
