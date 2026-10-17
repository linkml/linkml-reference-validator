"""GeneReviews and other NCBI Bookshelf chapters get full text (#41).

A PMID for a Bookshelf chapter has no PMC copy, so the chain used to stop at
the abstract. Bookshelf's own pages answer a script with a reCAPTCHA page on an
HTTP 200, so the text comes from NCBI's machine-retrieval archive (litarch)
instead: one tarball per book, unpacked once into ``bookshelf_archive_dir``.

The PubMed record already names the chapter -- ``book="gene"``,
``part="men1"`` -- so the provider looks it up on disk with no network call.

Fixtures are real NCBI data, trimmed: the PubMed record and esummary for
PMID:20301710 (GeneReviews, MEN1) and the first section of the chapter's
litarch ``men1.nxml``. Network calls go to a local HTTP server, never mocks.
"""

from __future__ import annotations

import csv
import io
import shutil
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

import pytest
from bs4 import BeautifulSoup
from Bio import Entrez
from Bio.Entrez import Parser
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.etl.fulltext.bookshelf import (
    BookshelfFullTextProvider,
    download_book,
)
from linkml_reference_validator.etl.identifiers import build_identifiers
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.etl.sources.pmid import PMIDSource
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)

FIXTURES = Path(__file__).parent / "fixtures" / "bookshelf"
PUBMED_XML = (FIXTURES / "pubmed_20301710.xml").read_bytes()
ESUMMARY_XML = (FIXTURES / "esummary_20301710.xml").read_bytes()
CHAPTER = FIXTURES / "gene_NBK1116" / "men1.nxml"
# From the chapter body, not the PubMed abstract.
CHAPTER_SENTENCE = (
    "Imaging is not usually required for diagnosis of parathyroid disease"
)
MEN1 = ReferenceIdentifiers(
    pmid="20301710", bookshelf_accession="NBK1538", bookshelf_part="gene/men1"
)


@pytest.fixture
def archive(tmp_path):
    """A litarch archive directory holding the one fixture chapter."""
    root = tmp_path / "bookshelf"
    shutil.copytree(FIXTURES / "gene_NBK1116", root / "gene_NBK1116")
    return root


@pytest.fixture
def config(tmp_path, archive):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        bookshelf_archive_dir=archive,
        full_text_providers=["bookshelf"],
    )


# --- reading the chapter out of the PubMed record ---------------------------


def test_pubmed_record_names_the_chapter():
    soup = BeautifulSoup(PUBMED_XML, "xml")
    assert PMIDSource._parse_bookshelf_chapter(soup) == ("NBK1538", "gene/men1")


def test_a_journal_article_names_no_chapter():
    soup = BeautifulSoup(
        b"<PubmedArticleSet><PubmedArticle><MedlineCitation><Article>"
        b"<ArticleTitle>A study</ArticleTitle></Article></MedlineCitation>"
        b"</PubmedArticle></PubmedArticleSet>",
        "xml",
    )
    assert PMIDSource._parse_bookshelf_chapter(soup) is None


def test_identifiers_carry_the_chapter():
    content = ReferenceContent(
        reference_id="PMID:20301710",
        metadata={"bookshelf_accession": "NBK1538", "bookshelf_part": "gene/men1"},
    )
    ids = build_identifiers(content)
    assert (ids.bookshelf_accession, ids.bookshelf_part) == ("NBK1538", "gene/men1")


# --- the provider -----------------------------------------------------------


def test_provider_reads_the_chapter_from_the_archive(config):
    location = BookshelfFullTextProvider().locate(MEN1, config)

    assert location is not None and not location.declined
    assert CHAPTER_SENTENCE in location.text
    assert location.format_hint == "xml"
    assert location.provider == "bookshelf"
    assert location.url == "https://www.ncbi.nlm.nih.gov/books/NBK1538/"
    assert location.access_type is None


