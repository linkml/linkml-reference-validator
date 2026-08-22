"""Tests for reference fetcher."""

import logging

import pytest
from unittest.mock import patch, MagicMock
from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ReferenceContent,
    FullTextLocation,
)
from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)


@pytest.fixture
def config(tmp_path):
    """Create a test configuration.

    Full-text enrichment is disabled so these legacy fetcher unit tests
    (ID parsing / caching / Crossref-vs-DataCite dispatch) stay isolated
    from the full-text provider chain, which has its own dedicated tests.
    """
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,  # No delay for tests
        fetch_full_text=False,
    )


@pytest.fixture
def fetcher(config):
    """Create a reference fetcher."""
    return ReferenceFetcher(config)


def test_fetcher_initialization(fetcher):
    """Test that fetcher initializes correctly."""
    assert fetcher.config is not None
    assert isinstance(fetcher._cache, dict)
    assert len(fetcher._cache) == 0


def test_parse_reference_id(fetcher):
    """Test parsing various reference ID formats."""
    assert fetcher._parse_reference_id("PMID:12345678") == ("PMID", "12345678")
    assert fetcher._parse_reference_id("PMID 12345678") == ("PMID", "12345678")
    assert fetcher._parse_reference_id("pmid:12345678") == ("PMID", "12345678")
    assert fetcher._parse_reference_id("12345678") == ("PMID", "12345678")
    assert fetcher._parse_reference_id("DOI:10.1234/test") == ("DOI", "10.1234/test")
    assert fetcher._parse_reference_id("file:./test.md") == ("file", "./test.md")
    assert fetcher._parse_reference_id("url:https://example.com") == (
        "url",
        "https://example.com",
    )


def test_parse_reference_id_with_prefix_map(tmp_path):
    """Test parsing with configurable prefix aliases."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        reference_prefix_map={
            "geo": "GEO",
            "NCBIGeo": "GEO",
            "bioproject": "BIOPROJECT",
        },
    )
    fetcher = ReferenceFetcher(config)

    assert fetcher._parse_reference_id("geo:GSE12345") == ("GEO", "GSE12345")
    assert fetcher._parse_reference_id("NCBIGeo:GSE12345") == ("GEO", "GSE12345")
    assert fetcher._parse_reference_id("bioproject:PRJNA12345") == (
        "BIOPROJECT",
        "PRJNA12345",
    )


def test_get_cache_path(fetcher):
    """Test cache path generation."""
    path = fetcher.get_cache_path("PMID:12345678")
    assert path.name == "PMID_12345678.md"

    path = fetcher.get_cache_path("DOI:10.1234/test")
    assert path.name == "DOI_10.1234_test.md"


def test_save_and_load_from_disk(fetcher, tmp_path):
    """Test saving and loading reference from disk."""
    ref = ReferenceContent(
        reference_id="PMID:12345678",
        title="Test Article",
        content="This is test content.",
        content_type="abstract_only",
        authors=["Smith J", "Doe A"],
        journal="Nature",
        year="2024",
        doi="10.1234/test",
    )

    fetcher._save_to_disk(ref)

    loaded = fetcher._load_from_disk("PMID:12345678")

    assert loaded is not None
    assert loaded.reference_id == "PMID:12345678"
    assert loaded.title == "Test Article"
    assert loaded.content == "This is test content."
    assert loaded.content_type == "abstract_only"
    assert loaded.authors == ["Smith J", "Doe A"]
    assert loaded.journal == "Nature"
    assert loaded.year == "2024"
    assert loaded.doi == "10.1234/test"


def test_load_from_disk_not_found(fetcher):
    """Test loading non-existent reference."""
    result = fetcher._load_from_disk("PMID:99999999")
    assert result is None


def test_private_cache_does_not_overlay_public_validation_cache(tmp_path):
    """Validation reads only the public cache when a private entry also exists."""
    public_dir = tmp_path / "public"
    private_dir = tmp_path / "private"
    public_fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=public_dir,
            private_cache_dir=private_dir,
            fetch_full_text=False,
        )
    )
    public_fetcher._save_to_disk(
        ReferenceContent(
            reference_id="DOI:10.1000/hit",
            doi="10.1000/hit",
            content="public abstract",
            content_type="abstract_only",
        )
    )
    public_fetcher._save_to_disk(
        ReferenceContent(
            reference_id="DOI:10.1000/hit",
            doi="10.1000/hit",
            content="closed full text",
            content_type="full_text",
            full_text_access_type="user_library",
        ),
        private=True,
    )

    loaded = public_fetcher._load_from_disk("DOI:10.1000/hit")

    assert loaded is not None
    assert loaded.content == "public abstract"
    assert loaded.full_text_access_type is None


def test_normal_fetch_never_writes_user_library_text_to_public_cache(tmp_path):
    """Validation skips private evidence and continues to a public provider."""

    class _PrivateProvider(FullTextProvider):
        @classmethod
        def name(cls):
            """Return the test provider name."""
            return "private_fetch"

        def locate(self, ids, config):
            """Return a private manuscript for the fixture DOI."""
            return FullTextLocation(
                text="closed manuscript text " * 30,
                format_hint="text",
                provider=self.name(),
                access_type="user_library",
                source_item_id="PRIVATE1",
            )

    class _PublicProvider(FullTextProvider):
        @classmethod
        def name(cls):
            """Return the test provider name."""
            return "public_fetch"

        def locate(self, ids, config):
            """Return public evidence for the fixture DOI."""
            return FullTextLocation(
                text="public full text " * 30,
                format_hint="text",
                provider=self.name(),
                access_type="open",
            )

    public_dir = tmp_path / "public"
    private_dir = tmp_path / "private"
    config = ReferenceValidationConfig(
        cache_dir=public_dir,
        private_cache_dir=private_dir,
        rate_limit_delay=0.0,
        full_text_providers=["private_fetch", "public_fetch"],
    )
    FullTextProviderRegistry.register(_PrivateProvider)
    FullTextProviderRegistry.register(_PublicProvider)
    fetcher = ReferenceFetcher(config)
    metadata = ReferenceContent(
        reference_id="DOI:10.1000/private",
        doi="10.1000/private",
        content="public abstract",
        content_type="abstract_only",
    )

    with patch(
        "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source"
    ) as get_source:
        get_source.return_value.return_value.fetch.return_value = metadata
        result = fetcher.fetch("DOI:10.1000/private")

    assert result is not None
    assert result.content == "public abstract\n\n" + "public full text " * 30
    assert "closed manuscript text" not in result.content
    assert result.full_text_access_type == "open"
    public_path = public_dir / "DOI_10.1000_private.md"
    assert public_path.exists()
    assert "public full text" in public_path.read_text(encoding="utf-8")
    private_path = private_dir / "DOI_10.1000_private.md"
    assert not private_path.exists()


def test_applying_private_enrichment_does_not_enter_validation_memory_cache(tmp_path):
    """A fetcher reused after private enrichment still returns public evidence."""
    public_dir = tmp_path / "public"
    private_dir = tmp_path / "private"
    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=public_dir,
            private_cache_dir=private_dir,
            fetch_full_text=False,
        )
    )
    public = ReferenceContent(
        reference_id="PMID:123",
        content="public abstract",
        content_type="abstract_only",
    )
    fetcher._save_to_disk(public)

    applied = fetcher.apply_full_text_location(
        public,
        FullTextLocation(
            text="closed manuscript text " * 30,
            format_hint="text",
            provider="zotero",
            access_type="user_library",
            source_item_id="PRIVATE1",
        ),
        "zotero",
        private=True,
    )

    assert applied is True
    loaded = fetcher.fetch("PMID:123")
    assert loaded is not None
    assert loaded.content == "public abstract"
    assert loaded.full_text_access_type is None


def test_private_location_forces_private_persistence_without_flag(tmp_path):
    """Private provenance is a safety floor even when a caller omits ``private``."""
    public_dir = tmp_path / "public"
    private_dir = tmp_path / "private"
    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=public_dir,
            private_cache_dir=private_dir,
            fetch_full_text=False,
        )
    )
    content = ReferenceContent(
        reference_id="PMID:123", content="abstract", content_type="abstract_only"
    )

    applied = fetcher.apply_full_text_location(
        content,
        FullTextLocation(
            text="closed manuscript text " * 30,
            format_hint="text",
            access_type="user_library",
        ),
        "zotero",
    )

    assert applied is True
    assert not (public_dir / "PMID_123.md").exists()
    assert (private_dir / "PMID_123.md").exists()


def test_iter_cached_references_streams_in_sorted_order(tmp_path):
    """Large caches are yielded one record at a time in deterministic order."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for filename, reference_id in (("B.md", "PMID:2"), ("A.md", "PMID:1")):
        (cache_dir / filename).write_text(
            f"---\nreference_id: {reference_id}\ncontent_type: abstract_only\n---\n",
            encoding="utf-8",
        )
    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(cache_dir=cache_dir, fetch_full_text=False)
    )

    references = fetcher.iter_cached_references()

    assert iter(references) is references
    assert [reference.reference_id for reference in references] == ["PMID:1", "PMID:2"]


