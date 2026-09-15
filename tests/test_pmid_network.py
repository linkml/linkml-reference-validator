"""Exercise live Entrez transport and parsing against a controlled HTTP server."""

from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ssl import SSLEOFError
from threading import Event, Thread
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from Bio import Entrez
from Bio.Entrez import Parser
import pytest

from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.etl.sources.pmid import PMIDSource
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

SUMMARY = b"""<?xml version="1.0"?>
<!DOCTYPE eSummaryResult PUBLIC "-//NLM//DTD esummary v1 20041029//EN" "https://eutils.ncbi.nlm.nih.gov/eutils/dtd/20041029/esummary-v1.dtd">
<eSummaryResult><DocSum><Id>123</Id><Item Name="Title" Type="String">A study</Item>
<Item Name="AuthorList" Type="List"><Item Name="Author" Type="String">Smith J</Item></Item>
</DocSum></eSummaryResult>"""
ARTICLE = b"<PubmedArticleSet><PubmedArticle><Abstract><AbstractText>The patient recovered.</AbstractText></Abstract></PubmedArticle></PubmedArticleSet>"


@pytest.fixture
def ncbi(monkeypatch):
    """Redirect real Entrez urlopen to HTTP responses, including truncated bodies."""
    failures = {}
    counts = Counter()
    handles = []
    sleeps = []

    class Handler(BaseHTTPRequestHandler):
        """Serve scripted failures before a valid Entrez response."""

        def do_GET(self):
            """Drop headers/body or send a complete XML response."""
            endpoint = urlsplit(self.path).path.rsplit("/", 1)[-1]
            counts[endpoint] += 1
            script = failures.get(endpoint, [])
            action = script.pop(0) if script else "ok"
            if action == "timeout":
                Event().wait(3)
                self.close_connection = True
                return
            if action == "bad_status":
                self.wfile.write(b"Not an HTTP status\r\n\r\n")
                self.close_connection = True
                return
            if action == "disconnect":
                self.close_connection = True
                return
            if isinstance(action, int):
                self.send_error(action)
                return
            payload = SUMMARY if endpoint == "esummary.fcgi" else ARTICLE
            if action == "empty":
                payload = b""
            if action == "invalid":
                payload = b"not XML"
            if action == "no_abstract":
                payload = b"<PubmedArticleSet><PubmedArticle/></PubmedArticleSet>"
            self.send_response(200)
            self.send_header("Content-Type", "text/xml")
            self.send_header("X-Test-Failure", action)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            if action == "read_timeout":
                Event().wait(3)
                self.close_connection = True
                return
            self.wfile.write(payload[:20] if action == "truncate" else payload)
            self.close_connection = True

        def log_message(self, format, *args):
            """Suppress expected server error logging."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    class TLSFailureHandle:
        """Inject a TLS read failure after consuming bytes from a real HTTP handle.

        This boundary harness avoids relying on platform-specific OpenSSL EOF
        suppression, while exercising real request creation, IO and cleanup.
        """

        def __init__(self, handle):
            self.handle = handle

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self):
            """Consume a partial response before surfacing the TLS exception."""
            assert self.handle.read(20)
            raise SSLEOFError("TLS connection closed during response body")

    def local_urlopen(request):
        """Keep Entrez request creation/retries and use a real local HTTP handle."""
        parts = urlsplit(request.full_url)
        local = Request(
            f"http://127.0.0.1:{server.server_port}{parts.path}?{parts.query}",
            data=request.data,
            headers=dict(request.header_items()),
        )
        handle = urlopen(local, timeout=1)
        handles.append(handle)
        if handle.headers.get("X-Test-Failure") == "tls_eof":
            return TLSFailureHandle(handle)
        return handle

    def forbid_dtd_network(*args, **kwargs):
        """Ensure summary parsing uses the DTD bundled with Biopython."""
        pytest.fail("Entrez parser attempted an external DTD request")

    monkeypatch.setattr(Parser, "urlopen", forbid_dtd_network)
    monkeypatch.setattr(Entrez, "urlopen", local_urlopen)
    # Entrez.time is stdlib time: this also records validator sleeps. The
    # HTTP handler uses Event.wait so its intended timeouts remain real.
    monkeypatch.setattr(Entrez.time, "sleep", sleeps.append)
    # Use the real built-in retry loop with its normal limit.
    monkeypatch.setattr(Entrez, "max_tries", 3)
    try:
        yield failures, counts, handles, sleeps
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def config(tmp_path):
    """Isolate cache writes and disable unrelated full-text providers."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path, fetch_full_text=False, rate_limit_delay=0
    )