def test_a_reference_that_is_not_a_chapter_is_skipped(config):
    assert BookshelfFullTextProvider().locate(ReferenceIdentifiers(pmid="1"), config) is None


def test_without_an_archive_the_chapter_is_declined_not_absent(config):
    config.bookshelf_archive_dir = None
    location = BookshelfFullTextProvider().locate(MEN1, config)
    assert location is not None
    assert location.declined == "bookshelf_archive_not_configured"
    assert location.text is None


def test_a_book_missing_from_the_archive_is_declined(config, archive):
    shutil.rmtree(archive / "gene_NBK1116")
    location = BookshelfFullTextProvider().locate(MEN1, config)
    assert location.declined == "bookshelf_book_not_in_archive:gene"


def test_a_chapter_missing_from_the_archive_is_declined(config, archive):
    (archive / "gene_NBK1116" / "men1.nxml").unlink()
    location = BookshelfFullTextProvider().locate(MEN1, config)
    assert location.declined == "bookshelf_chapter_not_in_archive:gene/men1"


def test_a_chapter_without_an_open_access_licence_is_declined(config, archive):
    path = archive / "gene_NBK1116" / "men1.nxml"
    text = path.read_text(encoding="utf-8")
    path.write_text(
        text.replace('license-type="open-access"', 'license-type="restricted"'),
        encoding="utf-8",
    )
    location = BookshelfFullTextProvider().locate(MEN1, config)
    assert location.declined == "bookshelf_licence:restricted"


@pytest.mark.parametrize("part", ["gene/../../etc/passwd", "../gene/men1", "gene/men1/x", "gene"])
def test_a_malformed_part_never_leaves_the_archive(config, part):
    ids = ReferenceIdentifiers(pmid="1", bookshelf_accession="NBK1", bookshelf_part=part)
    assert BookshelfFullTextProvider().locate(ids, config) is None


def test_bookshelf_is_in_the_default_chain_after_pmc():
    chain = ReferenceValidationConfig().full_text_providers
    assert chain.index("bookshelf") == chain.index("pmc") + 1


# --- end to end through PMIDSource and the fetcher --------------------------


@pytest.fixture
def ncbi(monkeypatch):
    """Answer Entrez esummary/efetch from the fixtures over real HTTP."""
    requests_seen: list[str] = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802 - http.server's naming
            endpoint = urlsplit(self.path).path.rsplit("/", 1)[-1]
            requests_seen.append(endpoint)
            payload = ESUMMARY_XML if endpoint == "esummary.fcgi" else PUBMED_XML
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def local_urlopen(request):
        parts = urlsplit(request.full_url)
        local = Request(
            f"http://127.0.0.1:{server.server_port}{parts.path}?{parts.query}",
            data=request.data,
            headers=dict(request.header_items()),
        )
        return urlopen(local, timeout=5)

    def forbid_dtd_network(*args, **kwargs):
        pytest.fail("Entrez parser attempted an external DTD request")

    monkeypatch.setattr(Parser, "urlopen", forbid_dtd_network)
    monkeypatch.setattr(Entrez, "urlopen", local_urlopen)
    yield requests_seen
    server.shutdown()
    server.server_close()


def test_pmid_fetch_records_the_chapter(ncbi, config):
    content = PMIDSource().fetch("20301710", config)
    assert content.content_type == "abstract_only"
    assert content.metadata["bookshelf_accession"] == "NBK1538"
    assert content.metadata["bookshelf_part"] == "gene/men1"


def test_a_genereviews_pmid_gets_chapter_full_text(ncbi, config):
    reference = ReferenceFetcher(config).fetch("PMID:20301710")

    assert reference.content_type == "full_text_xml"
    assert reference.full_text_provider == "bookshelf"
    assert reference.full_text_url == "https://www.ncbi.nlm.nih.gov/books/NBK1538/"
    assert CHAPTER_SENTENCE in reference.content
    cached = (config.get_cache_dir() / "PMID_20301710.md").read_text(encoding="utf-8")
    assert "full_text_provider: bookshelf" in cached
    assert CHAPTER_SENTENCE in cached
    # Only the two PubMed calls: the chapter came off disk.
    assert sorted(ncbi) == ["efetch.fcgi", "esummary.fcgi"]


