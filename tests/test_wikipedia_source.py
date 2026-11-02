"""The built-in WIKIPEDIA source reads an article's plain text from the MediaWiki API (#164).

These tests serve real HTTP from a local server shaped like the MediaWiki Action
API (``formatversion=2``), so the source, the fetcher and the cache all run as
they do against Wikipedia.
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.parse import parse_qs, urlparse

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
from linkml_reference_validator.etl.sources.json_api import register_json_api_source
from linkml_reference_validator.etl.sources.wikipedia import WikipediaSource, canonical_title
from linkml_reference_validator.models import (
    JSONAPISourceConfig,
    ReferenceValidationConfig,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

SAANEN_EXTRACT = (
    "The Saanen is a Swiss breed of domestic goat. It is named for the Saanen valley "
    "in the Bernese Oberland, in the south-west of the canton of Bern.\n\n\n"
    "== History ==\n"
    "The Saanen originates in the historic region of Saanen, in the Bernese Oberland. "
    "It has been exported to many countries.\n\n\n"
    "=== Distribution ===\n"
    "It is kept for milk in more than eighty countries.\n\n\n"
    "== See also ==\n"
)

SAANEN_PAGE = {
    "pageid": 3307245,
    "ns": 0,
    "title": "Saanen goat",
    "extract": SAANEN_EXTRACT,
    "revisions": [{"revid": 1250000001, "parentid": 1249999999, "timestamp": "2026-09-01T12:00:00Z"}],
    "fullurl": "https://en.wikipedia.org/wiki/Saanen_goat",
    "canonicalurl": "https://en.wikipedia.org/wiki/Saanen_goat",
}

CAFE_PAGE = {
    "pageid": 42,
    "ns": 0,
    "title": "Café",
    "extract": "A café is an establishment that primarily serves hot coffee.",
    "revisions": [{"revid": 7, "parentid": 6, "timestamp": "2026-01-01T00:00:00Z"}],
    "canonicalurl": "https://en.wikipedia.org/wiki/Caf%C3%A9",
}


def _respond(title: str) -> dict:
    """Answer a ``titles=`` query the way MediaWiki does, for the pages these tests know."""
    normalized = title.replace("_", " ")
    query: dict = {}
    if normalized != title:
        query["normalized"] = [{"fromencoded": False, "from": title, "to": normalized}]
    if normalized == "Saanen":
        query["redirects"] = [{"from": "Saanen", "to": "Saanen goat"}]
        query["pages"] = [SAANEN_PAGE]
    elif normalized == "Saanen goat":
        query["pages"] = [SAANEN_PAGE]
    elif normalized == "Café":
        query["pages"] = [CAFE_PAGE]
    elif "<" in normalized:
        query["pages"] = [{"title": normalized, "invalidreason": "bad", "invalid": True}]
    else:
        query["pages"] = [{"ns": 0, "title": normalized, "missing": True}]
    return {"batchcomplete": True, "query": query}


@pytest.fixture
def wiki_server(monkeypatch):
    """Serve MediaWiki-shaped responses and record each request's query and headers."""
    seen: list[dict] = []
    state = {"status": 200}

    class Handler(BaseHTTPRequestHandler):
        """A minimal stand-in for https://en.wikipedia.org/w/api.php."""

        def do_GET(self):
            """Record the request, then answer it or fail with the chosen status."""
            params = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            seen.append({"params": params, "user_agent": self.headers.get("User-Agent")})
            self.send_response(state["status"])
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            if state["status"] == 200:
                self.wfile.write(json.dumps(_respond(params["titles"])).encode())
            else:
                self.wfile.write(b"Too many requests")

        def log_message(self, format, *args):
            """Keep the test server quiet."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        "linkml_reference_validator.etl.sources.wikipedia.WIKIPEDIA_API_URL",
        f"http://127.0.0.1:{server.server_port}/w/api.php",
    )
    try:
        yield seen, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.fixture
def config(tmp_path):
    """An isolated cache, no rate-limit delay, and a contact address."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        email="curator@example.org",
    )


@pytest.mark.parametrize(
    "reference_id, handled",
    [
        ("WIKIPEDIA:Saanen_goat", True),
        ("wikipedia:Saanen goat", True),
        ("Wikipedia:Star_Trek:_Voyager", True),
        ("url:https://en.wikipedia.org/wiki/Saanen_goat", False),
        ("PMID:12345678", False),
        ("WIKIDATA:Q42", False),
    ],
)
def test_the_source_claims_wikipedia_ids_only(reference_id, handled):
    assert WikipediaSource.can_handle(reference_id) is handled


def test_the_registry_dispatches_wikipedia_ids_to_the_source():
    assert ReferenceSourceRegistry.get_source("WIKIPEDIA:Saanen_goat") is WikipediaSource