@pytest.mark.parametrize("endpoint", ["esummary.fcgi", "efetch.fcgi"])
@pytest.mark.parametrize(
    "failure",
    ["truncate", "disconnect", "timeout", "read_timeout", "bad_status", "tls_eof"],
)
def test_transient_recovery(ncbi, config, endpoint, failure):
    """Opening and body failures recover, and every response handle closes."""
    failures, counts, handles, sleeps = ncbi
    failures[endpoint] = [failure, failure]
    ref = PMIDSource().fetch("123", config)
    assert ref is not None
    assert ref.content == "The patient recovered."
    assert counts[endpoint] == 3
    assert all(handle.closed for handle in handles)
    assert 2 in sleeps and 4 in sleeps


@pytest.mark.parametrize("endpoint", ["esummary.fcgi", "efetch.fcgi"])
@pytest.mark.parametrize(
    "failure",
    ["truncate", "disconnect", "timeout", "read_timeout", "bad_status", "tls_eof"],
)
def test_exhaustion_does_not_pass_or_abort_next_reference(
    ncbi, config, endpoint, failure
):
    """An exhausted PMID fails validation while the next PMID still succeeds."""
    failures, counts, handles, _ = ncbi
    failures[endpoint] = [failure] * 3
    validator = SupportingTextValidator(config)
    assert not validator.validate("The patient recovered.", "PMID:123").is_valid
    assert counts[endpoint] == 3
    assert validator.validate("The patient recovered.", "PMID:456").is_valid
    assert all(handle.closed for handle in handles)


@pytest.mark.parametrize("status,attempts", [(400, 1), (429, 3), (503, 3)])
@pytest.mark.parametrize("endpoint", ["esummary.fcgi", "efetch.fcgi"])
def test_entrez_open_retries_are_not_multiplied(
    ncbi, config, endpoint, status, attempts
):
    """Already-exhausted Entrez HTTP retries are not wrapped in another loop."""
    failures, counts, handles, _ = ncbi
    failures[endpoint] = [status] * 12
    assert PMIDSource().fetch("123", config) is None
    assert counts[endpoint] == attempts
    assert all(handle.closed for handle in handles)


def test_summary_parse_error_is_not_retried(ncbi, config):
    """A complete but invalid summary is a deterministic failure, not a retry."""
    failures, counts, handles, _ = ncbi
    failures["esummary.fcgi"] = ["invalid"]
    assert PMIDSource().fetch("123", config) is None
    assert counts["esummary.fcgi"] == 1
    assert all(handle.closed for handle in handles)


@pytest.mark.parametrize("force_refresh", [False, True])
def test_partial_refresh_preserves_stale_cache(ncbi, config, force_refresh):
    """Summary success plus XML exhaustion must not replace useful stale text."""
    fetcher = ReferenceFetcher(config)
    old = ReferenceContent(
        reference_id="PMID:123",
        content="Useful older text.",
        content_type="abstract_only",
    )
    fetcher._save_to_disk(old)
    path = fetcher.get_cache_path("PMID:123")
    stale = path.read_text().replace(
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}", "extractor_version: 0"
    )
    path.write_text(stale)
    failures, counts, _, _ = ncbi
    failures["efetch.fcgi"] = ["truncate"] * 3
    ref = fetcher.fetch("PMID:123", force_refresh=force_refresh)
    assert counts["efetch.fcgi"] == 3
    if force_refresh:
        assert ref is None
    else:
        assert ref is not None and ref.content == old.content
        assert fetcher.fetch("PMID:123") is ref
        assert counts["efetch.fcgi"] == 3
    assert path.read_text() == stale


