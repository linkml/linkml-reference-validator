"""Native .drawio files are read as the labels they draw (#104, phase 3).

A ``.drawio`` file is an ``<mxfile>`` of ``<diagram>`` pages, each holding an
``<mxGraphModel>`` either as XML or compressed (base64 of raw-deflated,
URL-encoded XML). Each visible cell's label is a label of its own; an edge
between two labelled cells adds an edge line, "<source> <edge label>
<target>". As for SVG, only what is drawn counts: hidden cells and layers,
collapsed groups, labels switched off or transparent, and the HTML a label
hides are never quotable.
"""

from __future__ import annotations

import base64
import zlib
from urllib.parse import quote

import pytest

from linkml_reference_validator.etl.acquire import resolve_format, sniff_format
from linkml_reference_validator.etl.extract import ExtractorRegistry
from linkml_reference_validator.etl.extract.drawio import DrawioExtractor
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.etl.sources.file import FileSource
from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceContent,
    ReferenceValidationConfig,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

LAYER = '<mxCell id="0"/><mxCell id="1" parent="0"/>'
PTEN = '<mxCell id="pten" value="PTEN" style="rounded=0;" vertex="1" parent="1"><mxGeometry x="0" y="0" width="60" height="30" as="geometry"/></mxCell>'
AKT = '<mxCell id="akt" value="AKT" vertex="1" parent="1"><mxGeometry x="200" y="0" width="60" height="30" as="geometry"/></mxCell>'
EDGE = '<mxCell id="e1" value="inhibits" style="endArrow=block;" edge="1" parent="1" source="pten" target="akt"><mxGeometry relative="1" as="geometry"/></mxCell>'


def model(cells: str) -> str:
    return f"<mxGraphModel><root>{LAYER}{cells}</root></mxGraphModel>"


def drawio(*pages: str, compressed: bool = False) -> bytes:
    """An .drawio file with one <diagram> per page of cells."""
    diagrams = []
    for index, cells in enumerate(pages):
        xml = model(cells)
        if compressed:
            deflater = zlib.compressobj(9, zlib.DEFLATED, -15)
            raw = deflater.compress(quote(xml).encode()) + deflater.flush()
            body = base64.b64encode(raw).decode()
        else:
            body = xml
        diagrams.append(f'<diagram id="d{index}" name="Page-{index}">{body}</diagram>')
    return f'<mxfile host="app.diagrams.net">{"".join(diagrams)}</mxfile>'.encode()


def extract(*pages: str, compressed: bool = False) -> str | None:
    return DrawioExtractor().extract(drawio(*pages, compressed=compressed))


def quotable(cells: str, quote_text: str) -> bool:
    text = extract(cells)
    if text is None:
        return False
    reference = ReferenceContent(reference_id="file:fig.drawio", content=text, content_type="local_drawio")
    return SupportingTextValidator(ReferenceValidationConfig()).find_text_in_reference(quote_text, reference).found


# ---------------------------------------------------------------- routing


def test_registered_for_drawio_format():
    assert isinstance(ExtractorRegistry.get("drawio"), DrawioExtractor)


@pytest.mark.parametrize("name", ["fig.drawio", "fig.drawio.xml", "FIG.DRAWIO"])
def test_drawio_suffixes_resolve(name):
    assert resolve_format(None, name, None) == "drawio"


def test_plain_xml_suffix_is_still_xml():
    assert resolve_format(None, "article.xml", None) == "xml"


@pytest.mark.parametrize(
    "head",
    [b'<mxfile host="x"><diagram/></mxfile>', b'<?xml version="1.0"?>\n<mxfile><diagram/></mxfile>', b"<mxGraphModel/>"],
)
def test_drawio_is_sniffed(head):
    assert sniff_format(head) == "drawio"


# ---------------------------------------------------------------- labels and edges


def test_each_cell_label_is_its_own_label_then_edge_lines():
    assert extract(PTEN + AKT + EDGE) == "PTEN\n\nAKT\n\ninhibits\n\nPTEN inhibits AKT"


