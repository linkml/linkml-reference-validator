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
    path = fetcher.get_cache_path("url:https://example.com/book/chapter1")
    assert path.name == "url_https___example.com_book_chapter1.md"

    path = fetcher.get_cache_path("url:https://example.com/path?param=value")
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
    prefix, identifier = fetcher._parse_reference_id("https://doi.org/10.5281/zenodo.123")
    assert prefix == "url"
    assert identifier == "https://doi.org/10.5281/zenodo.123"

    # Explicit url: prefix should still work
    prefix, identifier = fetcher._parse_reference_id("url:https://example.com")
    assert prefix == "url"
    assert identifier == "https://example.com"


def test_normalize_bare_https_url(fetcher):
    """Test that normalize_reference_id handles bare HTTPS URLs."""
    assert fetcher.normalize_reference_id("https://example.com") == "url:https://example.com"
    assert fetcher.normalize_reference_id("http://example.com/path") == "url:http://example.com/path"
    assert fetcher.normalize_reference_id("https://doi.org/10.5281/zenodo.123") == "url:https://doi.org/10.5281/zenodo.123"


@patch("linkml_reference_validator.etl.sources.url.requests.get")
def test_fetch_bare_https_url(mock_get, fetcher):
    """Test that bare HTTPS URLs are fetched correctly."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.text = "<html><head><title>Bare URL Test</title></head><body>Content from bare URL.</body></html>"
    mock_response.headers = {"content-type": "text/html"}
    mock_get.return_value = mock_response

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
    assert source._detect_repository("10.5281/other.123") is None  # 10.5281 but not zenodo


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
