"""Sources degrade, not raise, when the network or the data is bad (#134, #122).

``ReferenceFetcher`` falls back to a stale cache entry only when a source returns
None. Two kinds of source did not get that far:

- ``DOISource`` (Crossref, DataCite, Zenodo) and ``JSONAPISource`` let a network
  error or a non-JSON HTTP 200 raise, so one unreachable DOI aborted the run
  and the cached copy was never served (#134).
- A truncated or corrupt PDF behind a ``url:`` reference raised a pypdf error
  out of ``URLSource.fetch`` instead of giving ``content_type="unavailable"``
  (#122).

Only the network is simulated: ``requests.get`` raising, or answering with a
real ``requests.Response`` whose body is not JSON.
"""

import logging
from unittest.mock import patch

import pytest
import requests

from linkml_reference_validator.etl.extract.pdf import PDFExtractor
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.etl.sources.doi import DOISource
from linkml_reference_validator.etl.sources.json_api import JSONAPISource
from linkml_reference_validator.etl.sources.url import URLSource
from linkml_reference_validator.models import (
    JSONAPISourceConfig,
    ReferenceValidationConfig,
)

DOI = "10.1234/abc"
GET = "requests.get"


def _response(status: int, body: bytes, content_type: str = "text/html") -> requests.Response:
    """A real response object, so ``.json()`` behaves exactly as in production."""
    response = requests.Response()
    response.status_code = status
    response._content = body
    response.headers["Content-Type"] = content_type
    response.encoding = "utf-8"
    return response


MAINTENANCE_PAGE = _response(200, b"<html><body>Down for maintenance</body></html>")


def _offline(*args, **kwargs):
    raise requests.ConnectionError("offline")


def _timeout(*args, **kwargs):
    raise requests.Timeout("timed out")


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(cache_dir=tmp_path, rate_limit_delay=0)


@pytest.mark.parametrize(
    "get",
    [_offline, _timeout, lambda *a, **k: MAINTENANCE_PAGE],
    ids=["connection_error", "timeout", "non_json_200"],
)
def test_doi_source_returns_none_instead_of_raising(config, get, caplog):
    """Crossref and DataCite both fail, so the DOI is a miss, with a warning."""
    with patch(GET, side_effect=get), caplog.at_level(logging.WARNING):
        assert DOISource().fetch(DOI, config) is None
    assert DOI in caplog.text


def test_a_crossref_failure_still_tries_datacite(config):
    """A Crossref outage alone does not lose a DOI that DataCite knows."""
    datacite = _response(
        200,
        b'{"data": {"attributes": {"titles": [{"title": "From DataCite"}],'
        b' "descriptions": [{"description": "An abstract.", "descriptionType": "Abstract"}]}}}',
        "application/json",
    )

    def get(url, *args, **kwargs):
        if "crossref" in url:
            raise requests.ConnectionError("crossref down")
        return datacite

    with patch(GET, side_effect=get):
        reference = DOISource().fetch(DOI, config)
    assert reference is not None
    assert reference.title == "From DataCite"


@pytest.mark.parametrize(
    "get", [_offline, lambda *a, **k: MAINTENANCE_PAGE], ids=["connection_error", "non_json_200"]
)
def test_a_zenodo_files_failure_keeps_the_doi_metadata(config, get):
    """The Zenodo file list is enrichment: losing it must not lose the record."""
    with patch(GET, side_effect=get):
        assert DOISource()._fetch_zenodo_files("123", config) is None


@pytest.mark.parametrize(
    "get",
    [_offline, _timeout, lambda *a, **k: MAINTENANCE_PAGE],
    ids=["connection_error", "timeout", "non_json_200"],
)
def test_json_api_source_returns_none_instead_of_raising(config, get, caplog):
    source = JSONAPISource(
        JSONAPISourceConfig(
            prefix="TESTAPI", url_template="https://api.example.org/{id}",
            fields={"title": "$.name"},
        )
    )
    with patch(GET, side_effect=get), caplog.at_level(logging.WARNING):
        assert source.fetch("42", config) is None
    assert "TESTAPI:42" in caplog.text


