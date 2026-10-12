"""SVG references are matched against the text the figure renders (#104).

A quote must not pass against text a reader of the figure cannot see, so the
extractor reads only rendered text: never attributes, ``<desc>``/``<title>``/
``<metadata>``, unreferenced ``<defs>``, or text that is hidden, transparent
or zero-size. Where the extractor cannot tell what renders (stylesheets with
selectors it does not evaluate, scripts, animations of visibility), it fails
closed and returns no text rather than guessing.
"""

from __future__ import annotations

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
from linkml_reference_validator.models import ReferenceValidationConfig
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
    normalize = SupportingTextValidator.normalize_text
    return normalize(quote) in normalize(text)


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
    ],
)
def test_sniffs_svg_including_behind_an_xml_declaration(head):
    assert sniff_format(head) == "svg"


def test_jats_still_sniffs_as_xml():
    assert sniff_format(b"<?xml version='1.0'?><article/>") == "xml"


# ---------------------------------------------------------------- text structure


def test_one_line_per_text_element():
    assert extract("<text>PTEN</text><text>AKT</text>") == "PTEN\nAKT"


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
        "<script>document.querySelector('text').textContent='x'</script><text>shown</text>",
        '<text>shown<set attributeName="visibility" to="hidden" begin="1s"/></text>',
        '<text opacity="0">x<animate attributeName="opacity" from="0" to="1" dur="1s"/></text>',
        '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml"><script>x()</script>'
        "<p>shown</p></div></foreignObject>",
    ],
)
def test_scripts_and_visibility_animations_fail_closed(body):
    assert extract(body) is None


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


def test_switch_renders_only_the_first_matching_child():
    body = (
        '<switch><text systemLanguage="fr">SECRET french</text>'
        "<text>english claim</text><text>SECRET fallback</text></switch>"
    )
    assert quotable(body, "english claim")
    assert not quotable(body, "SECRET french")
    assert not quotable(body, "SECRET fallback")


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
