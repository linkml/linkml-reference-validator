"""Real HTML fixtures and HTTP acquisition regressions for issue #65."""

from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from bs4 import BeautifulSoup

from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceContent,
    ReferenceValidationConfig,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fulltext_html"


@pytest.fixture
def html_server(tmp_path):
    """Serve downloaded fixtures and provider responses over actual loopback HTTP."""
    for path in FIXTURES.glob("*.html"):
        (tmp_path / path.name).write_bytes(path.read_bytes())
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    )
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()
    thread.join()


def make_fetcher(tmp_path, **kwargs):
    """Create an isolated, delay-free fetcher."""
    return ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=tmp_path / "cache", rate_limit_delay=0, **kwargs
        )
    )


@pytest.mark.parametrize("hint", ["html", "pdf"])
@pytest.mark.parametrize(
    "abstract", [None, "An abstract already held by the metadata source."]
)
def test_dspace_landing_is_not_full_text(tmp_path, html_server, hint, abstract):
    """Real PMID:32894695 DSpace markup must fail regardless of hint or abstract."""
    data = (FIXTURES / "dspace-32894695.html").read_bytes()
    text = HTMLExtractor().extract(data)
    assert text and len(text) > 3000  # Long, novel metadata/chrome is insufficient.
    ref = ReferenceContent(
        reference_id="PMID:32894695", content=abstract, content_type="abstract_only"
    )
    fetcher = make_fetcher(tmp_path)
    assert not fetcher.apply_full_text_location(
        ref,
        FullTextLocation(url=f"{html_server}/dspace-32894695.html", format_hint=hint),
        "openalex",
    )
    assert ref.content == abstract
    assert ref.content_type == "abstract_only"
    assert ref.full_text_provider is None


def test_real_plos_article_is_accepted(tmp_path, html_server):
    """A genuine publisher article retains its research body and inline spacing."""
    ref = ReferenceContent(
        reference_id="DOI:10.1371/journal.pone.0000308",
        content="Abstract",
        content_type="abstract_only",
    )
    fetcher = make_fetcher(tmp_path)
    assert fetcher.apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/plos-0000308.html"), "openalex"
    )
    assert ref.content_type == "full_text_html"
    assert (
        "We studied the citations of 85 cancer microarray clinical trials"
        in ref.content
    )
    assert ref.full_text_provider == "openalex"


def test_abstract_only_article_container_is_rejected(tmp_path, html_server):
    """Semantic article tags and structured abstract headings do not prove a body."""
    s = BeautifulSoup((FIXTURES / "plos-0000308.html").read_text(), "html.parser")
    abstract = s.select_one(".abstract")
    assert abstract is not None
    (tmp_path / "abstract.html").write_text(
        f"<html><body><article>{abstract}</article></body></html>"
    )
    fetcher = make_fetcher(tmp_path)
    ref = ReferenceContent(
        reference_id="DOI:10.1/abstract", content_type="abstract_only"
    )
    assert not fetcher.apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/abstract.html"), "unpaywall"
    )


def test_short_real_article_body_is_accepted(tmp_path, html_server):
    """A short real Results section can prove full-text content without a size heuristic."""
    s = BeautifulSoup((FIXTURES / "plos-0000308.html").read_text(), "html.parser")
    section = s.find("h2", string="Results").parent
    assert section is not None
    # Keep the actual section structure and first two substantive paragraphs.
    for p in section.find_all("p")[2:]:
        p.decompose()
    (tmp_path / "short.html").write_text(
        f"<html><body><article>{section}</article></body></html>"
    )
    text = HTMLExtractor().extract(str(section))
    assert text and 500 < len(text) < 2000
    ref = ReferenceContent(reference_id="DOI:10.1/short", content_type="abstract_only")
    assert make_fetcher(tmp_path).apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/short.html"), "unpaywall"
    )