def test_save_and_load_preprint_metadata(fetcher, tmp_path):
    """Preprint status round-trips through the disk cache frontmatter."""
    ref = ReferenceContent(
        reference_id="DOI:10.1101/2024.01.01.573333",
        title="A preprint",
        content="Early findings.",
        content_type="abstract_only",
        doi="10.1101/2024.01.01.573333",
        is_preprint=True,
        peer_review_status="preprint",
    )

    fetcher._save_to_disk(ref)
    loaded = fetcher._load_from_disk("DOI:10.1101/2024.01.01.573333")

    assert loaded is not None
    assert loaded.is_preprint is True
    assert loaded.peer_review_status == "preprint"


def test_save_and_load_publication_types(fetcher, tmp_path):
    """Publication types round-trip through the disk cache frontmatter."""
    ref = ReferenceContent(
        reference_id="PMID:12345678",
        title="An illustrative case",
        content="Case description.",
        content_type="abstract_only",
        publication_types=["Journal Article", "Case Reports"],
    )

    fetcher._save_to_disk(ref)
    loaded = fetcher._load_from_disk("PMID:12345678")

    assert loaded is not None
    assert loaded.publication_types == ["Journal Article", "Case Reports"]


def test_save_and_load_non_preprint_leaves_status_unset(fetcher, tmp_path):
    """A record with no preprint status must not gain one via the cache."""
    ref = ReferenceContent(
        reference_id="PMID:12345678",
        title="A paper",
        content="Results.",
        content_type="abstract_only",
    )

    fetcher._save_to_disk(ref)
    loaded = fetcher._load_from_disk("PMID:12345678")

    assert loaded is not None
    assert loaded.is_preprint is None
    assert loaded.peer_review_status is None


def test_save_and_load_with_brackets_in_title(fetcher, tmp_path):
    """Test saving and loading reference with brackets in title.

    This tests the fix for YAML parsing errors when titles contain
    brackets (e.g., [Cholera]. for articles in other languages).
    """
    ref = ReferenceContent(
        reference_id="PMID:30512613",
        title="[Cholera].",
        content="Article content about cholera.",
        content_type="abstract_only",
        authors=["García A", "López B"],
        journal="Rev Med",
        year="2018",
    )

    fetcher._save_to_disk(ref)

    loaded = fetcher._load_from_disk("PMID:30512613")

    assert loaded is not None
    assert loaded.reference_id == "PMID:30512613"
    assert loaded.title == "[Cholera]."
    assert loaded.content == "Article content about cholera."


def test_yaml_value_quoting(fetcher):
    """Test that special characters are properly quoted in YAML values."""
    # Brackets should be quoted
    assert fetcher._quote_yaml_value("[Cholera].") == '"[Cholera]."'
    assert fetcher._quote_yaml_value("{Test}") == '"{Test}"'


