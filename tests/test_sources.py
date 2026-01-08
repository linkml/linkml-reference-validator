"""Tests for reference source plugins."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
from linkml_reference_validator.etl.sources.file import FileSource
from linkml_reference_validator.etl.sources.url import URLSource
from linkml_reference_validator.etl.sources.pmid import PMIDSource
from linkml_reference_validator.etl.sources.doi import DOISource
from linkml_reference_validator.etl.sources.entrez import (
    GEOSource,
    BioProjectSource,
    BioSampleSource,
)


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
        assert "GEO" in prefixes
        assert "BIOPROJECT" in prefixes
        assert "BIOSAMPLE" in prefixes
        assert "clinicaltrials" in prefixes

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


class TestClinicalTrialsSource:
    """Tests for ClinicalTrials.gov source."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    @pytest.fixture
    def source(self):
        """Create ClinicalTrialsSource instance."""
        from linkml_reference_validator.etl.sources.clinicaltrials import (
            ClinicalTrialsSource,
        )

        return ClinicalTrialsSource()

    def test_prefix(self, source):
        """ClinicalTrialsSource should have 'clinicaltrials' prefix (bioregistry standard)."""
        assert source.prefix() == "clinicaltrials"

    def test_can_handle_clinicaltrials_prefix(self, source):
        """Should handle clinicaltrials: prefixed references."""
        assert source.can_handle("clinicaltrials:NCT00000001")
        assert source.can_handle("clinicaltrials:NCT12345678")
        assert not source.can_handle("PMID:12345")

    def test_can_handle_bare_nct_id(self, source):
        """Should handle bare NCT IDs without prefix."""
        assert source.can_handle("NCT00000001")
        assert source.can_handle("NCT12345678")
        assert not source.can_handle("GSE12345")

    @patch("linkml_reference_validator.etl.sources.clinicaltrials.requests.get")
    def test_fetch_clinical_trial(self, mock_get, source, config):
        """Should fetch clinical trial data from ClinicalTrials.gov API."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000001",
                    "officialTitle": "A Study of Something Important",
                    "briefTitle": "Important Study",
                },
                "descriptionModule": {
                    "briefSummary": "This is a brief summary of the trial.",
                    "detailedDescription": "This is the detailed description.",
                },
                "statusModule": {
                    "overallStatus": "Completed",
                },
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {"name": "Test Sponsor"},
                },
            }
        }
        mock_get.return_value = mock_response

        result = source.fetch("NCT00000001", config)

        assert result is not None
        assert result.reference_id == "clinicaltrials:NCT00000001"
        assert result.title == "A Study of Something Important"
        assert result.content == "This is a brief summary of the trial."
        assert result.content_type == "summary"
        assert result.metadata["status"] == "Completed"
        assert result.metadata["sponsor"] == "Test Sponsor"
        mock_get.assert_called_once()

    @patch("linkml_reference_validator.etl.sources.clinicaltrials.requests.get")
    def test_fetch_uses_brief_title_fallback(self, mock_get, source, config):
        """Should use briefTitle when officialTitle is missing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000002",
                    "briefTitle": "Brief Title Only",
                },
                "descriptionModule": {
                    "briefSummary": "Summary text.",
                },
            }
        }
        mock_get.return_value = mock_response

        result = source.fetch("NCT00000002", config)

        assert result is not None
        assert result.title == "Brief Title Only"

    @patch("linkml_reference_validator.etl.sources.clinicaltrials.requests.get")
    def test_fetch_uses_detailed_description_fallback(self, mock_get, source, config):
        """Should use detailedDescription when briefSummary is missing."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT00000003",
                    "officialTitle": "Test Title",
                },
                "descriptionModule": {
                    "detailedDescription": "Detailed description only.",
                },
            }
        }
        mock_get.return_value = mock_response

        result = source.fetch("NCT00000003", config)

        assert result is not None
        assert result.content == "Detailed description only."

    @patch("linkml_reference_validator.etl.sources.clinicaltrials.requests.get")
    def test_fetch_not_found(self, mock_get, source, config):
        """Should return None for 404 responses."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = source.fetch("NCT99999999", config)

        assert result is None

    @patch("linkml_reference_validator.etl.sources.clinicaltrials.requests.get")
    def test_fetch_network_error(self, mock_get, source, config):
        """Should return None on network errors."""
        import requests  # type: ignore

        mock_get.side_effect = requests.RequestException("Network error")

        result = source.fetch("NCT00000001", config)

        assert result is None


class TestEntrezSummarySources:
    """Tests for Entrez summary-based sources."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    @pytest.mark.parametrize(
        ("source_cls", "reference_id", "title_key", "content_key", "db_name"),
        [
            (GEOSource, "GEO:GSE12345", "title", "summary", "gds"),
            (
                BioProjectSource,
                "BioProject:PRJNA000001",
                "Project_Title",
                "Project_Description",
                "bioproject",
            ),
            (BioSampleSource, "biosample:SAMN00000001", "Title", "Description", "biosample"),
        ],
    )
    @patch("linkml_reference_validator.etl.sources.entrez.Entrez.read")
    @patch("linkml_reference_validator.etl.sources.entrez.Entrez.esummary")
    def test_fetch_entrez_summary(
        self,
        mock_esummary,
        mock_read,
        source_cls,
        reference_id,
        title_key,
        content_key,
        db_name,
        config,
    ):
        """Should fetch summary records for Entrez-backed sources."""
        mock_handle = MagicMock()
        mock_esummary.return_value = mock_handle
        mock_read.return_value = [
            {
                title_key: "Example Title",
                content_key: "Example content summary.",
            }
        ]

        source = source_cls()
        result = source.fetch(reference_id.split(":", 1)[1], config)

        assert result is not None
        assert result.reference_id == f"{source.prefix()}:{reference_id.split(':', 1)[1]}"
        assert result.title == "Example Title"
        assert result.content == "Example content summary."
        assert result.content_type == "summary"
        assert result.metadata["entrez_db"] == db_name
        mock_esummary.assert_called_once_with(db=db_name, id=reference_id.split(":", 1)[1])
        mock_handle.close.assert_called_once()

    @pytest.mark.parametrize(
        ("source", "valid_id", "invalid_id"),
        [
            (GEOSource(), "geo:GSE12345", "DOI:10.1000/test"),
            (BioProjectSource(), "bioproject:PRJNA12345", "PMID:123"),
            (BioSampleSource(), "biosample:SAMN12345", "url:https://example.com"),
        ],
    )
    def test_can_handle_entrez_sources(self, source, valid_id, invalid_id):
        """Should handle prefixed Entrez references and reject others."""
        assert source.can_handle(valid_id)
        assert not source.can_handle(invalid_id)