@pytest.mark.parametrize(
    "get", [_offline, lambda *a, **k: MAINTENANCE_PAGE], ids=["connection_error", "non_json_200"]
)
def test_an_unreachable_doi_serves_the_stale_cache_entry(config, get):
    """The documented offline safety net now covers DOIs."""
    fetcher = ReferenceFetcher(config)
    path = fetcher.get_cache_path(f"DOI:{DOI}")
    stale = (
        f"---\nreference_id: DOI:{DOI}\ntitle: Cached paper\n"
        "content_type: abstract_only\n---\n\n## Content\n\nCached abstract.\n"
    )
    path.write_text(stale, encoding="utf-8")

    with patch(GET, side_effect=get):
        outcome = fetcher.fetch_with_provenance(f"DOI:{DOI}")

    assert outcome.content is not None
    assert outcome.content.content == "Cached abstract."
    assert outcome.served_stale is True
    assert path.read_text(encoding="utf-8") == stale


TRUNCATED_PDF = b"%PDF-1.7\n truncated download"


@pytest.mark.parametrize("data", [TRUNCATED_PDF, b""], ids=["truncated", "empty"])
def test_pdf_extractor_returns_none_for_a_damaged_pdf(data, caplog):
    with caplog.at_level(logging.WARNING):
        assert PDFExtractor().extract(data, source="https://x.example/a.pdf") is None
    assert "https://x.example/a.pdf" in caplog.text


def test_a_truncated_pdf_behind_a_url_is_unavailable(config):
    """The fetch succeeds as a record with no text, not an exception."""
    url = "https://x.example/a.pdf"
    with patch(
        "linkml_reference_validator.etl.sources.url.ContentAcquirer.fetch_bytes",
        return_value=(TRUNCATED_PDF, "application/pdf"),
    ):
        reference = URLSource().fetch(url, config)
    assert reference is not None
    assert reference.content_type == "unavailable"
    assert reference.content is None
    assert reference.title == url


def _minimal_pdf(text: str) -> bytes:
    """A one-page PDF with an uncompressed text stream, built by hand."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R"
        b" /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1, xref,
    )
    return bytes(out)


def test_the_minimal_pdf_reads():
    """The corpus below starts from a PDF whose text really extracts."""
    assert PDFExtractor().extract(_minimal_pdf("Hello evidence")) == "Hello evidence"


def test_damaged_pdfs_never_raise():
    """Truncations and seeded byte flips of a real PDF give text or None.

    pypdf raises more than ``PyPdfError`` on such input: this corpus includes
    cases raising ``AttributeError``, ``KeyError``, ``ValueError``,
    ``TypeError`` and ``IndexError``.
    """
    import random

    data = _minimal_pdf("Hello evidence")
    rng = random.Random(0)
    corpus = [data[:n] for n in range(len(data))]
    for _ in range(300):
        mutated = bytearray(data)
        for _ in range(rng.randint(1, 8)):
            mutated[rng.randrange(len(mutated))] = rng.randrange(256)
        corpus.append(bytes(mutated))

    extractor = PDFExtractor()
    logging.disable(logging.CRITICAL)
    try:
        for case in corpus:
            text = extractor.extract(case)
            assert text is None or isinstance(text, str)
            title = extractor.extract_title(case)
            assert title is None or isinstance(title, str)
    finally:
        logging.disable(logging.NOTSET)


def test_an_unreadable_full_text_pdf_is_still_a_transient_error(config):
    """In the full-text chain a truncated PDF stays retryable.

    ``_materialize`` flags it as an error, so ``full_text_attempted`` is not
    set and a later run tries the download again. Only ``URLSource`` maps an
    unreadable PDF to "unavailable".
    """
    from linkml_reference_validator.models import FullTextLocation

    fetcher = ReferenceFetcher(config)
    with patch.object(
        fetcher._acquirer, "fetch_bytes", return_value=(TRUNCATED_PDF, "application/pdf")
    ):
        text, fmt, pdf_bytes, error = fetcher._materialize(
            FullTextLocation(url="https://x.example/a.pdf", format_hint="pdf")
        )
    assert text is None
    assert fmt == "pdf"
    assert error is True
