"""JATS table extraction and targeted cache migration regressions for #68."""

from pathlib import Path

import pytest

from linkml_reference_validator.etl.extract.xml import XMLExtractor
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceContent,
    ReferenceValidationConfig,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

FIXTURE = Path(__file__).parent / "fixtures/jats/PMC5593426.xml"


def test_real_clinical_rows():
    """The reported table-only findings are directly quotable from the real paper."""
    text = XMLExtractor().extract(FIXTURE.read_bytes())
    assert text is not None
    assert (
        "## Table 1 Summary clinical characteristics of patients with missense mutations in BACH2."
        in text
    )
    for row in [
        "On IvIg treatment | Yes | Yes | No",
        "IgM | Low | Low | High",
        "IgG | Low | Low | High*",
    ]:
        assert f"| {row} |" in text
        ref = ReferenceContent(reference_id="PMID:28530713", content=text)
        assert (
            SupportingTextValidator(ReferenceValidationConfig())
            .find_text_in_reference(row, ref)
            .found
        )


@pytest.mark.parametrize("placement", ["body", "floats-group"])
def test_structural_tables(placement):
    """Wrappers, blocks and inline tags retain boundaries without duplicate captions."""
    xml = f"""<article><abstract><p>Abstract stays separate.</p></abstract><{placement}>
    <table-wrap><label>Table 2</label><caption><p>Clinical <italic>features</italic>.</p></caption>
    <alternatives><table><tbody><tr><th>Patient</th><th>A</th><th>B</th></tr>
    <tr><td><p>CD<sup>4</sup><sup>+</sup> cells</p><p>Ig<italic>G</italic></p></td>
    <td>Yes<break/>again</td><td>A | B</td></tr></tbody></table></alternatives>
    </table-wrap></{placement}></article>"""
    text = XMLExtractor().extract(xml)
    assert (
        text
        == "## Table 2 Clinical features.\n\n| Patient | A | B |\n| CD4+ cells IgG | Yes again | A \\| B |"
    )


def test_nested_tables_and_wraps_once():
    """Each actual table owns its rows; descendants never leak into ancestor cells."""
    xml = """<article><body><p>Body.</p><table-wrap><label>Outer</label><table>
    <tr><td>Outer cell<table-wrap><label>Inner</label><table><tr><td>Inner cell</td></tr></table>
    </table-wrap></td></tr></table></table-wrap></body></article>"""
    text = XMLExtractor().extract(xml)
    assert text == "Body.\n\n## Outer\n\n| Outer cell |\n\n## Inner\n\n| Inner cell |"


def test_spans_are_explicit_source_cells():
    """Spanned cells are annotated, never propagated into invented patient values."""
    xml = """<article><table-wrap><table><tr><td rowspan="2">Group</td><td colspan="2">Shared</td></tr>
    <tr><td>A</td><td>B</td></tr></table></table-wrap></article>"""
    assert (
        XMLExtractor().extract(xml)
        == "## Table\n\n| Group [rowspan=2] | Shared [colspan=2] |\n| A | B |"
    )


@pytest.mark.parametrize("count", [200, 201])
def test_row_cap(count):
    """Only the first 200 source rows survive, with an explicit truncation notice."""
    rows = "".join(f"<tr><td><p>Row {i}</p></td></tr>" for i in range(count))
    text = XMLExtractor().extract(
        f"<article><body><table-wrap><table>{rows}</table></table-wrap></body></article>"
    )
    assert text.count("\n| Row ") == 200
    assert "| Row 199 |" in text
    assert "Row 200" not in text
    assert ("[Table truncated after 200 rows.]" in text) == (count > 200)


def test_stub_is_checked_before_tables():
    """Table size cannot disguise a restricted body notice."""
    xml = "<article><body><p>Text cannot be obtained from PMC.</p></body><table-wrap><table>"
    xml += "<tr><td>Data</td></tr>" * 200 + "</table></table-wrap></article>"
    assert XMLExtractor().extract(xml) is None


def make_fetcher(tmp_path):
    """Use a fresh in-memory cache on each call."""
    return ReferenceFetcher(
        ReferenceValidationConfig(cache_dir=tmp_path, rate_limit_delay=0)
    )


