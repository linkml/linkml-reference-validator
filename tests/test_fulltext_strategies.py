"""Tests for enhanced fulltext retrieval strategies.

These tests verify the BioC XML, Europe PMC, Unpaywall, and identifier
conversion utilities.
"""

import pytest
from unittest.mock import Mock, patch

from linkml_reference_validator.etl.fulltext_strategies import (
    FulltextStrategy,
    BioCStrategy,
    EuropePMCStrategy,
    UnpaywallStrategy,
    IdentifierConverter,
    FulltextResult,
)


class TestFulltextResult:
    """Test the FulltextResult data structure."""

    def test_fulltext_result_creation(self):
        """Test creating a basic FulltextResult."""
        result = FulltextResult(
            content="This is the full text content.",
            source="bioc",
            content_type="full_text",
        )
        assert result.content == "This is the full text content."
        assert result.source == "bioc"
        assert result.content_type == "full_text"
        assert result.success is True

    def test_fulltext_result_failure(self):
        """Test creating a failed FulltextResult."""
        result = FulltextResult(
            content=None,
            source="unpaywall",
            content_type="unavailable",
            success=False,
            error_message="No open access version found",
        )
        assert result.content is None
        assert result.success is False
        assert "No open access" in result.error_message


class TestBioCStrategy:
    """Test BioC XML fulltext retrieval."""

    def test_bioc_url_construction(self):
        """Test the BioC URL is correctly constructed."""
        strategy = BioCStrategy()
        url = strategy._build_url("12345678")
        assert "12345678" in url
        assert "BioC_xml" in url

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_bioc_fetch_success(self, mock_get):
        """Test successful BioC fulltext fetch."""
        # Need to provide enough text to pass the 500 char minimum
        long_intro = "This is the introduction paragraph. " * 20
        long_results = "This is the results section with detailed findings. " * 20
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = f"""<?xml version="1.0" encoding="UTF-8"?>
        <collection>
            <document>
                <passage>
                    <text>{long_intro}</text>
                </passage>
                <passage>
                    <text>{long_results}</text>
                </passage>
            </document>
        </collection>"""
        mock_get.return_value = mock_response

        strategy = BioCStrategy()
        result = strategy.fetch("12345678")

        assert result.success is True
        assert "introduction paragraph" in result.content
        assert "results section" in result.content
        assert result.source == "bioc"
        assert result.content_type == "full_text_bioc"

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_bioc_fetch_not_found(self, mock_get):
        """Test BioC fetch when article not in OA subset."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        strategy = BioCStrategy()
        result = strategy.fetch("99999999")

        assert result.success is False
        assert result.content is None


class TestEuropePMCStrategy:
    """Test Europe PMC fulltext retrieval."""

    def test_europepmc_api_url(self):
        """Test Europe PMC API URL construction."""
        strategy = EuropePMCStrategy()
        url = strategy._build_search_url("12345678")
        assert "europepmc" in url

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_europepmc_fetch_by_pmid(self, mock_get):
        """Test fetching fulltext via Europe PMC by PMID."""
        # Mock search response
        search_response = Mock()
        search_response.status_code = 200
        search_response.json.return_value = {
            "resultList": {
                "result": [{
                    "pmid": "12345678",
                    "pmcid": "PMC123456",
                    "isOpenAccess": "Y",
                }]
            }
        }

        # Mock fulltext response - needs enough text to pass 500 char minimum
        long_text = "This is the full article text from Europe PMC. " * 20
        fulltext_response = Mock()
        fulltext_response.status_code = 200
        fulltext_response.text = f"""<?xml version="1.0"?>
        <article>
            <body>
                <sec>
                    <p>{long_text}</p>
                </sec>
            </body>
        </article>"""

        mock_get.side_effect = [search_response, fulltext_response]

        strategy = EuropePMCStrategy()
        result = strategy.fetch("12345678")

        assert result.success is True
        assert "Europe PMC" in result.content
        assert result.source == "europepmc"

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_europepmc_not_open_access(self, mock_get):
        """Test Europe PMC when article is not open access."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "resultList": {
                "result": [{
                    "pmid": "12345678",
                    "isOpenAccess": "N",
                }]
            }
        }
        mock_get.return_value = mock_response

        strategy = EuropePMCStrategy()
        result = strategy.fetch("12345678")

        assert result.success is False


