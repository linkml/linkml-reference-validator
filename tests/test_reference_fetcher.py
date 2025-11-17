"""Tests for reference fetcher."""

import pytest
from unittest.mock import Mock, patch, MagicMock
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


def test_parse_authors(fetcher):
    """Test author list parsing."""
    authors = fetcher._parse_authors(["Smith J", "Doe A", "Johnson K"])
    assert authors == ["Smith J", "Doe A", "Johnson K"]

    authors = fetcher._parse_authors([])
    assert authors == []


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


@patch("linkml_reference_validator.etl.reference_fetcher.Entrez")
def test_fetch_pmid_mock(mock_entrez, fetcher):
    """Test fetching PMID with mocked Entrez."""
    mock_handle = MagicMock()
    mock_handle.read.return_value = [
        {
            "Title": "Test Article",
            "AuthorList": ["Smith J", "Doe A"],
            "Source": "Nature",
            "PubDate": "2024 Jan",
            "DOI": "10.1234/test",
        }
    ]
    mock_handle.__enter__ = Mock(return_value=mock_handle)
    mock_handle.__exit__ = Mock(return_value=False)

    mock_entrez.read.return_value = [
        {
            "Title": "Test Article",
            "AuthorList": ["Smith J", "Doe A"],
            "Source": "Nature",
            "PubDate": "2024 Jan",
            "DOI": "10.1234/test",
        }
    ]
    mock_entrez.esummary.return_value = mock_handle
    mock_entrez.efetch.return_value = MagicMock(read=lambda: "This is the abstract text.")
    mock_entrez.elink.return_value = MagicMock()
    mock_entrez.read.side_effect = [
        [
            {
                "Title": "Test Article",
                "AuthorList": ["Smith J", "Doe A"],
                "Source": "Nature",
                "PubDate": "2024 Jan",
                "DOI": "10.1234/test",
            }
        ],
        [{"LinkSetDb": []}],
    ]

    result = fetcher._fetch_pmid("12345678")

    assert result is not None
    assert result.reference_id == "PMID:12345678"
    assert result.title == "Test Article"