def test_save_and_load_extra_fields_captured(fetcher):
    """Test that extra_fields_captured in metadata is saved and loaded from cache."""
    ref = ReferenceContent(
        reference_id="clinicaltrials:NCT00000001",
        title="Test Trial",
        content="Summary text.",
        content_type="summary",
        metadata={"extra_fields_captured": ["eligibility", "outcomes"]},
    )

    fetcher._save_to_disk(ref)

    loaded = fetcher._load_from_disk("clinicaltrials:NCT00000001")

    assert loaded is not None
    assert loaded.metadata.get("extra_fields_captured") == ["eligibility", "outcomes"]

    # Colons should be quoted
    assert fetcher._quote_yaml_value("Title: Subtitle") == '"Title: Subtitle"'

    # Normal values should not be quoted
    assert fetcher._quote_yaml_value("Normal Title") == "Normal Title"

    # Boolean-like values should be quoted
    assert fetcher._quote_yaml_value("true") == '"true"'
    assert fetcher._quote_yaml_value("Yes") == '"Yes"'

    # Values with quotes inside should be escaped
    result = fetcher._quote_yaml_value('Title "quoted"')
    assert result == '"Title \\"quoted\\""'


def test_fetch_with_cache(fetcher):
    """Test that fetch uses cache."""
    cached_ref = ReferenceContent(
        reference_id="PMID:12345678",
        title="Cached Article",
        content="Cached content",
    )

    fetcher._cache["PMID:12345678"] = cached_ref

    result = fetcher.fetch("PMID:12345678")

    assert result is not None
    assert result.reference_id == "PMID:12345678"
    assert result.title == "Cached Article"


def test_fetch_unsupported_type(fetcher):
    """Test fetch with unsupported reference type."""
    result = fetcher.fetch("UNKNOWN:12345")
    assert result is None


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_fetch_doi_via_fetch_method(mock_get, fetcher):
    """Test that fetch() correctly routes DOI requests to DOISource."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "message": {
            "title": ["DOI Article via fetch()"],
            "author": [{"given": "Jane", "family": "Doe"}],
            "container-title": ["Science"],
            "published-print": {"date-parts": [[2023]]},
            "DOI": "10.5678/another.article",
        },
    }
    mock_get.return_value = mock_response

    result = fetcher.fetch("DOI:10.5678/another.article")

    assert result is not None
    assert result.reference_id == "DOI:10.5678/another.article"
    assert result.title == "DOI Article via fetch()"


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_save_and_load_doi_from_disk(mock_get, fetcher, tmp_path):
    """Test saving and loading DOI reference from disk cache."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "message": {
            "title": ["Cached DOI Article"],
            "author": [{"given": "Bob", "family": "Jones"}],
            "container-title": ["Cell"],
            "published-print": {"date-parts": [[2022, 6]]},
            "abstract": "Abstract content here.",
            "DOI": "10.9999/cached.doi",
        },
    }
    mock_get.return_value = mock_response

    # First fetch - this should save to disk
    result1 = fetcher.fetch("DOI:10.9999/cached.doi")
    assert result1 is not None

    # Clear memory cache
    fetcher._cache.clear()

    # Second fetch - should load from disk
    result2 = fetcher.fetch("DOI:10.9999/cached.doi")

    assert result2 is not None
    assert result2.reference_id == "DOI:10.9999/cached.doi"
    assert result2.title == "Cached DOI Article"
    assert result2.doi == "10.9999/cached.doi"


def test_fetch_local_file(fetcher, tmp_path):
    """Test fetching content from a local file."""
    # Create a test file
    test_file = tmp_path / "research.md"
    test_file.write_text("# Research Notes\n\nThis is my research content.")

    result = fetcher.fetch(f"file:{test_file}")

    assert result is not None
    assert "Research Notes" in result.title
    assert "This is my research content." in result.content
    assert result.content_type == "local_file"


@patch("linkml_reference_validator.etl.sources.url.ContentAcquirer")
def test_fetch_url(MockAcquirer, fetcher):
    """Test fetching content from a URL."""
    MockAcquirer.return_value.fetch_bytes.return_value = (
        b"<html><head><title>Web Page</title></head><body>Page content here.</body></html>",
        "text/html",
    )

    result = fetcher.fetch("url:https://example.com/page")

    assert result is not None
    assert result.title == "Web Page"
    assert "Page content here." in result.content
    assert result.content_type == "url"


@patch("linkml_reference_validator.etl.sources.url.ContentAcquirer")
def test_fetch_url_http_error(MockAcquirer, fetcher):
    """Test fetching URL that the acquirer rejects (non-200 / over cap)."""
    MockAcquirer.return_value.fetch_bytes.return_value = (None, None)

    result = fetcher.fetch("url:https://example.com/not-found")

    assert result is None


def test_url_cache_path(fetcher):
    """Test cache path generation for URLs."""
    path = fetcher.get_cache_path("url:https://example.com/book/chapter1")
    assert path.name == "url_https___example.com_book_chapter1.md"

    path = fetcher.get_cache_path("url:https://example.com/path?param=value")
    assert path.name == "url_https___example.com_path_param_value.md"


@patch("linkml_reference_validator.etl.sources.url.ContentAcquirer")
def test_save_and_load_url_from_disk(MockAcquirer, fetcher, tmp_path):
    """Test saving and loading URL reference from disk cache."""
    MockAcquirer.return_value.fetch_bytes.return_value = (
        b"""
    <html>
        <head><title>Cached URL Content</title></head>
        <body><p>This content should be cached.</p></body>
    </html>
    """,
        "text/html",
    )

    # First fetch - this should save to disk
    result1 = fetcher.fetch("url:https://example.com/cached")
    assert result1 is not None

    # Clear memory cache
    fetcher._cache.clear()

    # Second fetch - should load from disk without acquiring anything
    with patch(
        "linkml_reference_validator.etl.sources.url.ContentAcquirer"
    ) as mock_no_request:
        result2 = fetcher.fetch("url:https://example.com/cached")
        mock_no_request.return_value.fetch_bytes.assert_not_called()

    assert result2 is not None
    assert result2.reference_id == "url:https://example.com/cached"
    assert result2.title == "Cached URL Content"
    assert "This content should be cached" in result2.content