def test_rejected_landing_continues_provider_chain(tmp_path, html_server):
    """Configured real HTTP providers advance from landing page to genuine article."""
    import json

    for name, target in [
        ("landing", "dspace-32894695.html"),
        ("article", "plos-0000308.html"),
    ]:
        (tmp_path / f"{name}.json").write_text(
            json.dumps({"url": f"{html_server}/{target}"})
        )
    providers = tmp_path / "providers.yaml"
    providers.write_text(
        "full_text_providers:\n"
        + "".join(
            f"  issue65_{name}:\n    url_template: {html_server}/{name}.json\n    location_field: $.url\n"
            for name in ["landing", "article"]
        )
    )
    fetcher = make_fetcher(
        tmp_path,
        full_text_providers=["issue65_landing", "issue65_article"],
        full_text_providers_file=providers,
    )
    ref = ReferenceContent(
        reference_id="PMID:32894695",
        content="Original abstract",
        content_type="abstract_only",
    )
    result = fetcher._enrich_with_full_text(ref)
    assert result.full_text_provider == "issue65_article"
    assert result.full_text_attempted
    assert "Show full item record" not in result.content
    assert (
        "We studied the citations of 85 cancer microarray clinical trials"
        in result.content
    )


def test_old_html_cache_is_not_used_even_offline_and_can_recover(tmp_path, html_server):
    """Version-one HTML cannot validate chrome while offline; a fresh body repairs it."""
    fetcher = make_fetcher(tmp_path)
    ref = ReferenceContent(
        reference_id="unknown:65",
        content="Show full item record",
        content_type="full_text_html",
    )
    path = fetcher.get_cache_path(ref.reference_id)
    old = "---\nreference_id: unknown:65\nextractor_version: 1\ncontent_type: full_text_html\n---\nShow full item record"
    path.write_text(old)
    assert fetcher.fetch(ref.reference_id) is None
    assert path.read_text() == old
    assert fetcher.apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/plos-0000308.html"), "openalex"
    )
    assert (
        make_fetcher(tmp_path)._load_from_disk(ref.reference_id).content_type
        == "full_text_html"
    )


def test_flat_article_headings_preserve_body_without_chrome(tmp_path, html_server):
    """Flatten real PLOS section wrappers to the common heading/sibling layout."""
    s = BeautifulSoup((FIXTURES / "plos-0000308.html").read_text(), "html.parser")
    body = s.select_one("#artText")
    body.name = "article"
    body.attrs = {}
    for section in list(body.select(".section")):
        section.unwrap()
    (tmp_path / "flat.html").write_text(
        f"<html><body>{body}<footer><p>Repository rights reserved</p></footer></body></html>"
    )
    ref = ReferenceContent(reference_id="DOI:10.1/flat", content_type="abstract_only")
    assert make_fetcher(tmp_path).apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/flat.html"), "openalex"
    )
    assert (
        "We studied the citations of 85 cancer microarray clinical trials"
        in ref.content
    )
    assert "Repository rights reserved" not in ref.content
    assert "Sharing research data provides benefit" not in ref.content


def test_current_pdf_cache_does_not_need_html_migration(tmp_path):
    """The landing-page fix does not invalidate already current PDF/XML caches."""
    fetcher = make_fetcher(tmp_path)
    path = fetcher.get_cache_path("unknown:pdf")
    path.write_text(
        "---\nreference_id: unknown:pdf\nextractor_version: 1\ncontent_type: full_text_pdf\n---\nReal PDF text"
    )
    assert fetcher._load_from_disk("unknown:pdf") is not None


def test_iris_landing_is_not_full_text(tmp_path, html_server):
    """Real IRIS item metadata, abstract and delete dialog are not an article."""
    data = (FIXTURES / "iris-19049553.html").read_bytes()
    assert len(HTMLExtractor().extract(data)) > 500
    ref = ReferenceContent(reference_id="PMID:19049553", content_type="abstract_only")
    assert not make_fetcher(tmp_path).apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/iris-19049553.html"), "openalex"
    )