def test_compressed_diagrams_read_the_same():
    assert extract(PTEN + AKT + EDGE, compressed=True) == extract(PTEN + AKT + EDGE)


def test_every_page_is_read():
    assert extract(PTEN, AKT) == "PTEN\n\nAKT"


def test_a_quote_cannot_run_across_cells():
    cells = PTEN + AKT
    assert not quotable(cells, "PTEN AKT")


def test_html_label_lines_stay_one_label():
    cell = (
        '<mxCell id="n" value="&lt;b&gt;PTEN&lt;/b&gt;&lt;br&gt;tumour suppressor" '
        'style="html=1;" vertex="1" parent="1"/>'
    )
    assert extract(cell) == "PTEN\ntumour suppressor"
    assert quotable(cell, "PTEN tumour suppressor")


def test_plain_label_newlines_are_lines():
    cell = '<mxCell id="n" value="PTEN&#xa;tumour suppressor" vertex="1" parent="1"/>'
    assert extract(cell) == "PTEN\ntumour suppressor"


def test_edge_label_on_a_child_label_cell():
    edge = EDGE.replace('value="inhibits" ', 'value="" ')
    child = '<mxCell id="l1" value="inhibits" style="edgeLabel;html=1;" vertex="1" connectable="0" parent="e1"/>'
    assert quotable(PTEN + AKT + edge + child, "PTEN inhibits AKT")


def test_user_object_labels_and_ids():
    node = '<UserObject label="PTEN" tooltip="SECRET" id="pten"><mxCell vertex="1" parent="1"/></UserObject>'
    assert quotable(node + AKT + EDGE, "PTEN inhibits AKT")
    assert not quotable(node, "SECRET")


@pytest.mark.parametrize(
    "html",
    [
        "&lt;p&gt;PTEN&lt;o:p&gt;&lt;/o:p&gt;&lt;/p&gt;",  # Word's leftovers in pasted text
        "&lt;div foo:bar=&quot;1&quot;&gt;PTEN&lt;/div&gt;",
        "&lt;svg:text&gt;PTEN&lt;/svg:text&gt;",
    ],
)
def test_prefixed_html_from_pasted_text_is_read(html):
    cell = f'<mxCell id="n" value="{html}" style="html=1;" vertex="1" parent="1"/>'
    assert extract(cell) == "PTEN"


# ---------------------------------------------------------------- not drawn


@pytest.mark.parametrize(
    "cells",
    [
        '<mxCell id="s" value="SECRET" vertex="1" parent="1" visible="0"/>',
        '<mxCell id="L2" value="layer" parent="0" visible="0"/><mxCell id="s" value="SECRET" vertex="1" parent="L2"/>',
        '<mxCell id="g" value="" vertex="1" parent="1" collapsed="1"/><mxCell id="s" value="SECRET" vertex="1" parent="g"/>',
        '<mxCell id="s" value="SECRET" style="noLabel=1;" vertex="1" parent="1"/>',
        '<mxCell id="s" value="SECRET" style="textOpacity=0;" vertex="1" parent="1"/>',
        '<mxCell id="s" value="SECRET" style="opacity=0;" vertex="1" parent="1"/>',
        '<mxCell id="s" value="SECRET" style="fontColor=none;" vertex="1" parent="1"/>',
        '<mxCell id="s" value="SECRET" style="fontSize=0;" vertex="1" parent="1"/>',
        '<mxCell id="s" value="shown&lt;span style=&quot;display:none&quot;&gt;SECRET&lt;/span&gt;" style="html=1;" vertex="1" parent="1"/>',
        '<mxCell id="s" value="shown" style="SECRET" vertex="1" parent="1" tooltip="SECRET"/>',
        '<mxCell id="L2" value="SECRET" parent="0"/><mxCell id="s" value="shown" vertex="1" parent="L2"/>',
    ],
    ids=[
        "hidden-cell", "hidden-layer", "collapsed-group", "noLabel", "textOpacity", "opacity",
        "fontColor-none", "fontSize-0", "hidden-html", "style-and-attributes", "layer-name",
    ],
)
def test_what_is_not_drawn_is_not_quotable(cells):
    assert not quotable(cells + PTEN, "SECRET")