def test_parse_bare_https_url(fetcher):
    """Test that bare HTTPS URLs are correctly parsed as url: prefix.

    Bug fix: Previously https://example.com was parsed as prefix='HTTPS'
    with identifier='//example.com', which failed to match any source.
    """
    # Bare HTTPS URL should be parsed as url: prefix
    prefix, identifier = fetcher._parse_reference_id("https://example.com")
    assert prefix == "url"
    assert identifier == "https://example.com"

    # Bare HTTP URL should also work
    prefix, identifier = fetcher._parse_reference_id("http://example.com/path")
    assert prefix == "url"
    assert identifier == "http://example.com/path"

    # doi.org URL should also be treated as url:
    prefix, identifier = fetcher._parse_reference_id(
        "https://doi.org/10.5281/zenodo.123"
    )
    assert prefix == "url"
    assert identifier == "https://doi.org/10.5281/zenodo.123"

    # Explicit url: prefix should still work
    prefix, identifier = fetcher._parse_reference_id("url:https://example.com")
    assert prefix == "url"
    assert identifier == "https://example.com"


def test_normalize_bare_https_url(fetcher):
    """Test that normalize_reference_id handles bare HTTPS URLs."""
    assert (
        fetcher.normalize_reference_id("https://example.com")
        == "url:https://example.com"
    )
    assert (
        fetcher.normalize_reference_id("http://example.com/path")
        == "url:http://example.com/path"
    )
    assert (
        fetcher.normalize_reference_id("https://doi.org/10.5281/zenodo.123")
        == "url:https://doi.org/10.5281/zenodo.123"
    )


@patch("linkml_reference_validator.etl.sources.url.ContentAcquirer")
def test_fetch_bare_https_url(MockAcquirer, fetcher):
    """Test that bare HTTPS URLs are fetched correctly."""
    MockAcquirer.return_value.fetch_bytes.return_value = (
        b"<html><head><title>Bare URL Test</title></head><body>Content from bare URL.</body></html>",
        "text/html",
    )

    # Fetch using bare URL (no url: prefix)
    result = fetcher.fetch("https://example.com/page")

    assert result is not None
    assert result.title == "Bare URL Test"
    assert "Content from bare URL" in result.content
    assert result.reference_id == "url:https://example.com/page"


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_fetch_zenodo_doi_via_datacite(mock_get, fetcher):
    """Test that Zenodo DOIs are fetched via DataCite when Crossref returns 404.

    Zenodo DOIs (10.5281/zenodo.*) are registered with DataCite, not Crossref.
    The DOI source should fall back to DataCite when Crossref returns 404.
    """
    # Set up mock responses: Crossref 404, then DataCite success, then Zenodo files
    crossref_response = MagicMock()
    crossref_response.status_code = 404

    datacite_response = MagicMock()
    datacite_response.status_code = 200
    datacite_response.json.return_value = {
        "data": {
            "attributes": {
                "doi": "10.5281/zenodo.17993529",
                "titles": [{"title": "Gene Ontology Curators AI Workshop (Part 1)"}],
                "creators": [
                    {
                        "name": "Mungall, Christopher",
                        "givenName": "Christopher",
                        "familyName": "Mungall",
                    }
                ],
                "publicationYear": 2025,
                "publisher": "Zenodo",
                "descriptions": [
                    {
                        "description": "Workshop aims to equip curators with AI skills.",
                        "descriptionType": "Abstract",
                    }
                ],
            }
        }
    }

    # Zenodo API returns file metadata (or 404 if no files)
    zenodo_response = MagicMock()
    zenodo_response.status_code = 200
    zenodo_response.json.return_value = {"files": []}  # Empty files list

    # Order: Crossref (404), DataCite (success), Zenodo (success)
    mock_get.side_effect = [crossref_response, datacite_response, zenodo_response]

    result = fetcher.fetch("DOI:10.5281/zenodo.17993529")

    assert result is not None
    assert result.reference_id == "DOI:10.5281/zenodo.17993529"
    assert "Gene Ontology" in result.title
    assert result.year == "2025"
    assert result.journal == "Zenodo"
    assert "Christopher" in result.authors[0] or "Mungall" in result.authors[0]
    assert "AI skills" in result.content or "Workshop" in result.content


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_fetch_doi_crossref_success_no_datacite_call(mock_get, fetcher):
    """Test that when Crossref succeeds, DataCite is not called."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "message": {
            "title": ["Regular Crossref Article"],
            "author": [{"given": "Jane", "family": "Doe"}],
            "container-title": ["Nature"],
            "published-print": {"date-parts": [[2024]]},
        },
    }
    mock_get.return_value = mock_response

    result = fetcher.fetch("DOI:10.1038/s41586-024-12345")

    assert result is not None
    assert result.title == "Regular Crossref Article"
    # Crossref should only be called once
    assert mock_get.call_count == 1
    assert "crossref.org" in mock_get.call_args[0][0]


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_fetch_doi_both_fail(mock_get, fetcher):
    """Test that when both Crossref and DataCite fail, None is returned."""
    crossref_response = MagicMock()
    crossref_response.status_code = 404

    datacite_response = MagicMock()
    datacite_response.status_code = 404

    mock_get.side_effect = [crossref_response, datacite_response]

    result = fetcher.fetch("DOI:10.9999/nonexistent.doi")

    assert result is None
    # Both APIs should be called
    assert mock_get.call_count == 2


# === Supplementary Files Tests ===


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_fetch_zenodo_doi_with_supplementary_files(mock_get, fetcher):
    """Test that Zenodo DOIs include supplementary file metadata.

    Zenodo DOIs (10.5281/zenodo.*) should fetch file metadata from
    the Zenodo API and populate supplementary_files.
    """
    # Crossref returns 404 (Zenodo DOIs aren't in Crossref)
    crossref_response = MagicMock()
    crossref_response.status_code = 404

    # DataCite returns basic metadata
    datacite_response = MagicMock()
    datacite_response.status_code = 200
    datacite_response.json.return_value = {
        "data": {
            "attributes": {
                "doi": "10.5281/zenodo.7961621",
                "titles": [{"title": "Workshop Presentation"}],
                "creators": [{"name": "Mungall, Christopher"}],
                "publicationYear": 2023,
                "publisher": "Zenodo",
                "descriptions": [],
            }
        }
    }

    # Zenodo API returns file metadata
    zenodo_response = MagicMock()
    zenodo_response.status_code = 200
    zenodo_response.json.return_value = {
        "files": [
            {
                "key": "Dickinson_Varenna2022.pdf",
                "size": 1975995,
                "checksum": "md5:88c66d378d886fea4969949c5877802f",
                "links": {
                    "self": "https://zenodo.org/api/records/7961621/files/Dickinson_Varenna2022.pdf/content"
                },
            },
            {
                "key": "supplementary_data.csv",
                "size": 12345,
                "checksum": "md5:abc123def456",
                "links": {
                    "self": "https://zenodo.org/api/records/7961621/files/supplementary_data.csv/content"
                },
            },
        ]
    }

    # Order: Crossref (404), DataCite (success), Zenodo (success)
    mock_get.side_effect = [crossref_response, datacite_response, zenodo_response]

    result = fetcher.fetch("DOI:10.5281/zenodo.7961621")

    assert result is not None
    assert result.reference_id == "DOI:10.5281/zenodo.7961621"
    assert result.title == "Workshop Presentation"

    # Check supplementary files
    assert result.supplementary_files is not None
    assert len(result.supplementary_files) == 2

    # Check first file
    pdf_file = result.supplementary_files[0]
    assert pdf_file.filename == "Dickinson_Varenna2022.pdf"
    assert pdf_file.size_bytes == 1975995
    assert pdf_file.checksum == "md5:88c66d378d886fea4969949c5877802f"
    assert "zenodo.org" in pdf_file.download_url
    assert pdf_file.local_path is None  # Not downloaded by default

    # Check second file
    csv_file = result.supplementary_files[1]
    assert csv_file.filename == "supplementary_data.csv"
    assert csv_file.size_bytes == 12345


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_fetch_non_zenodo_doi_no_supplementary_files(mock_get, fetcher):
    """Test that non-Zenodo DOIs (regular Crossref) don't have supplementary files."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "status": "ok",
        "message": {
            "title": ["Regular Journal Article"],
            "author": [{"given": "Jane", "family": "Doe"}],
            "container-title": ["Nature"],
            "published-print": {"date-parts": [[2024]]},
        },
    }
    mock_get.return_value = mock_response

    result = fetcher.fetch("DOI:10.1038/s41586-024-12345")

    assert result is not None
    assert result.title == "Regular Journal Article"
    # Regular DOIs don't have supplementary files from Crossref
    assert result.supplementary_files is None