@pytest.mark.parametrize(
    "content_type", ["full_text_pdf", "full_text_xml", "abstract_only"]
)
def test_unaffected_stale_cache_still_works_offline(tmp_path, content_type):
    """HTML migration leaves the pre-existing stale fallback for other types intact."""
    fetcher = make_fetcher(tmp_path)
    path = fetcher.get_cache_path("unknown:offline")
    path.write_text(
        f"---\nreference_id: unknown:offline\ncontent_type: {content_type}\n---\nUseful old content"
    )
    ref = fetcher.fetch("unknown:offline")
    assert ref.content == "Useful old content"
    assert ref.content_type == content_type


def test_abstract_text_alone_is_not_novel_full_text(tmp_path):
    """A provider's extracted HTML text equal to the abstract cannot enrich it."""
    abstract = "A previously fetched scientific abstract. " * 30
    ref = ReferenceContent(
        reference_id="PMID:65", content=abstract, content_type="abstract_only"
    )
    assert not make_fetcher(tmp_path).apply_full_text_location(
        ref, FullTextLocation(text=abstract, format_hint="html"), "custom"
    )
    assert ref.content == abstract


@pytest.mark.parametrize("stamp", [None, 5])
def test_metadata_rewrite_preserves_html_acceptance_provenance(tmp_path, stamp):
    """Inventory edits cannot certify old HTML or downgrade a future acceptance stamp."""
    fetcher = make_fetcher(tmp_path)
    path = fetcher.get_cache_path("unknown:inventory")
    stamp_line = "" if stamp is None else f"html_full_text_version: {stamp}\n"
    path.write_text(
        f"---\nreference_id: unknown:inventory\nextractor_version: 1\ncontent_type: full_text_html\n{stamp_line}---\nOld content"
    )
    ref = next(fetcher.iter_cached_references())
    ref.title = "Metadata edited"
    fetcher._save_to_disk(ref)
    if stamp is None:
        assert "html_full_text_version:" not in path.read_text()
        assert fetcher._load_from_disk(ref.reference_id) is None
    else:
        assert stamp_line in path.read_text()
        assert fetcher._load_from_disk(ref.reference_id) is not None


def test_old_html_is_not_served_after_http_failure(tmp_path, html_server):
    """A real 404 during refresh cannot resurrect an unverified HTML cache."""
    fetcher = make_fetcher(tmp_path)
    reference_id = f"url:{html_server}/missing.html"
    path = fetcher.get_cache_path(reference_id)
    old = f"---\nreference_id: {reference_id}\nextractor_version: 1\ncontent_type: full_text_html\n---\nRepository metadata"
    path.write_text(old)
    assert fetcher.fetch(reference_id) is None
    assert path.read_text() == old


def test_exhausted_landing_provider_keeps_original_abstract(tmp_path, html_server):
    """A cleanly rejected landing page records an attempt without changing evidence."""
    import json

    (tmp_path / "landing-only.json").write_text(
        json.dumps({"url": f"{html_server}/dspace-32894695.html"})
    )
    providers = tmp_path / "landing-only.yaml"
    providers.write_text(
        "full_text_providers:\n  issue65_only:\n"
        f"    url_template: {html_server}/landing-only.json\n"
        "    location_field: $.url\n"
    )
    fetcher = make_fetcher(
        tmp_path,
        full_text_providers=["issue65_only"],
        full_text_providers_file=providers,
    )
    ref = ReferenceContent(
        reference_id="PMID:32894695",
        content="Original abstract",
        content_type="abstract_only",
    )
    result = fetcher._enrich_with_full_text(ref)
    assert result.content == "Original abstract"
    assert result.content_type == "abstract_only"
    assert result.full_text_attempted
    assert result.full_text_provider is None