@pytest.mark.parametrize(
    "cells",
    [
        PTEN + AKT + EDGE.replace('style="endArrow=block;"', 'style="strokeColor=none;"'),
        PTEN + AKT + EDGE.replace('edge="1"', 'edge="1" visible="0"'),
        PTEN + AKT.replace('vertex="1"', 'vertex="1" visible="0"') + EDGE,
        PTEN + AKT + EDGE.replace('target="akt"', 'target="nowhere"'),
        PTEN + AKT + EDGE.replace(' source="pten"', ""),
        PTEN + AKT + EDGE.replace('value="inhibits"', 'value=""'),
    ],
    ids=["invisible-stroke", "hidden-edge", "hidden-target", "missing-target", "no-source", "no-label"],
)
def test_no_edge_line_without_a_drawn_edge_between_labelled_cells(cells):
    assert not quotable(cells, "PTEN inhibits AKT")


# ---------------------------------------------------------------- fail closed


@pytest.mark.parametrize(
    "cells",
    [
        '<UserObject label="%name% inhibits" placeholders="1" name="SECRET" id="u"><mxCell vertex="1" parent="1"/></UserObject>',
        '<mxCell id="s" value="&lt;script&gt;x()&lt;/script&gt;shown" style="html=1;" vertex="1" parent="1"/>',
    ],
    ids=["placeholders", "script"],
)
def test_labels_that_cannot_be_read_statically_fail_closed(cells):
    assert extract(cells + PTEN) is None


@pytest.mark.parametrize(
    "data",
    [
        b"<mxfile><diagram>not base64 !!</diagram></mxfile>",
        b"<mxfile><diagram>" + base64.b64encode(b"not deflated") + b"</diagram></mxfile>",
        b"<mxfile><diagram><unclosed></diagram></mxfile>",
        b"<html/>",
    ],
)
def test_unreadable_files_yield_none(data):
    assert DrawioExtractor().extract(data) is None


def test_a_decompression_bomb_fails_closed():
    deflater = zlib.compressobj(9, zlib.DEFLATED, -15)
    raw = deflater.compress(b"A" * (64 * 1024 * 1024)) + deflater.flush()
    data = b"<mxfile><diagram>" + base64.b64encode(raw) + b"</diagram></mxfile>"
    assert DrawioExtractor().extract(data) is None


# ---------------------------------------------------------------- file: and cache


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)


def test_file_source_reads_drawio(tmp_path, config):
    figure = tmp_path / "pathway.drawio"
    figure.write_bytes(drawio(PTEN + AKT + EDGE, compressed=True))
    ref = FileSource().fetch(str(figure), config)
    assert ref is not None
    assert ref.content_type == "local_drawio"
    assert ref.content == "PTEN\n\nAKT\n\ninhibits\n\nPTEN inhibits AKT"


def test_validator_matches_drawio_end_to_end(tmp_path, config):
    figure = tmp_path / "pathway.drawio"
    figure.write_bytes(drawio(PTEN + AKT + EDGE, compressed=True))
    validator = SupportingTextValidator(config)
    assert validator.validate("PTEN inhibits AKT", f"file:{figure}").is_valid
    assert not validator.validate("AKT inhibits PTEN", f"file:{figure}").is_valid


def test_drawio_entry_cached_as_raw_markup_is_stale():
    entry = "---\nreference_id: file:/x/fig.drawio\nextractor_version: 1\ncontent_type: local_file\n---\n\nraw"
    assert ReferenceFetcher._is_stale_cache_entry(entry)


def test_drawio_at_a_full_text_location_is_not_full_text(config):
    from unittest.mock import patch

    fetcher = ReferenceFetcher(config)
    data = drawio(PTEN + AKT + EDGE)
    location = FullTextLocation(url="https://oa.example/fig", provider="test")
    with patch.object(fetcher._acquirer, "fetch_bytes", return_value=(data, None)):
        assert fetcher._materialize(location)[0] is None