def test_ids_normalize_to_the_uppercase_prefix(config):
    fetcher = ReferenceFetcher(config)
    assert fetcher.normalize_reference_id("wikipedia:Saanen_goat") == "WIKIPEDIA:Saanen_goat"


def test_an_article_is_fetched_as_plain_full_text(config, wiki_server):
    seen, _ = wiki_server
    reference = ReferenceFetcher(config).fetch("WIKIPEDIA:Saanen_goat")

    assert reference is not None
    assert reference.reference_id == "WIKIPEDIA:Saanen_goat"
    assert reference.title == "Saanen goat"
    assert reference.content_type == "full_text"
    assert "The Saanen originates in the historic region of Saanen" in reference.content
    assert "<" not in reference.content


def test_section_headings_are_plain_lines(config, wiki_server):
    reference = ReferenceFetcher(config).fetch("WIKIPEDIA:Saanen_goat")

    assert reference is not None
    lines = reference.content.splitlines()
    assert "History" in lines
    assert "Distribution" in lines
    assert "=" not in reference.content


def test_provenance_is_recorded(config, wiki_server):
    reference = ReferenceFetcher(config).fetch("WIKIPEDIA:Saanen_goat")

    assert reference is not None
    assert reference.license == "CC BY-SA 4.0"
    assert reference.source_revision == "1250000001"
    assert reference.source_revision_timestamp == "2026-09-01T12:00:00Z"
    assert reference.source_url == "https://en.wikipedia.org/wiki/Saanen_goat"


def test_the_request_asks_for_plain_text_and_names_a_contact(config, wiki_server):
    seen, _ = wiki_server
    ReferenceFetcher(config).fetch("WIKIPEDIA:Saanen_goat")

    assert len(seen) == 1
    params = seen[0]["params"]
    assert params["titles"] == "Saanen_goat"
    assert params["action"] == "query"
    assert params["explaintext"] == "1"
    assert params["redirects"] == "1"
    assert params["formatversion"] == "2"
    assert "mailto:curator@example.org" in seen[0]["user_agent"]


def test_a_redirect_is_followed_and_recorded(config, wiki_server):
    reference = ReferenceFetcher(config).fetch("WIKIPEDIA:Saanen")

    assert reference is not None
    assert reference.reference_id == "WIKIPEDIA:Saanen"
    assert reference.title == "Saanen goat"
    assert reference.source_url == "https://en.wikipedia.org/wiki/Saanen_goat"


def test_a_percent_encoded_title_is_decoded(config, wiki_server):
    seen, _ = wiki_server
    reference = ReferenceFetcher(config).fetch("WIKIPEDIA:Caf%C3%A9")

    assert seen[0]["params"]["titles"] == "Café"
    assert reference is not None
    assert reference.title == "Café"


@pytest.mark.parametrize("reference_id", ["WIKIPEDIA:No_such_article_zzqq", "WIKIPEDIA:Bad<title>"])
def test_a_missing_or_invalid_page_gives_no_result(config, wiki_server, reference_id):
    assert ReferenceFetcher(config).fetch(reference_id) is None


def test_a_throttled_request_gives_no_result(config, wiki_server):
    _, state = wiki_server
    state["status"] = 429
    assert ReferenceFetcher(config).fetch("WIKIPEDIA:Saanen_goat") is None


def test_the_cache_keeps_the_article_and_its_revision(config, wiki_server):
    seen, state = wiki_server
    ReferenceFetcher(config).fetch("WIKIPEDIA:Saanen_goat")
    state["status"] = 429  # anything served from here on comes from the cache

    reference = ReferenceFetcher(config).fetch("WIKIPEDIA:Saanen_goat")

    assert len(seen) == 1
    assert reference is not None
    assert reference.content_type == "full_text"
    assert reference.license == "CC BY-SA 4.0"
    assert reference.source_revision == "1250000001"
    assert reference.source_revision_timestamp == "2026-09-01T12:00:00Z"
    assert reference.source_url == "https://en.wikipedia.org/wiki/Saanen_goat"
    assert "The Saanen originates in the historic region of Saanen" in reference.content


def test_a_quote_from_the_article_validates(config, wiki_server):
    """The quote from mechmaker#6 that failed against the cached raw HTML."""
    result = SupportingTextValidator(config).validate(
        "The Saanen originates in the historic region of Saanen",
        "WIKIPEDIA:Saanen_goat",
        expected_title="Saanen goat",
    )
    assert result.is_valid, result.message


def test_a_quote_not_in_the_article_fails_without_an_abstract_note(config, wiki_server):
    result = SupportingTextValidator(config).validate(
        "The Saanen was first bred on the Moon", "WIKIPEDIA:Saanen_goat"
    )
    assert not result.is_valid
    assert "only abstract available" not in (result.message or "")