def test_generic_body_id_does_not_establish_full_text(tmp_path, html_server):
    """A generic layout ID and long metadata paragraphs are insufficient evidence."""
    from html import escape

    metadata = HTMLExtractor().extract((FIXTURES / "dspace-32894695.html").read_bytes())
    assert metadata and len(metadata) > 3000
    (tmp_path / "generic-body.html").write_text(
        '<html><body><div id="body">'
        f"<p>{escape(metadata[:1500])}</p><p>{escape(metadata[1500:])}</p>"
        "</div></body></html>"
    )
    ref = ReferenceContent(reference_id="PMID:32894695", content_type="abstract_only")
    assert not make_fetcher(tmp_path).apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/generic-body.html"), "openalex"
    )


def test_accepted_article_preserves_unfamiliar_sections(tmp_path, html_server):
    """Research headings establish the body without filtering its other sections."""
    s = BeautifulSoup((FIXTURES / "plos-0000308.html").read_text(), "html.parser")
    body = s.select_one("#artText")
    body.name = "article"
    body.attrs = {}
    body.find("h2", string="Introduction").string = "Main"
    body.find("h2", string="Results").string = "Case presentation"
    body.find("h2", string="Discussion").string = "Limitations"
    for section in list(body.select(".section")):
        section.unwrap()
    (tmp_path / "unfamiliar.html").write_text(f"<html><body>{body}</body></html>")
    ref = ReferenceContent(
        reference_id="DOI:10.1/unfamiliar", content_type="abstract_only"
    )
    assert make_fetcher(tmp_path).apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/unfamiliar.html"), "openalex"
    )
    assert (
        "We studied the citations of 85 cancer microarray clinical trials"
        in ref.content
    )
    assert "To confirm that these findings" in ref.content


def test_abstract_heading_cannot_remove_identifiable_body(tmp_path, html_server):
    """A higher-rank abstract heading must stop at a separately marked article body."""
    s = BeautifulSoup((FIXTURES / "plos-0000308.html").read_text(), "html.parser")
    body = s.select_one("#artText")
    body.select_one(".abstract").decompose()
    body.attrs = {"class": ["article-body"]}
    for heading in body.find_all("h2"):
        heading.name = "h3"
    (tmp_path / "ranked.html").write_text(
        f"<html><body><article><h2>Abstract</h2><p>Abstract only.</p>{body}</article></body></html>"
    )
    ref = ReferenceContent(reference_id="DOI:10.1/ranked", content_type="abstract_only")
    assert make_fetcher(tmp_path).apply_full_text_location(
        ref, FullTextLocation(url=f"{html_server}/ranked.html"), "openalex"
    )
    assert (
        "We studied the citations of 85 cancer microarray clinical trials"
        in ref.content
    )
    assert "Abstract only." not in ref.content


def test_raw_inline_html_is_not_trusted_as_preextracted_text(tmp_path):
    """HTML markup in a provider text field must pass the same body classifier."""
    ref = ReferenceContent(reference_id="PMID:32894695", content_type="abstract_only")
    assert not make_fetcher(tmp_path).apply_full_text_location(
        ref,
        FullTextLocation(
            text=(FIXTURES / "dspace-32894695.html").read_text(), format_hint="html"
        ),
        "custom",
    )


def test_preextracted_html_body_is_a_trusted_provider_contract(tmp_path):
    """PMC and configured text providers can supply an already-extracted body."""
    text = HTMLExtractor().extract_full_text(
        (FIXTURES / "plos-0000308.html").read_bytes()
    )
    assert text is not None
    ref = ReferenceContent(
        reference_id="DOI:10.1/extracted", content_type="abstract_only"
    )
    assert make_fetcher(tmp_path).apply_full_text_location(
        ref, FullTextLocation(text=text, format_hint="html"), "custom"
    )
    assert ref.content == text
    assert ref.metadata["html_full_text_version"] == 1
