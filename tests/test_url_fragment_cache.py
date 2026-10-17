"""``url:`` references differing only by fragment share one cache entry (#114).

Citing pages 54, 55 and 56 of one PDF as ``...pdf#page=54`` and so on used to
write three cache files, each holding the whole extracted document. A fragment
is never sent to the server, so the fetched bytes are the same for all of them:
the cache key drops it, while the reference handed back to the caller keeps the
page-anchored URL it asked for. Query strings stay part of the identity.

The fetch tests serve a real PDF from a local HTTP server rather than mocking
the acquirer, so "fetched once" is counted at the socket.
"""

from __future__ import annotations

import io
import re
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from linkml_reference_validator import validate_cache_file
from linkml_reference_validator.cache import cache_filename, cache_key
from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    URL_SOURCE_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.models import ReferenceValidationConfig

PDF_TEXT = "Soil respiration increased under drought"


def _text_pdf(text: str) -> bytes:
    """Build a one-page PDF whose page draws ``text``, so extraction finds it."""
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=100)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    stream.set_data(f"BT /F1 12 Tf 10 50 Td ({text}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


@pytest.fixture
def pdf_server():
    """Serve one PDF at any path; count the requests each path receives."""
    body = _text_pdf(PDF_TEXT)
    hits: dict[str, int] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's naming
            hits[self.path] = hits.get(self.path, 0) + 1
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", hits
    server.shutdown()
    server.server_close()


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)


def _md_files(cache_dir: Path) -> list[Path]:
    return sorted(cache_dir.glob("*.md"))


# --- the key ----------------------------------------------------------------


def test_fragment_variants_share_a_cache_path(config):
    fetcher = ReferenceFetcher(config)
    base = "url:https://example.org/report.pdf"
    paths = {fetcher.get_cache_path(f"{base}#page={n}") for n in (54, 55, 56)}
    assert paths == {fetcher.get_cache_path(base)}
    assert "#" not in fetcher.get_cache_path(f"{base}#page=54").name


def test_query_strings_stay_distinct(config):
    fetcher = ReferenceFetcher(config)
    first = fetcher.get_cache_path("url:https://example.org/doc.pdf?v=1#page=2")
    second = fetcher.get_cache_path("url:https://example.org/doc.pdf?v=2#page=2")
    assert first != second
    assert first == fetcher.get_cache_path("url:https://example.org/doc.pdf?v=1")


def test_only_url_references_are_defragmented():
    assert cache_key("file:./notes.md#section") == "file:./notes.md#section"
    assert cache_key("PMID:123") == "PMID:123"
    assert cache_filename("url:https://example.org/a.pdf#page=3") == cache_filename(
        "url:https://example.org/a.pdf"
    )


# --- fetching ---------------------------------------------------------------


def test_page_anchored_urls_reuse_one_extraction(pdf_server, config):
    base, hits = pdf_server
    url = f"{base}/proposal.pdf"
    fetcher = ReferenceFetcher(config)

    refs = [fetcher.fetch(f"url:{url}#page={n}") for n in (54, 55, 56)]

    assert hits == {"/proposal.pdf": 1}
    assert [ref.reference_id for ref in refs] == [
        f"url:{url}#page={n}" for n in (54, 55, 56)
    ]
    assert all(PDF_TEXT in ref.content for ref in refs)
    files = _md_files(config.get_cache_dir())
    assert [f.name for f in files] == [cache_filename(f"url:{url}")]
    assert validate_cache_file(files[0]).is_valid


def test_a_new_process_reads_the_shared_entry_with_its_own_url(pdf_server, config):
    base, hits = pdf_server
    url = f"{base}/proposal.pdf"
    ReferenceFetcher(config).fetch(f"url:{url}#page=54")

    later = ReferenceFetcher(config).fetch(f"url:{url}#page=55")

    assert hits == {"/proposal.pdf": 1}
    assert later.reference_id == f"url:{url}#page=55"
    assert PDF_TEXT in later.content


def test_different_queries_are_fetched_separately(pdf_server, config):
    base, hits = pdf_server
    fetcher = ReferenceFetcher(config)
    fetcher.fetch(f"url:{base}/doc.pdf?v=1#page=1")
    fetcher.fetch(f"url:{base}/doc.pdf?v=2#page=1")
    assert hits == {"/doc.pdf?v=1": 1, "/doc.pdf?v=2": 1}
    assert len(_md_files(config.get_cache_dir())) == 2


# --- caches written before this change --------------------------------------


def _legacy_entry(cache_dir: Path, reference_id: str, body: str) -> Path:
    """A current-format entry written under the old fragment-keyed filename."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    # The pre-#114 sanitization, fragment and all.
    path = cache_dir / (re.sub(r"[:/?=]", "_", reference_id) + ".md")
    path.write_text(
        "\n".join(
            [
                "---",
                f"reference_id: {reference_id}",
                f"extractor_version: {EXTRACTOR_CACHE_VERSION}",
                f"url_source_version: {URL_SOURCE_CACHE_VERSION}",
                "content_type: full_text_pdf",
                "---",
                "",
                "## Content",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_legacy_fragment_keyed_entry_is_still_read(pdf_server, config):
    base, hits = pdf_server
    reference_id = f"url:{base}/proposal.pdf#page=54"
    legacy = _legacy_entry(config.get_cache_dir(), reference_id, "Legacy cached text.")
    assert "#page_54" in legacy.name

    ref = ReferenceFetcher(config).fetch(reference_id)

    assert hits == {}
    assert ref.reference_id == reference_id
    assert "Legacy cached text." in ref.content


def test_legacy_entry_is_still_a_valid_cache_file(tmp_path):
    legacy = _legacy_entry(tmp_path, "url:https://example.org/a.pdf#page=54", "Text.")
    assert validate_cache_file(legacy).is_valid


def test_shared_entry_wins_over_a_legacy_one(pdf_server, config):
    """Once the shared entry exists it is the one read, for every fragment."""
    base, hits = pdf_server
    url = f"{base}/proposal.pdf"
    _legacy_entry(config.get_cache_dir(), f"url:{url}#page=54", "Legacy cached text.")
    ReferenceFetcher(config).fetch(f"url:{url}#page=55")  # writes the shared entry

    ref = ReferenceFetcher(config).fetch(f"url:{url}#page=54")

    assert hits == {"/proposal.pdf": 1}
    assert PDF_TEXT in ref.content
    assert ref.reference_id == f"url:{url}#page=54"
