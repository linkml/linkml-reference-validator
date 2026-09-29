"""A PDF fetched by URL should carry a real title where one can be found (issue #93).

Before this, ``URLSource`` set ``title=url`` on every PDF, so a consumer that
reads ``title`` as bibliographic metadata got the address back as the name.
The recovery order is: a publisher landing page found by a documented rule
(``citation_title``), then the PDF's embedded ``/Title``, then the URL.
"""

import io
from unittest.mock import patch

import pytest
import requests
from pypdf import PdfWriter

from linkml_reference_validator.etl.extract.pdf import PDFExtractor
from linkml_reference_validator.etl.sources.url import URLSource
from linkml_reference_validator.models import ReferenceValidationConfig

JSTAGE_PDF = "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_pdf/-char/ja"
JSTAGE_ARTICLE = "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_article/-char/ja"


def _pdf(title=None) -> bytes:
    """Build a blank one-page PDF, optionally with an embedded ``/Title``."""
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    if title is not None:
        writer.add_metadata({"/Title": title})
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)


def _fetch(url, responses, config):
    """Fetch ``url`` with the acquirer answering from ``responses``.

    Each value is ``(bytes, content_type)``, or an exception to raise, as
    ``requests`` does on a timeout or a refused connection.
    """

    def answer(u, _config):
        response = responses.get(u, (None, None))
        if isinstance(response, Exception):
            raise response
        return response

    with patch("linkml_reference_validator.etl.sources.url.ContentAcquirer") as MockAcquirer:
        MockAcquirer.return_value.fetch_bytes.side_effect = answer
        result = URLSource().fetch(url, config)
        requested = [c.args[0] for c in MockAcquirer.return_value.fetch_bytes.call_args_list]
    return result, requested


# --- embedded PDF metadata -------------------------------------------------


def test_extractor_reads_embedded_title():
    assert PDFExtractor().extract_title(_pdf("Canine Distemper in Dogs")) == (
        "Canine Distemper in Dogs"
    )


def test_extractor_title_absent_is_none():
    assert PDFExtractor().extract_title(_pdf()) is None


@pytest.mark.parametrize(
    "junk",
    ["", "   ", "untitled", "Untitled", "Microsoft Word - draft_v3.doc", "paper.pdf", "manuscript.docx"],
)
def test_extractor_ignores_placeholder_titles(junk):
    """Authoring tools stamp filenames and placeholders into /Title. Those are not titles."""
    assert PDFExtractor().extract_title(_pdf(junk)) is None


def _pdf_with_raw_title(raw: bytes) -> bytes:
    """Build a PDF whose /Title is the literal PDF object ``raw``.

    ``add_metadata`` turns every value into a string, so the object is written
    over a same-length placeholder in the file, which keeps the xref offsets.
    """
    placeholder = b"(" + b"X" * 20 + b")"
    data = _pdf("X" * 20)
    assert placeholder in data and len(raw) <= len(placeholder)
    return data.replace(placeholder, raw.ljust(len(placeholder)))


@pytest.mark.parametrize(
    "raw", [b"5", b"[(a)]", b"<< /A 1 >>"], ids=["number", "array", "dictionary"]
)
def test_extractor_ignores_a_title_that_is_not_text(raw):
    """pypdf returns /Title as whatever object it holds. A number is not a title."""
    assert PDFExtractor().extract_title(_pdf_with_raw_title(raw)) is None


def test_raw_title_helper_writes_a_readable_title():
    """The helper itself: a string written the same way is read back."""
    assert PDFExtractor().extract_title(_pdf_with_raw_title(b"(Real Title)")) == "Real Title"


def test_extractor_title_on_unparseable_bytes_is_none():
    assert PDFExtractor().extract_title(b"%PDF-1.4 not really a pdf") is None


def test_pdf_url_uses_embedded_title(config):
    url = "https://example.org/files/paper.pdf"
    result, _ = _fetch(url, {url: (_pdf("A Real Paper Title"), "application/pdf")}, config)
    assert result is not None
    assert result.title == "A Real Paper Title"


def test_pdf_url_without_any_title_falls_back_to_url(config):
    """With nothing to recover, the URL stays, so ``title == url`` still means 'none found'."""
    url = "https://example.org/files/paper.pdf"
    result, requested = _fetch(url, {url: (_pdf(), "application/pdf")}, config)
    assert result is not None
    assert result.title == url
    assert requested == [url], "no landing-page rule matches, so nothing else is fetched"


# --- landing page discovery ------------------------------------------------