def test_article_parser_is_outside_retry_boundary(ncbi, config, monkeypatch):
    """A parser defect after successful real HTTP fetches is raised just once."""
    _, counts, handles, _ = ncbi
    calls = []

    def broken_parser(content, parser):
        """Represent a deterministic extraction defect after transport succeeds."""
        calls.append(content)
        raise ValueError("invalid parser configuration")

    monkeypatch.setattr(
        "linkml_reference_validator.etl.sources.pmid.BeautifulSoup", broken_parser
    )
    with pytest.raises(ValueError, match="invalid parser configuration"):
        PMIDSource().fetch("123", config)
    assert calls == [ARTICLE]
    assert counts["efetch.fcgi"] == 1
    assert all(handle.closed for handle in handles)


def test_complete_record_without_abstract_remains_unavailable(ncbi, config):
    """A successful no-abstract response remains distinct from transport failure."""
    failures, counts, _, _ = ncbi
    failures["efetch.fcgi"] = ["no_abstract"]
    ref = PMIDSource().fetch("123", config)
    assert ref is not None
    assert ref.title == "A study"
    assert ref.content_type == "unavailable"
    assert ref.content is None
    assert counts["efetch.fcgi"] == 1


@pytest.mark.parametrize("endpoint", ["esummary.fcgi", "efetch.fcgi"])
@pytest.mark.parametrize("last_response", ["ok", "truncate"])
def test_mixed_open_and_body_failures_have_a_finite_bound(
    ncbi, config, endpoint, last_response
):
    """Built-in open retries followed by body failures take at most nine requests."""
    failures, counts, handles, _ = ncbi
    failures[endpoint] = [503, 503, "truncate"] * 2 + [503, 503, last_response]
    ref = PMIDSource().fetch("123", config)
    assert (ref is not None) == (last_response == "ok")
    assert counts[endpoint] == 9
    assert Entrez.max_tries == 3
    assert all(handle.closed for handle in handles)


def test_connection_refused_uses_only_entrez_retries(ncbi, config, monkeypatch):
    """Real connection refusal exhausts the library limit without outer retries."""
    import socket

    _, _, _, sleeps = ncbi
    attempts = []
    with socket.socket() as endpoint:
        # A bound socket without listen() reserves a port that refuses connections.
        endpoint.bind(("127.0.0.1", 0))
        port = endpoint.getsockname()[1]

        def refused_urlopen(request):
            """Exercise urllib's real connection-error wrapping."""
            attempts.append(request)
            return urlopen(f"http://127.0.0.1:{port}/", timeout=1)

        monkeypatch.setattr(Entrez, "urlopen", refused_urlopen)
        assert PMIDSource().fetch("123", config) is None
    assert len(attempts) == 3
    assert sleeps.count(Entrez.sleep_between_tries) == 2
    assert 2 not in sleeps and 4 not in sleeps


def test_empty_article_response_does_not_replace_stale_text(ncbi, config):
    """A complete empty body provides no replacement article text for a cache."""
    fetcher = ReferenceFetcher(config)
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id="PMID:123",
            content="Useful older text.",
            content_type="abstract_only",
        )
    )
    path = fetcher.get_cache_path("PMID:123")
    stale = path.read_text().replace(
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}", "extractor_version: 0"
    )
    path.write_text(stale)
    failures, counts, handles, _ = ncbi
    failures["efetch.fcgi"] = ["empty"]
    ref = fetcher.fetch("PMID:123")
    assert ref is not None and ref.content == "Useful older text."
    assert path.read_text() == stale
    assert counts["efetch.fcgi"] == 1
    assert all(handle.closed for handle in handles)
