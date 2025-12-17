"""Tests for reference source plugins."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
from linkml_reference_validator.etl.sources.file import FileSource
from linkml_reference_validator.etl.sources.url import URLSource
from linkml_reference_validator.etl.sources.pmid import PMIDSource
from linkml_reference_validator.etl.sources.doi import DOISource


class TestReferenceSourceRegistry:
    """Tests for the source registry."""

    def test_registry_has_default_sources(self):
        """Registry should have PMID, DOI, file, and url sources registered."""
        sources = ReferenceSourceRegistry.list_sources()
        prefixes = [s.prefix() for s in sources]
        assert "PMID" in prefixes
        assert "DOI" in prefixes
        assert "file" in prefixes
        assert "url" in prefixes

    def test_get_source_for_pmid(self):
        """Should return PMIDSource for PMID references."""
        source = ReferenceSourceRegistry.get_source("PMID:12345678")
        assert source is not None
        assert source.prefix() == "PMID"

    def test_get_source_for_doi(self):
        """Should return DOISource for DOI references."""
        source = ReferenceSourceRegistry.get_source("DOI:10.1234/test")
        assert source is not None
        assert source.prefix() == "DOI"

    def test_get_source_for_file(self):
        """Should return FileSource for file references."""
        source = ReferenceSourceRegistry.get_source("file:./test.md")
        assert source is not None
        assert source.prefix() == "file"

    def test_get_source_for_url(self):
        """Should return URLSource for url references."""
        source = ReferenceSourceRegistry.get_source("url:https://example.com")
        assert source is not None
        assert source.prefix() == "url"

    def test_get_source_unknown(self):
        """Should return None for unknown reference types."""
        source = ReferenceSourceRegistry.get_source("UNKNOWN:12345")
        assert source is None


class TestFileSource:
    """Tests for FileSource."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    @pytest.fixture
    def source(self):
        """Create FileSource instance."""
        return FileSource()

    def test_prefix(self, source):
        """FileSource should have 'file' prefix."""
        assert source.prefix() == "file"

    def test_can_handle_file_prefix(self, source):
        """Should handle file: references."""
        assert source.can_handle("file:./test.md")
        assert source.can_handle("file:/absolute/path.txt")
        assert not source.can_handle("PMID:12345")

    def test_fetch_markdown_file(self, source, config, tmp_path):
        """Should read markdown file content."""
        # Create test markdown file
        test_file = tmp_path / "test.md"
        test_file.write_text("# Test Document\n\nThis is test content.")

        result = source.fetch(str(test_file), config)

        assert result is not None
        assert result.reference_id == f"file:{test_file}"
        assert result.title == "Test Document"
        assert "This is test content." in result.content
        assert result.content_type == "local_file"

    def test_fetch_plain_text_file(self, source, config, tmp_path):
        """Should read plain text file content."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Plain text content here.")

        result = source.fetch(str(test_file), config)

        assert result is not None
        assert "Plain text content here." in result.content
        assert result.title == "test.txt"  # Falls back to filename

    def test_fetch_relative_path_with_base_dir(self, tmp_path):
        """Should resolve relative paths using reference_base_dir."""
        # Create base dir with test file
        base_dir = tmp_path / "references"
        base_dir.mkdir()
        test_file = base_dir / "notes.md"
        test_file.write_text("# Notes\n\nSome notes here.")

        config = ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            reference_base_dir=base_dir,
        )
        source = FileSource()

        result = source.fetch("notes.md", config)

        assert result is not None
        assert "Some notes here." in result.content

    def test_fetch_relative_path_cwd_fallback(self, source, config, tmp_path, monkeypatch):
        """Should resolve relative paths from CWD if no base_dir set."""
        # Create test file in tmp_path (simulating CWD)
        test_file = tmp_path / "relative.md"
        test_file.write_text("# Relative\n\nRelative content.")

        # Change CWD to tmp_path
        monkeypatch.chdir(tmp_path)

        result = source.fetch("relative.md", config)

        assert result is not None
        assert "Relative content." in result.content

    def test_fetch_nonexistent_file(self, source, config):
        """Should return None for nonexistent files."""
        result = source.fetch("/nonexistent/file.md", config)
        assert result is None

    def test_extract_title_from_markdown(self, source, config, tmp_path):
        """Should extract title from first heading."""
        test_file = tmp_path / "titled.md"
        test_file.write_text("Some preamble\n\n# The Real Title\n\nContent here.")

        result = source.fetch(str(test_file), config)

        assert result is not None
        assert result.title == "The Real Title"

    def test_html_content_preserved(self, source, config, tmp_path):
        """HTML content should be preserved as-is."""
        test_file = tmp_path / "test.html"
        test_file.write_text("<html><body><p>Test &amp; content</p></body></html>")

        result = source.fetch(str(test_file), config)

        assert result is not None
        assert "&amp;" in result.content  # HTML entities preserved


class TestURLSource:
    """Tests for URLSource."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    @pytest.fixture
    def source(self):
        """Create URLSource instance."""
        return URLSource()

    def test_prefix(self, source):
        """URLSource should have 'url' prefix."""
        assert source.prefix() == "url"

    def test_can_handle_url_prefix(self, source):
        """Should handle url: references."""
        assert source.can_handle("url:https://example.com")
        assert source.can_handle("url:http://example.com/page")
        assert not source.can_handle("PMID:12345")

    @patch("linkml_reference_validator.etl.sources.url.requests.get")
    def test_fetch_url_html(self, mock_get, source, config):
        """Should fetch HTML content from URL."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><head><title>Test Page</title></head><body>Content here</body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_get.return_value = mock_response

        result = source.fetch("https://example.com/page", config)

        assert result is not None
        assert result.reference_id == "url:https://example.com/page"
        assert "Content here" in result.content
        assert result.content_type == "url"

    @patch("linkml_reference_validator.etl.sources.url.requests.get")
    def test_fetch_url_plain_text(self, mock_get, source, config):
        """Should fetch plain text content from URL."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "Plain text content from URL"
        mock_response.headers = {"content-type": "text/plain"}
        mock_get.return_value = mock_response

        result = source.fetch("https://example.com/text.txt", config)

        assert result is not None
        assert "Plain text content from URL" in result.content

    @patch("linkml_reference_validator.etl.sources.url.requests.get")
    def test_fetch_url_not_found(self, mock_get, source, config):
        """Should return None for 404 responses."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = source.fetch("https://example.com/notfound", config)

        assert result is None

    @patch("linkml_reference_validator.etl.sources.url.requests.get")
    def test_fetch_url_extracts_title(self, mock_get, source, config):
        """Should extract title from HTML."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "<html><head><title>Page Title Here</title></head><body>Content</body></html>"
        mock_response.headers = {"content-type": "text/html"}
        mock_get.return_value = mock_response

        result = source.fetch("https://example.com", config)

        assert result is not None
        assert result.title == "Page Title Here"


class TestPMIDSource:
    """Tests for PMIDSource (refactored from ReferenceFetcher)."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    @pytest.fixture
    def source(self):
        """Create PMIDSource instance."""
        return PMIDSource()

    def test_prefix(self, source):
        """PMIDSource should have 'PMID' prefix."""
        assert source.prefix() == "PMID"

    def test_can_handle_pmid(self, source):
        """Should handle PMID references."""
        assert source.can_handle("PMID:12345678")
        assert source.can_handle("PMID 12345678")
        assert not source.can_handle("DOI:10.1234/test")


class TestDOISource:
    """Tests for DOISource (refactored from ReferenceFetcher)."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    @pytest.fixture
    def source(self):
        """Create DOISource instance."""
        return DOISource()

    def test_prefix(self, source):
        """DOISource should have 'DOI' prefix."""
        assert source.prefix() == "DOI"

    def test_can_handle_doi(self, source):
        """Should handle DOI references."""
        assert source.can_handle("DOI:10.1234/test")
        assert not source.can_handle("PMID:12345678")