@pytest.fixture
def restore_registry():
    """Put the global source registry back as it was after the test."""
    saved = list(ReferenceSourceRegistry._sources)
    try:
        yield
    finally:
        ReferenceSourceRegistry._sources = saved


def test_a_projects_own_wikipedia_source_takes_precedence(restore_registry):
    """A project that configured WIKIPEDIA itself (mechmaker#6) keeps its source."""
    custom = register_json_api_source(
        JSONAPISourceConfig(
            prefix="WIKIPEDIA",
            url_template="https://example.org/{id}",
            id_patterns=[r"^\S+$"],
            fields={"title": "$.title", "content": "$.extract"},
        )
    )
    assert ReferenceSourceRegistry.get_source("WIKIPEDIA:Saanen_goat") is custom
    # Its bare-ID pattern matches anything without a space; it must still not
    # displace the sources that were ahead of it before.
    for reference_id, prefix in [
        ("PMID:12345678", "PMID"),
        ("DOI:10.1234/x", "DOI"),
        ("NCT12345678", "clinicaltrials"),
    ]:
        source = ReferenceSourceRegistry.get_source(reference_id)
        assert source is not None and source.prefix() == prefix


def test_a_custom_source_for_a_new_prefix_is_still_tried_last(restore_registry):
    custom = register_json_api_source(
        JSONAPISourceConfig(prefix="MYDB", url_template="https://example.org/{id}", fields={})
    )
    assert ReferenceSourceRegistry.list_sources()[-1] is custom


SPELLINGS = [
    "WIKIPEDIA:Saanen_goat",
    "WIKIPEDIA:Saanen goat",
    "WIKIPEDIA:Saanen%20goat",
    "WIKIPEDIA:saanen_goat",
    "wikipedia: Saanen  goat ",
]


@pytest.mark.parametrize("reference_id", SPELLINGS)
def test_every_spelling_of_a_title_normalizes_to_one_id(config, reference_id):
    """Wikipedia treats these as one article, so the cache must too (review of #165)."""
    fetcher = ReferenceFetcher(config)
    assert fetcher.normalize_reference_id(reference_id) == "WIKIPEDIA:Saanen_goat"
    assert fetcher.get_cache_path(reference_id).name == "WIKIPEDIA_Saanen_goat.md"


def test_every_spelling_shares_one_fetch_and_one_cache_file(config, wiki_server):
    seen, _ = wiki_server
    fetcher = ReferenceFetcher(config)
    for reference_id in SPELLINGS:
        reference = fetcher.fetch(reference_id)
        assert reference is not None
        assert reference.reference_id == "WIKIPEDIA:Saanen_goat"
    assert len(seen) == 1
    assert [p.name for p in config.cache_dir.iterdir()] == ["WIKIPEDIA_Saanen_goat.md"]


@pytest.mark.parametrize(
    "title, canonical",
    [
        ("Saanen goat", "Saanen_goat"),
        ("Caf%C3%A9", "Café"),
        ("iPhone", "IPhone"),  # MediaWiki upper-cases the first letter of every title
        ("Star Trek: Voyager", "Star_Trek:_Voyager"),
        ("__Saanen___goat_", "Saanen_goat"),
    ],
)
def test_canonical_title(title, canonical):
    assert canonical_title(title) == canonical


def test_a_projects_own_wikipedia_source_keeps_its_ids(config, restore_registry):
    """Canonical titles are the built-in source's rule; a project's own source keeps its IDs."""
    register_json_api_source(
        JSONAPISourceConfig(
            prefix="WIKIPEDIA",
            url_template="https://example.org/{id}",
            fields={"title": "$.title"},
        )
    )
    fetcher = ReferenceFetcher(config)
    assert fetcher.normalize_reference_id("WIKIPEDIA:Saanen goat") == "WIKIPEDIA:Saanen goat"


def test_a_direct_fetch_returns_the_canonical_id(config, wiki_server):
    """The source gives one ID for an article however it is called, not only via the fetcher."""
    reference = WikipediaSource().fetch("saanen goat", config)
    assert reference is not None
    assert reference.reference_id == "WIKIPEDIA:Saanen_goat"


def test_a_section_anchor_cites_the_whole_article(config, wiki_server):
    """A title copied from a URL with #Section is the article; '#' cannot be in a title."""
    seen, _ = wiki_server
    fetcher = ReferenceFetcher(config)
    assert fetcher.normalize_reference_id("WIKIPEDIA:Saanen_goat#History") == "WIKIPEDIA:Saanen_goat"
    reference = fetcher.fetch("WIKIPEDIA:Saanen_goat#History")
    assert reference is not None
    assert reference.reference_id == "WIKIPEDIA:Saanen_goat"
    assert seen[0]["params"]["titles"] == "Saanen_goat"