def test_detect_repository():
    """Test repository detection from DOI prefix."""
    from linkml_reference_validator.etl.sources.doi import DOISource

    source = DOISource()

    # Zenodo DOIs
    assert source._detect_repository("10.5281/zenodo.7961621") == "zenodo"
    assert source._detect_repository("10.5281/zenodo.123") == "zenodo"

    # Non-Zenodo DOIs
    assert source._detect_repository("10.1038/s41586-024-12345") is None
    assert source._detect_repository("10.1234/test") is None

    # Edge cases
    assert (
        source._detect_repository("10.5281/other.123") is None
    )  # 10.5281 but not zenodo


def test_extract_zenodo_record_id():
    """Test extracting Zenodo record ID from DOI."""
    from linkml_reference_validator.etl.sources.doi import DOISource

    source = DOISource()

    assert source._extract_zenodo_record_id("10.5281/zenodo.7961621") == "7961621"
    assert source._extract_zenodo_record_id("10.5281/zenodo.123") == "123"
    assert source._extract_zenodo_record_id("10.1038/s41586-024-12345") is None


# === Supplementary Files Cache Serialization Tests ===


def test_save_and_load_supplementary_files(fetcher, tmp_path):
    """Test saving and loading reference with supplementary files to/from cache."""
    from linkml_reference_validator.models import SupplementaryFile

    ref = ReferenceContent(
        reference_id="DOI:10.5281/zenodo.7961621",
        title="Workshop Presentation",
        content="Abstract text here.",
        content_type="abstract_only",
        authors=["Mungall, Christopher"],
        journal="Zenodo",
        year="2023",
        doi="10.5281/zenodo.7961621",
        supplementary_files=[
            SupplementaryFile(
                filename="Dickinson_Varenna2022.pdf",
                download_url="https://zenodo.org/api/records/7961621/files/Dickinson_Varenna2022.pdf/content",
                content_type="application/pdf",
                size_bytes=1975995,
                checksum="md5:88c66d378d886fea4969949c5877802f",
            ),
            SupplementaryFile(
                filename="data.csv",
                download_url="https://zenodo.org/api/records/7961621/files/data.csv/content",
                size_bytes=12345,
            ),
        ],
    )

    # Save to disk
    fetcher._save_to_disk(ref)

    # Clear memory cache
    fetcher._cache.clear()

    # Load from disk
    loaded = fetcher._load_from_disk("DOI:10.5281/zenodo.7961621")

    assert loaded is not None
    assert loaded.reference_id == "DOI:10.5281/zenodo.7961621"
    assert loaded.title == "Workshop Presentation"

    # Check supplementary files were preserved
    assert loaded.supplementary_files is not None
    assert len(loaded.supplementary_files) == 2

    pdf_file = loaded.supplementary_files[0]
    assert pdf_file.filename == "Dickinson_Varenna2022.pdf"
    assert pdf_file.size_bytes == 1975995
    assert pdf_file.checksum == "md5:88c66d378d886fea4969949c5877802f"
    assert "zenodo.org" in pdf_file.download_url

    csv_file = loaded.supplementary_files[1]
    assert csv_file.filename == "data.csv"
    assert csv_file.size_bytes == 12345


def test_save_and_load_no_supplementary_files(fetcher, tmp_path):
    """Test that references without supplementary files serialize correctly."""
    ref = ReferenceContent(
        reference_id="PMID:12345678",
        title="Regular Article",
        content="Abstract text.",
        content_type="abstract_only",
        supplementary_files=None,
    )

    fetcher._save_to_disk(ref)
    fetcher._cache.clear()

    loaded = fetcher._load_from_disk("PMID:12345678")

    assert loaded is not None
    assert loaded.supplementary_files is None