@pytest.mark.parametrize(
    "pdf_url,landing",
    [
        (JSTAGE_PDF, JSTAGE_ARTICLE),
        (
            "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_pdf",
            "https://www.jstage.jst.go.jp/article/jvms/64/1/64_1_1/_article",
        ),
        ("https://example.org/files/paper.pdf", None),
    ],
)
def test_landing_page_rule(pdf_url, landing):
    assert URLSource._landing_page_url(pdf_url) == landing


def test_jstage_pdf_takes_citation_title_from_article_page(config):
    article = (
        b'<html><head><title>J-STAGE</title>'
        b'<meta name="citation_title" content="Feline Infectious Peritonitis &amp; Its Diagnosis">'
        b"</head><body></body></html>"
    )
    result, requested = _fetch(
        JSTAGE_PDF,
        {
            JSTAGE_PDF: (_pdf("Microsoft Word - 64_1_1.doc"), "application/pdf"),
            JSTAGE_ARTICLE: (article, "text/html; charset=utf-8"),
        },
        config,
    )
    assert result is not None
    assert result.title == "Feline Infectious Peritonitis & Its Diagnosis"
    assert result.content_type == "unavailable"  # blank page, no text: unchanged behavior
    assert requested == [JSTAGE_PDF, JSTAGE_ARTICLE]


def test_landing_page_title_beats_embedded_title(config):
    """The publisher's page is authoritative. Embedded /Title is often stale."""
    article = b'<meta content="The Published Title" name="citation_title">'
    result, _ = _fetch(
        JSTAGE_PDF,
        {
            JSTAGE_PDF: (_pdf("Submitted Draft Title"), "application/pdf"),
            JSTAGE_ARTICLE: (article, "text/html"),
        },
        config,
    )
    assert result.title == "The Published Title"


def test_landing_page_without_citation_title_falls_through_to_embedded(config):
    """A bare <title> on a landing page is often the site name, so it is not used."""
    article = b"<html><head><title>J-STAGE</title></head></html>"
    result, _ = _fetch(
        JSTAGE_PDF,
        {
            JSTAGE_PDF: (_pdf("Embedded Title"), "application/pdf"),
            JSTAGE_ARTICLE: (article, "text/html"),
        },
        config,
    )
    assert result.title == "Embedded Title"


@pytest.mark.parametrize(
    "error", [requests.Timeout("slow"), requests.ConnectionError("refused")]
)
def test_landing_page_error_keeps_the_pdf(config, error):
    """The title is best-effort. A failed landing page must not cost the PDF."""
    result, requested = _fetch(
        JSTAGE_PDF,
        {JSTAGE_PDF: (_pdf("Embedded Title"), "application/pdf"), JSTAGE_ARTICLE: error},
        config,
    )
    assert requested == [JSTAGE_PDF, JSTAGE_ARTICLE]
    assert result is not None
    assert result.full_text_url == JSTAGE_PDF
    assert result.title == "Embedded Title"


def test_landing_page_fetch_failure_falls_through_to_url(config):
    result, _ = _fetch(JSTAGE_PDF, {JSTAGE_PDF: (_pdf(), "application/pdf")}, config)
    assert result is not None
    assert result.title == JSTAGE_PDF


# --- citation_title on ordinary HTML fetches -------------------------------


def test_html_prefers_citation_title_over_title_tag(config):
    url = "https://example.org/article/1"
    page = (
        b"<html><head><title>Example Journal | Home</title>"
        b'<meta name="citation_title" content="Actual Article Title"></head></html>'
    )
    result, _ = _fetch(url, {url: (page, "text/html")}, config)
    assert result.title == "Actual Article Title"


@pytest.mark.parametrize(
    "page",
    [
        '<meta data-name="citation_title" content="Wrong"><meta name="citation_title" content="Right">',
        '<meta name="citation_title" data-content="Wrong" content="Right">',
        '<meta\nname="citation_title"\ncontent="Right">',
    ],
)
def test_citation_title_ignores_look_alike_attributes(page):
    """``data-name`` and ``data-content`` are other attributes, not ``name`` and ``content``."""
    assert URLSource._citation_title(page) == "Right"


@pytest.mark.parametrize(
    "title",
    ["Converting LaTeX Manuscripts to report.pdf", "Why we stopped using .docx"],
)
def test_extractor_keeps_a_real_title_that_ends_like_a_filename(title):
    """Only a bare filename is a placeholder. A sentence ending in one is a title."""
    assert PDFExtractor().extract_title(_pdf(title)) == title