def test_without_an_archive_the_abstract_stays_retryable(ncbi, config):
    config.bookshelf_archive_dir = None
    reference = ReferenceFetcher(config).fetch("PMID:20301710")

    assert reference.content_type == "abstract_only"
    assert reference.full_text_declined == "bookshelf_archive_not_configured"
    assert not reference.full_text_attempted


# --- downloading a book -----------------------------------------------------


def _book_tarball() -> bytes:
    """A litarch-shaped tarball: chapters, a figure, and one hostile member."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        tar.add(CHAPTER, arcname="gene_NBK1116/men1.nxml")
        for name, data in [
            ("gene_NBK1116/men1-Image001.jpg", b"\xff\xd8 not really a jpeg"),
            ("gene_NBK1116/../../escaped.nxml", b"<x/>"),
        ]:
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@pytest.fixture
def litarch():
    """Serve a litarch mirror: file_list.csv plus one book tarball."""
    tarball = _book_tarball()
    listing = io.StringIO()
    writer = csv.writer(listing)
    writer.writerow(
        ["File", "Title", "Publisher", "Publication Year", "Accession ID", "Last Updated (YYYY-MM-DD HH:MM:SS)"]
    )
    writer.writerow(
        ["ca/84/gene_NBK1116.tar.gz", "GeneReviews&#174;", "University of Washington, Seattle", "1993", "NBK1116", "2026-10-16 02:42:01"]
    )
    files = {
        "/file_list.csv": listing.getvalue().encode(),
        "/ca/84/gene_NBK1116.tar.gz": tarball,
    }

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = files.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


def test_download_unpacks_only_chapters(litarch, tmp_path):
    archive = tmp_path / "archive"
    book_dir = download_book(
        "NBK1116", archive, ReferenceValidationConfig(rate_limit_delay=0.0), mirror=litarch
    )

    assert book_dir == archive / "gene_NBK1116"
    assert sorted(p.name for p in book_dir.iterdir()) == ["men1.nxml"]
    assert (book_dir / "men1.nxml").read_bytes() == CHAPTER.read_bytes()
    assert not (tmp_path / "escaped.nxml").exists()
    assert sorted(p.name for p in archive.iterdir()) == ["gene_NBK1116"]


def test_redownload_replaces_the_book(litarch, tmp_path):
    archive = tmp_path / "archive"
    config = ReferenceValidationConfig(rate_limit_delay=0.0)
    stale = archive / "gene_NBK1116" / "retired-chapter.nxml"
    stale.parent.mkdir(parents=True)
    stale.write_text("<old/>", encoding="utf-8")

    download_book("NBK1116", archive, config, mirror=litarch)

    assert sorted(p.name for p in (archive / "gene_NBK1116").iterdir()) == ["men1.nxml"]


def test_an_unknown_accession_is_an_error(litarch, tmp_path):
    with pytest.raises(ValueError, match="NBK9999999"):
        download_book(
            "NBK9999999", tmp_path, ReferenceValidationConfig(rate_limit_delay=0.0), mirror=litarch
        )


def test_cli_downloads_a_book(litarch, tmp_path):
    archive = tmp_path / "archive"
    result = CliRunner().invoke(
        app,
        ["cache", "bookshelf-download", "NBK1116", "--archive-dir", str(archive), "--mirror", litarch],
    )
    assert result.exit_code == 0, result.output
    assert (archive / "gene_NBK1116" / "men1.nxml").exists()
    assert "1 chapter" in result.stdout


def test_cli_needs_an_archive_dir(tmp_path):
    result = CliRunner().invoke(app, ["cache", "bookshelf-download", "NBK1116"])
    assert result.exit_code != 0
    assert "bookshelf_archive_dir" in result.output
