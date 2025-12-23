"""Tests for reference fetcher."""

import pytest
from unittest.mock import patch, MagicMock
from linkml_reference_validator.models import ReferenceValidationConfig, ReferenceContent
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher


@pytest.fixture
def config(tmp_path):
    """Create a test configuration."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,  # No delay for tests
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
    assert fetcher._parse_reference_id("url:https://example.com") == ("url", "https://example.com")


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
    assert fetcher._parse_reference_id("bioproject:PRJNA12345") == ("BIOPROJECT", "PRJNA12345")


def test_get_cache_path(fetcher):
    """Test cache path generation."""
    path = fetcher._get_cache_path("PMID:12345678")
    assert path.name == "PMID_12345678.md"

    path = fetcher._get_cache_path("DOI:10.1234/test")
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


@patch("linkml_reference_validator.etl.sources.url.requests.get")
def test_fetch_url(mock_get, fetcher):
    """Test fetching content from a URL."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><head><title>Web Page</title></head><body>Page content here.</body></html>"
    mock_response.headers = {"content-type": "text/html"}
    mock_get.return_value = mock_response

    result = fetcher.fetch("url:https://example.com/page")

    assert result is not None
    assert result.title == "Web Page"
    assert "Page content here." in result.content
    assert result.content_type == "url"


@patch("linkml_reference_validator.etl.sources.url.requests.get")
def test_fetch_url_http_error(mock_get, fetcher):
    """Test fetching URL that returns HTTP error."""
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    result = fetcher.fetch("url:https://example.com/not-found")

    assert result is None


def test_url_cache_path(fetcher):
    """Test cache path generation for URLs."""
    path = fetcher._get_cache_path("url:https://example.com/book/chapter1")
    assert path.name == "url_https___example.com_book_chapter1.md"

    path = fetcher._get_cache_path("url:https://example.com/path?param=value")
    assert path.name == "url_https___example.com_path_param_value.md"


@patch("linkml_reference_validator.etl.sources.url.requests.get")
def test_save_and_load_url_from_disk(mock_get, fetcher, tmp_path):
    """Test saving and loading URL reference from disk cache."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = """
    <html>
        <head><title>Cached URL Content</title></head>
        <body><p>This content should be cached.</p></body>
    </html>
    """
    mock_response.headers = {"content-type": "text/html"}
    mock_get.return_value = mock_response

    # First fetch - this should save to disk
    result1 = fetcher.fetch("url:https://example.com/cached")
    assert result1 is not None

    # Clear memory cache
    fetcher._cache.clear()

    # Second fetch - should load from disk without making HTTP request
    with patch("linkml_reference_validator.etl.sources.url.requests.get") as mock_no_request:
        result2 = fetcher.fetch("url:https://example.com/cached")
        mock_no_request.assert_not_called()

    assert result2 is not None
    assert result2.reference_id == "url:https://example.com/cached"
    assert result2.title == "Cached URL Content"
    assert "This content should be cached" in result2.content