@pytest.mark.parametrize("version", [None, 0, 1, 99])
def test_xml_version_roundtrip(tmp_path, version):
    """Metadata-only rewrites neither certify old XML nor downgrade future stamps."""
    fetcher = make_fetcher(tmp_path)
    path = fetcher.get_cache_path("unknown:xml")
    stamp = "" if version is None else f"xml_extraction_version: {version}\n"
    path.write_text(
        "---\nreference_id: unknown:xml\nextractor_version: 1\ncontent_type: full_text_xml\n"
        + stamp
        + "---\nOld body"
    )
    ref = fetcher._load_from_disk("unknown:xml", allow_stale=True)
    fetcher._save_to_disk(ref)
    assert ReferenceFetcher._is_stale_cache_entry(path.read_text()) == (
        version in (None, 0)
    )
    assert ref.metadata.get("xml_extraction_version") == version
    if version is None:
        assert "xml_extraction_version" not in path.read_text()


def test_xml_offline_stays_stale(tmp_path, caplog):
    """Useful old XML remains available offline without falsely certifying its text."""
    fetcher = make_fetcher(tmp_path)
    path = fetcher.get_cache_path("unknown:xml")
    old = "---\nreference_id: unknown:xml\nextractor_version: 1\ncontent_type: full_text_xml\n---\nOld body"
    path.write_text(old)
    assert fetcher.fetch("unknown:xml").content == "Old body"
    assert path.read_text() == old
    assert "older extractor" in caplog.text
    assert fetcher._load_from_disk("unknown:xml") is None


def test_provider_xml_stamp_and_abstract(tmp_path):
    """Fresh extracted provider XML certifies its version and keeps the abstract."""
    fetcher = make_fetcher(tmp_path)
    ref = ReferenceContent(
        reference_id="unknown:xml",
        content="Original abstract",
        content_type="abstract_only",
    )
    text = XMLExtractor().extract(FIXTURE.read_bytes())
    assert fetcher.apply_full_text_location(
        ref, FullTextLocation(text=text, format_hint="xml"), "pmc"
    )
    assert ref.content.startswith("Original abstract\n\n")
    assert ref.metadata["xml_extraction_version"] == 1
    assert make_fetcher(tmp_path)._load_from_disk(ref.reference_id) is not None


def test_warm_legacy_xml_refreshes_from_real_source(tmp_path, monkeypatch):
    """A registered fixture-backed source replaces legacy text once, then stays warm."""
    from linkml_reference_validator.etl.sources.base import (
        ReferenceSource,
        ReferenceSourceRegistry,
    )

    reads = []

    class FixtureXMLSource(ReferenceSource):
        """Read and extract the actual PMC response using the source contract."""

        @classmethod
        def prefix(cls):
            """Use an isolated reference namespace."""
            return "JATSFIXTURE"

        def fetch(self, identifier, config):
            """Perform real extraction, tracking disk acquisitions."""
            reads.append(identifier)
            return ReferenceContent(
                reference_id=f"JATSFIXTURE:{identifier}",
                content=XMLExtractor().extract(FIXTURE.read_bytes()),
                content_type="full_text_xml",
            )

    monkeypatch.setattr(ReferenceSourceRegistry, "_sources", [FixtureXMLSource])
    fetcher = make_fetcher(tmp_path)
    path = fetcher.get_cache_path("JATSFIXTURE:28530713")
    path.write_text(
        "---\nreference_id: JATSFIXTURE:28530713\nextractor_version: 1\ncontent_type: full_text_xml\n---\nLegacy prose only"
    )
    fresh = fetcher.fetch("JATSFIXTURE:28530713")
    assert "| On IvIg treatment | Yes | Yes | No |" in fresh.content
    assert fresh.metadata["xml_extraction_version"] == 1
    assert "xml_extraction_version: 1" in path.read_text()
    assert make_fetcher(tmp_path).fetch("JATSFIXTURE:28530713").content == fresh.content
    assert reads == ["28530713"]


@pytest.mark.parametrize(
    "kind,stamp",
    [("full_text_pdf", ""), ("full_text_html", "html_full_text_version: 1\n")],
)
def test_xml_migration_does_not_refresh_other_formats(tmp_path, kind, stamp):
    """Current HTML and PDF caches remain usable without an XML version."""
    fetcher = make_fetcher(tmp_path)
    path = fetcher.get_cache_path("unknown:other")
    path.write_text(
        f"---\nreference_id: unknown:other\nextractor_version: 1\ncontent_type: {kind}\n{stamp}---\nCurrent body"
    )
    assert fetcher._load_from_disk("unknown:other").content == "Current body"