def test_save_and_load_empty_supplementary_files(fetcher, tmp_path):
    """Test that empty supplementary files list serializes correctly."""
    ref = ReferenceContent(
        reference_id="DOI:10.1234/test",
        title="Article",
        supplementary_files=[],  # Empty list
    )

    fetcher._save_to_disk(ref)
    fetcher._cache.clear()

    loaded = fetcher._load_from_disk("DOI:10.1234/test")

    assert loaded is not None
    # Empty list should be treated as None or empty
    assert loaded.supplementary_files is None or loaded.supplementary_files == []


def test_enrich_with_full_text_uses_first_successful_provider(tmp_path):
    from linkml_reference_validator.models import (
        ReferenceContent,
        ReferenceValidationConfig,
        FullTextLocation,
    )
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.etl.fulltext.base import FullTextProvider, FullTextProviderRegistry

    class _TextProvider(FullTextProvider):
        @classmethod
        def name(cls):
            return "fake_text"

        def locate(self, ids, config):
            return FullTextLocation(text="X" * 600, format_hint="xml", provider="fake_text", oa_status="green")

    FullTextProviderRegistry.register(_TextProvider)

    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        full_text_providers=["fake_text"],
    )
    fetcher = ReferenceFetcher(config)

    content = ReferenceContent(
        reference_id="DOI:10.1/x", doi="10.1/x", content="abstract here", content_type="abstract_only"
    )
    enriched = fetcher._enrich_with_full_text(content)
    assert enriched.content_type == "full_text_xml"
    assert "X" * 600 in enriched.content
    assert enriched.full_text_provider == "fake_text"
    assert enriched.oa_status == "green"


def test_enrich_skips_when_already_full_text(tmp_path):
    from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    fetcher = ReferenceFetcher(config)
    content = ReferenceContent(
        reference_id="PMID:1", content="lots of full text", content_type="full_text_xml"
    )
    assert fetcher.needs_full_text(content) is False


def test_enrich_downloads_and_extracts_pdf(tmp_path):
    from linkml_reference_validator.models import (
        ReferenceContent,
        ReferenceValidationConfig,
        FullTextLocation,
    )
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.etl.fulltext.base import FullTextProvider, FullTextProviderRegistry
    from unittest.mock import patch

    class _PdfProvider(FullTextProvider):
        @classmethod
        def name(cls):
            return "fake_pdf"

        def locate(self, ids, config):
            return FullTextLocation(url="https://x/y.pdf", format_hint="pdf", provider="fake_pdf")

    FullTextProviderRegistry.register(_PdfProvider)

    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        full_text_providers=["fake_pdf"],
    )
    fetcher = ReferenceFetcher(config)
    content = ReferenceContent(
        reference_id="DOI:10.1/x", doi="10.1/x", content="abstract", content_type="abstract_only"
    )

    # The fetcher builds (and reuses) a single PDFExtractor at init; patch its
    # extract so we exercise the download/sniff/enrich path without real pypdf.
    with patch.object(fetcher._acquirer, "fetch_bytes", return_value=(b"%PDF-fake", "application/pdf")), \
         patch.object(fetcher._pdf_extractor, "extract", return_value="extracted pdf text " * 50):
        enriched = fetcher._enrich_with_full_text(content)

    assert enriched.content_type == "full_text_pdf"
    assert "extracted pdf text" in enriched.content
    assert enriched.full_text_provider == "fake_pdf"


def test_provenance_round_trips_through_cache(tmp_path):
    from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    fetcher = ReferenceFetcher(config)

    content = ReferenceContent(
        reference_id="DOI:10.1/x",
        title="Paper",
        content="full body text",
        content_type="full_text_pdf",
        full_text_provider="unpaywall",
        full_text_url="https://oa/x.pdf",
        oa_status="gold",
        license="cc-by",
        local_pdf_path="files/DOI_10.1_x.pdf",
        full_text_access_type="user_library",
        full_text_source_item_id="ATTACHMENT1",
    )
    fetcher._save_to_disk(content)
    loaded = fetcher._load_from_disk("DOI:10.1/x")

    assert loaded.content_type == "full_text_pdf"
    assert loaded.full_text_provider == "unpaywall"
    assert loaded.full_text_url == "https://oa/x.pdf"
    assert loaded.oa_status == "gold"
    assert loaded.license == "cc-by"
    assert loaded.local_pdf_path == "files/DOI_10.1_x.pdf"
    assert loaded.full_text_access_type == "user_library"
    assert loaded.full_text_source_item_id == "ATTACHMENT1"


def test_fetcher_registers_custom_full_text_providers(tmp_path):
    from linkml_reference_validator.models import ReferenceValidationConfig
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry

    yaml_file = tmp_path / ".linkml-reference-validator-fulltext.yaml"
    yaml_file.write_text(
        "full_text_providers:\n"
        "  custom_at_init:\n"
        "    url_template: https://api.example.org/ft/{doi}\n"
        "    location_field: $.pdf_url\n"
    )
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", rate_limit_delay=0.0, full_text_providers_file=yaml_file
    )
    ReferenceFetcher(config)
    assert FullTextProviderRegistry.get("custom_at_init") is not None


# ---------------------------------------------------------------------------
# Full-text chain: transient failures must not be cached as permanent absence
# (PR #48 review, issue #1)
# ---------------------------------------------------------------------------


class _ScriptedProvider(FullTextProvider):
    """A provider whose locate() replays a scripted list of behaviours.

    Each call pops the next behaviour: an Exception is raised (simulating a
    provider/API outage), anything else is returned (a FullTextLocation or None).
    """

    def __init__(self, behaviours):
        self._behaviours = list(behaviours)
        self.calls = 0

    @classmethod
    def name(cls):
        return "scripted"

    def locate(self, ids, config):
        self.calls += 1
        behaviour = self._behaviours.pop(0) if self._behaviours else None
        if isinstance(behaviour, Exception):
            raise behaviour
        return behaviour


def _full_text_config(tmp_path):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        fetch_full_text=True,
        full_text_providers=["scripted"],
    )


