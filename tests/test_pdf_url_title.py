"""A PDF fetched by URL should carry a real title where one can be found (issue #93).

Before this, ``URLSource`` set ``title=url`` on every PDF, so a consumer that
reads ``title`` as bibliographic metadata got the address back as the name.
The recovery order is: a publisher landing page found by a documented rule
(``citation_title``), then the PDF's embedded ``/Title``, then the URL.
"""

import io
from unittest.mock import patch

import pytest
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
    """Fetch ``url`` with the acquirer answering from ``responses`` (url -> (bytes, ctype))."""
    with patch("linkml_reference_validator.etl.sources.url.ContentAcquirer") as MockAcquirer:
        MockAcquirer.return_value.fetch_bytes.side_effect = (
            lambda u, _config: responses.get(u, (None, None))
        )
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


def test_extractor_title_on_unparseable_bytes_is_none():
    assert PDFExtractor().extract_title(b"%PDF-1.4 not really a pdf") is None