def test_downloaded_xml_provider_uses_tables(tmp_path):
    """Actual HTTP acquisition extracts the PMC fixture and stamps its cache."""
    from functools import partial
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    server = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        partial(SimpleHTTPRequestHandler, directory=str(FIXTURE.parent)),
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        ref = ReferenceContent(
            reference_id="unknown:download",
            content_type="abstract_only",
            content="Abstract",
        )
        fetcher = make_fetcher(tmp_path)
        assert fetcher.apply_full_text_location(
            ref,
            FullTextLocation(
                url=f"http://127.0.0.1:{server.server_port}/{FIXTURE.name}",
                format_hint="xml",
            ),
            "local-test",
        )
        assert ref.content.startswith("Abstract\n\n")
        assert "| On IvIg treatment | Yes | Yes | No |" in ref.content
        assert ref.metadata["xml_extraction_version"] == 1
        assert not fetcher._is_stale_cache_entry(
            fetcher.get_cache_path(ref.reference_id).read_text()
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_hidden_xml_nodes_are_not_quotable():
    """Comments and processing instructions are metadata, while CDATA is content."""
    xml = """<article><table-wrap><caption><p>Clinical<!-- hidden caption --></p></caption>
    <table><tr><td>Yes<!-- secret --><?review hidden?> again</td>
    <td><![CDATA[Useful text]]></td><td/></tr></table></table-wrap></article>"""
    assert (
        XMLExtractor().extract(xml) == "## Clinical\n\n| Yes again | Useful text |  |"
    )


@pytest.mark.parametrize("placement", ["body", "floats-group"])
def test_table_footnotes_preserved_once(placement):
    """Footnotes defining table markers remain quotable, including floats-group notes."""
    xml = f"""<article><{placement}><table-wrap><label>Table 1</label>
    <table><tr><td>IgG</td><td>High<sup>*</sup></td></tr></table>
    <table-wrap-foot><fn><p>* Measured before <italic>treatment</italic>.</p></fn>
    <fn><p>IvIg, intravenous immunoglobulin.</p></fn></table-wrap-foot>
    </table-wrap></{placement}></article>"""
    assert XMLExtractor().extract(xml) == (
        "## Table 1\n\n| IgG | High* |\n\n"
        "* Measured before treatment. IvIg, intravenous immunoglobulin."
    )


def test_nested_wrapper_footnotes_are_not_duplicated():
    """Inner and outer notes are rendered once, under their own wrappers."""
    xml = """<article><body><table-wrap><table><tr><td>Outer</td></tr></table>
    <table-wrap><table><tr><td>Inner</td></tr></table><table-wrap-foot><p>Inner note.</p></table-wrap-foot></table-wrap>
    <table-wrap-foot><p>Outer note.</p></table-wrap-foot></table-wrap></body></article>"""
    text = XMLExtractor().extract(xml)
    assert text.count("Inner note.") == 1
    assert text.count("Outer note.") == 1


@pytest.mark.parametrize("tag", ["sub-article", "response"])
def test_other_article_tables_are_not_attributed_to_main_paper(tag):
    """Review/reply tables cannot become evidence attributed to the main article."""
    xml = f"""<article><body><p>Main prose.</p></body>
    <floats-group><table-wrap><table><tr><td>Main finding</td></tr></table></table-wrap></floats-group>
    <{tag}><body><p>Reviewer prose.</p></body><table-wrap><table><tr><td>Reviewer finding</td></tr></table>
    <table-wrap-foot><p>Reviewer note.</p></table-wrap-foot></table-wrap></{tag}></article>"""
    text = XMLExtractor().extract(xml)
    assert text == "Main prose.\n\n## Table\n\n| Main finding |"


def test_nested_table_without_own_wrapper_has_own_heading():
    """A nested physical table must not repeat the outer table's label/caption."""
    xml = """<article><table-wrap><label>Table 1</label><caption><p>Main caption</p></caption>
    <table><tr><td>Outer<table><tr><td>Nested</td></tr></table></td></tr></table></table-wrap></article>"""
    assert (
        XMLExtractor().extract(xml)
        == "## Table 1 Main caption\n\n| Outer |\n\n## Nested table\n\n| Nested |"
    )