def test_transient_full_text_failure_is_retried_on_next_run(tmp_path):
    """A provider outage on one run must not bake in 'abstract_only' forever."""
    provider = _ScriptedProvider(
        [
            RuntimeError("PMC outage"),
            FullTextLocation(text="F" * 600, format_hint="text", provider="scripted"),
        ]
    )
    FullTextProviderRegistry.register_instance("scripted", provider)
    config = _full_text_config(tmp_path)

    # Seed the disk cache with an abstract-only record (as a prior fetch would have).
    seed = ReferenceContent(
        reference_id="DOI:10.1/x", content="abstract", content_type="abstract_only"
    )
    ReferenceFetcher(config)._save_to_disk(seed)

    # Run 1 (fresh process): provider is down -> stays abstract_only, NOT attempted.
    r1 = ReferenceFetcher(config).fetch("DOI:10.1/x")
    assert r1.content_type == "abstract_only"
    assert r1.full_text_attempted is False

    # Run 2 (fresh process): provider recovers -> full text is fetched.
    r2 = ReferenceFetcher(config).fetch("DOI:10.1/x")
    assert "F" * 600 in (r2.content or "")
    assert r2.content_type.startswith("full_text")


def test_clean_exhaustion_marks_attempted_and_is_not_retried(tmp_path):
    """When the chain runs cleanly but finds nothing, record it and don't re-run."""
    provider = _ScriptedProvider([None, None])
    FullTextProviderRegistry.register_instance("scripted", provider)
    config = _full_text_config(tmp_path)

    seed = ReferenceContent(
        reference_id="DOI:10.1/y", content="abstract", content_type="abstract_only"
    )
    ReferenceFetcher(config)._save_to_disk(seed)

    r1 = ReferenceFetcher(config).fetch("DOI:10.1/y")
    assert r1.full_text_attempted is True
    assert provider.calls == 1

    # Next run must NOT re-run the chain (attempted=True persisted to disk).
    r2 = ReferenceFetcher(config).fetch("DOI:10.1/y")
    assert r2.full_text_attempted is True
    assert provider.calls == 1


def test_full_text_attempted_round_trips_through_disk_cache(tmp_path):
    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    fetcher = ReferenceFetcher(config)
    ref = ReferenceContent(
        reference_id="DOI:10.1/z",
        content="abstract",
        content_type="abstract_only",
        full_text_attempted=True,
    )
    fetcher._save_to_disk(ref)
    loaded = fetcher._load_from_disk("DOI:10.1/z")
    assert loaded.full_text_attempted is True


def test_materialize_trusts_sniffed_format_over_hint(tmp_path):
    """A 'pdf' hint pointing at an HTML landing page must route to HTML, not pypdf."""
    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    fetcher = ReferenceFetcher(config)
    html_landing = b"<!DOCTYPE html><html><body>" + b"text " * 200 + b"</body></html>"
    with patch.object(
        fetcher._acquirer, "fetch_bytes", return_value=(html_landing, "application/pdf")
    ):
        loc = FullTextLocation(url="https://x/paper", format_hint="pdf")
        text, fmt, pdf_bytes, error = fetcher._materialize(loc)
    assert fmt == "html"
    assert pdf_bytes is None
    assert error is False


# ============================================================================
# Cache invalidation on extractor changes
#
# Fixing an extractor does not rewrite what it already cached. Entries written
# before the stub-detection and markup-welding fixes hold text those bugs
# produced - an 8.7 KB placeholder labelled as full text, or gene symbols
# welded to their punctuation - and are served from disk forever, so correct
# snippets keep being rejected with nothing in the output to explain why.
# See https://github.com/monarch-initiative/genesets/issues/10
# ============================================================================


def _cached_text(fetcher, reference_id):
    return fetcher.get_cache_path(reference_id).read_text(encoding="utf-8")


def _unstamp(fetcher, reference_id):
    """Rewrite a cache entry as an older extractor would have left it."""
    path = fetcher.get_cache_path(reference_id)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"extractor_version: {EXTRACTOR_CACHE_VERSION}\n", ""
        ),
        encoding="utf-8",
    )


def _source_returning(mocker, content):
    """Patch the registry so every reference resolves to a source yielding ``content``."""
    return mocker.patch.object(
        ReferenceSourceRegistry,
        "get_source",
        return_value=mocker.Mock(
            return_value=mocker.Mock(fetch=mocker.Mock(return_value=content))
        ),
    )


def test_saved_entry_carries_the_extractor_version(fetcher):
    """Every entry records which extraction it came from."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Body text.")
    )

    assert f"extractor_version: {EXTRACTOR_CACHE_VERSION}" in _cached_text(
        fetcher, "PMID:1"
    )


def test_entry_from_the_current_extractor_is_served(fetcher):
    """The ordinary case: a current entry still comes back from disk."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Body text.")
    )

    loaded = fetcher._load_from_disk("PMID:1")

    assert loaded is not None
    assert loaded.content == "Body text."


def test_entry_without_a_version_is_not_served(fetcher):
    """Entries written before the stamp existed are the poisoned ones."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Stale body text.")
    )
    _unstamp(fetcher, "PMID:1")

    assert fetcher._load_from_disk("PMID:1") is None


def test_entry_from_an_older_extractor_is_not_served(fetcher):
    """A stamp older than the current one is equally stale."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Stale body text.")
    )
    path = fetcher.get_cache_path("PMID:1")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"extractor_version: {EXTRACTOR_CACHE_VERSION}",
            f"extractor_version: {EXTRACTOR_CACHE_VERSION - 1}",
        ),
        encoding="utf-8",
    )

    assert fetcher._load_from_disk("PMID:1") is None