class TestUnpaywallStrategy:
    """Test Unpaywall API for open access papers."""

    def test_unpaywall_url_construction(self):
        """Test Unpaywall API URL is correctly constructed."""
        strategy = UnpaywallStrategy(email="test@example.com")
        url = strategy._build_url("10.1234/example.doi")
        assert "api.unpaywall.org" in url
        assert "10.1234/example.doi" in url
        assert "test@example.com" in url

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_unpaywall_fetch_open_access(self, mock_get):
        """Test Unpaywall finding an open access version."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "is_oa": True,
            "best_oa_location": {
                "url": "https://example.com/paper.pdf",
                "url_for_pdf": "https://example.com/paper.pdf",
                "license": "cc-by",
                "version": "publishedVersion",
            },
            "oa_locations": [
                {
                    "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC123456/",
                    "pmh_id": "oai:pubmedcentral.nih.gov:123456",
                }
            ]
        }
        mock_get.return_value = mock_response

        strategy = UnpaywallStrategy(email="test@example.com")
        result = strategy.fetch("10.1234/example.doi")

        assert result.success is True
        assert result.source == "unpaywall"
        assert result.metadata["is_oa"] is True
        assert "pdf" in result.metadata.get("pdf_url", "")

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_unpaywall_not_open_access(self, mock_get):
        """Test Unpaywall when article is not open access."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "is_oa": False,
            "best_oa_location": None,
        }
        mock_get.return_value = mock_response

        strategy = UnpaywallStrategy(email="test@example.com")
        result = strategy.fetch("10.1234/closed.doi")

        assert result.success is False
        assert "not open access" in result.error_message.lower()


class TestIdentifierConverter:
    """Test identifier conversion utilities."""

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_doi_to_pmid(self, mock_get):
        """Test converting DOI to PMID."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [{
                "pmid": "12345678",
                "pmcid": "PMC654321",
                "doi": "10.1234/example",
            }]
        }
        mock_get.return_value = mock_response

        converter = IdentifierConverter()
        pmid = converter.doi_to_pmid("10.1234/example")
        assert pmid == "12345678"

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_pmid_to_doi(self, mock_get):
        """Test converting PMID to DOI."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "12345678": {
                    "articleids": [
                        {"idtype": "pubmed", "value": "12345678"},
                        {"idtype": "doi", "value": "10.1234/example"},
                    ]
                }
            }
        }
        mock_get.return_value = mock_response

        converter = IdentifierConverter()
        doi = converter.pmid_to_doi("12345678")
        assert doi == "10.1234/example"

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_pmid_to_pmcid(self, mock_get):
        """Test converting PMID to PMCID."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "records": [{
                "pmid": "12345678",
                "pmcid": "PMC654321",
            }]
        }
        mock_get.return_value = mock_response

        converter = IdentifierConverter()
        pmcid = converter.pmid_to_pmcid("12345678")
        assert pmcid == "PMC654321"

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_pmcid_to_pmid(self, mock_get):
        """Test converting PMCID to PMID."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "result": {
                "uids": ["654321"],
                "654321": {
                    "articleids": [
                        {"idtype": "pmid", "value": "12345678"},
                    ]
                }
            }
        }
        mock_get.return_value = mock_response

        converter = IdentifierConverter()
        pmid = converter.pmcid_to_pmid("PMC654321")
        assert pmid == "12345678"


class TestFulltextStrategyChain:
    """Test chaining multiple fulltext strategies."""

    @patch("linkml_reference_validator.etl.fulltext_strategies.requests.get")
    def test_strategy_chain_fallback(self, mock_get):
        """Test that strategies fall back when one fails."""
        # First strategy (BioC) fails
        bioc_response = Mock()
        bioc_response.status_code = 404

        # Second strategy (Europe PMC) succeeds
        long_text = "Europe PMC text with enough content to pass validation. " * 20
        europepmc_search = Mock()
        europepmc_search.status_code = 200
        europepmc_search.json.return_value = {
            "resultList": {
                "result": [{
                    "pmid": "12345678",
                    "pmcid": "PMC123456",
                    "isOpenAccess": "Y",
                }]
            }
        }
        europepmc_fulltext = Mock()
        europepmc_fulltext.status_code = 200
        europepmc_fulltext.text = f"<article><body><p>{long_text}</p></body></article>"

        mock_get.side_effect = [bioc_response, europepmc_search, europepmc_fulltext]

        from linkml_reference_validator.etl.fulltext_strategies import FulltextFetcher
        fetcher = FulltextFetcher(email="test@example.com")
        result = fetcher.fetch_fulltext_for_pmid("12345678")

        assert result.success is True
        assert result.source == "europepmc"