def test_entry_from_a_newer_extractor_is_served(fetcher):
    """A newer stamp is not stale - it just means an older tool is reading it."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Body text.")
    )
    path = fetcher.get_cache_path("PMID:1")
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"extractor_version: {EXTRACTOR_CACHE_VERSION}",
            f"extractor_version: {EXTRACTOR_CACHE_VERSION + 1}",
        ),
        encoding="utf-8",
    )

    assert fetcher._load_from_disk("PMID:1") is not None


def test_legacy_text_entry_is_still_served(fetcher):
    """The pre-Markdown format is deliberately exempt from the version check.

    Nothing has written it for a long time, so such entries are as likely to
    be hand-maintained as tool-written, and they are not what the extractor
    bugs produced - those wrote Markdown. Invalidating them would discard
    someone's data to fix a problem they do not have.
    """
    legacy = fetcher.get_cache_path("PMID:1").with_suffix(".txt")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("Body text from a legacy cache entry.", encoding="utf-8")

    loaded = fetcher._load_from_disk("PMID:1")

    assert loaded is not None
    assert "legacy cache entry" in loaded.content


def test_entry_whose_id_contains_a_horizontal_rule_is_not_perpetually_stale(fetcher):
    """Frontmatter ends at a line that is ``---``, not at ``---`` inside a value.

    A URL reference containing ``---`` would otherwise truncate the searched
    block, hiding the stamp - so the entry would read as unstamped, be
    re-fetched, be rewritten with the same id, and read as unstamped again on
    every single run.
    """
    reference_id = "url:https://example.com/a---b"
    fetcher._save_to_disk(
        ReferenceContent(reference_id=reference_id, content="Body text.")
    )

    assert not fetcher._is_stale_cache_entry(_cached_text(fetcher, reference_id))

    loaded = fetcher._load_from_disk(reference_id)
    assert loaded is not None
    assert loaded.reference_id == reference_id
    assert loaded.content == "Body text."


def test_horizontal_rule_in_a_title_does_not_truncate_the_frontmatter(fetcher):
    """The same holds for any other value the source supplies."""
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id="PMID:1",
            title="Before --- after",
            content="Body text.",
            journal="Nature",
        )
    )

    loaded = fetcher._load_from_disk("PMID:1")

    assert loaded is not None
    assert loaded.journal == "Nature"


def test_legacy_text_entry_is_exempt_even_if_it_starts_with_a_rule(fetcher):
    """The exemption follows the file that was read, not what its text looks like.

    A ``.txt`` entry whose first line happens to be ``---`` has no stamp to find,
    so routing it by content rather than by which branch opened it would discard
    it - the exact "someone's data for a problem they do not have" the exemption
    exists to prevent.
    """
    legacy = fetcher.get_cache_path("PMID:1").with_suffix(".txt")
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("---\nBody text from a legacy cache entry.", encoding="utf-8")

    loaded = fetcher._load_from_disk("PMID:1")

    assert loaded is not None
    assert "legacy cache entry" in loaded.content


def test_stale_entry_is_refetched_and_restamped(fetcher, mocker):
    """A stale entry is replaced rather than merely ignored."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Stale body text.")
    )
    _unstamp(fetcher, "PMID:1")

    _source_returning(
        mocker, ReferenceContent(reference_id="PMID:1", content="Freshly fetched text.")
    )

    result = fetcher.fetch("PMID:1")

    assert result is not None
    assert result.content == "Freshly fetched text."
    assert f"extractor_version: {EXTRACTOR_CACHE_VERSION}" in _cached_text(
        fetcher, "PMID:1"
    )


# ---------------------------------------------------------------------------
# Falling back to a stale entry when the source cannot be reached.
#
# Treating a stale entry as absent is only safe while the source can supply a
# replacement. Offline, during an NCBI outage, or for a record since withdrawn,
# "this text is out of date" must not become "this reference does not exist" -
# otherwise the first offline run after upgrading reports every reference as
# not found.
# ---------------------------------------------------------------------------


def test_stale_entry_is_served_when_the_source_cannot_be_reached(fetcher, mocker):
    """An unreachable source falls back to the out-of-date copy on disk."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Stale body text.")
    )
    _unstamp(fetcher, "PMID:1")

    _source_returning(mocker, None)

    result = fetcher.fetch("PMID:1")

    assert result is not None
    assert result.content == "Stale body text."


def test_stale_fallback_warns_that_the_text_is_out_of_date(fetcher, mocker, caplog):
    """Serving known-suspect text is a warning, not a silent success."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Stale body text.")
    )
    _unstamp(fetcher, "PMID:1")
    _source_returning(mocker, None)

    with caplog.at_level(logging.WARNING):
        fetcher.fetch("PMID:1")

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("PMID:1" in message for message in warnings)
    assert any("older extractor" in message for message in warnings)


def test_stale_fallback_is_not_written_back_to_disk(fetcher, mocker):
    """The entry stays stale, so the next reachable run still refreshes it."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Stale body text.")
    )
    _unstamp(fetcher, "PMID:1")
    _source_returning(mocker, None)

    fetcher.fetch("PMID:1")

    assert "extractor_version:" not in _cached_text(fetcher, "PMID:1")


def test_stale_entry_is_served_when_no_source_handles_the_id(fetcher, mocker):
    """An unroutable ID is the same problem: the cached copy beats nothing."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Stale body text.")
    )
    _unstamp(fetcher, "PMID:1")

    mocker.patch.object(ReferenceSourceRegistry, "get_source", return_value=None)

    result = fetcher.fetch("PMID:1")

    assert result is not None
    assert result.content == "Stale body text."


def test_force_refresh_does_not_fall_back_to_the_stale_entry(fetcher, mocker):
    """An explicit refresh that fails must report failure, not paper over it."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", content="Stale body text.")
    )
    _unstamp(fetcher, "PMID:1")
    _source_returning(mocker, None)

    assert fetcher.fetch("PMID:1", force_refresh=True) is None


def test_missing_entry_still_returns_none_when_the_source_fails(fetcher, mocker):
    """The fallback invents nothing: no cache entry means no result."""
    _source_returning(mocker, None)

    assert fetcher.fetch("PMID:1") is None


def test_cache_export_still_reads_unstamped_entries(fetcher):
    """Export and enrichment must not lose entries the validator re-fetches.

    iter_cached_references is what `cache export` and the Zotero enrichment
    walk; treating an unstamped entry as absent there would silently drop it
    from an export rather than just re-fetching it for validation.
    """
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:1", title="Kept", content="Body.")
    )
    _unstamp(fetcher, "PMID:1")

    assert [r.title for r in fetcher.iter_cached_references()] == ["Kept"]
