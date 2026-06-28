"""Tests for the Europe PMC preprint full-text provider."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ReferenceIdentifiers,
)
from linkml_reference_validator.etl.fulltext.epmc_preprint import (
    EuropePMCPreprintProvider,
)


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
    )


def _core_result(**overrides):
    """A representative Europe PMC SRC:PPR core search result."""
    result = {
        "id": "PPR123456",
        "source": "PPR",
        "doi": "10.1101/2024.01.01.573333",
        "title": "A mechanistic preprint",
        "authorString": "Smith J, Doe A.",
        "pubYear": "2024",
        "hasPDF": "Y",
        "fullTextUrlList": {
            "fullTextUrl": [
                {
                    "availability": "Open access",
                    "availabilityCode": "OA",
                    "documentStyle": "pdf",
                    "site": "Europe_PMC",
                    "url": (
                        "https://www.ebi.ac.uk/europepmc/webservices/rest/"
                        "fulltextRepo?pprId=PPR123456&type=FILE&fileName=ppr.pdf"
                        "&mimeType=application/pdf"
                    ),
                },
                {
                    "availability": "Open access",
                    "documentStyle": "html",
                    "url": "https://europepmc.org/article/PPR/PPR123456",
                },
            ]
        },
    }
    result.update(overrides)
    return result


def _mock_search(result_list):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "hitCount": len(result_list),
        "resultList": {"result": result_list},
    }
    return mock_response


def test_name():
    assert EuropePMCPreprintProvider.name() == "epmc_preprint"


def test_locate_without_doi_or_pprid_returns_none(config):
    provider = EuropePMCPreprintProvider()
    assert provider.locate(ReferenceIdentifiers(pmid="123"), config) is None


@patch("linkml_reference_validator.etl.fulltext.epmc_preprint.requests.get")
def test_locate_by_doi_returns_pdf_location(mock_get, config):
    mock_get.return_value = _mock_search([_core_result()])

    loc = EuropePMCPreprintProvider().locate(
        ReferenceIdentifiers(doi="10.1101/2024.01.01.573333"), config
    )

    assert loc is not None
    assert loc.url.startswith(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/fulltextRepo?pprId=PPR123456"
    )
    assert loc.format_hint == "pdf"
    assert loc.provider == "epmc_preprint"
    assert loc.version == "preprint"

    # The query must restrict to the preprint source so a peer-reviewed
    # record sharing the DOI namespace is never picked up here.
    sent_params = mock_get.call_args.kwargs.get("params", {})
    assert "SRC:PPR" in sent_params.get("query", "")
    assert "10.1101/2024.01.01.573333" in sent_params.get("query", "")


@patch("linkml_reference_validator.etl.fulltext.epmc_preprint.requests.get")
def test_locate_by_pprid_without_doi(mock_get, config):
    mock_get.return_value = _mock_search([_core_result()])

    loc = EuropePMCPreprintProvider().locate(
        ReferenceIdentifiers(pprid="PPR123456"), config
    )

    assert loc is not None
    assert loc.format_hint == "pdf"
    sent_params = mock_get.call_args.kwargs.get("params", {})
    assert "PPR123456" in sent_params.get("query", "")


@patch("linkml_reference_validator.etl.fulltext.epmc_preprint.requests.get")
def test_locate_no_results_returns_none(mock_get, config):
    mock_get.return_value = _mock_search([])
    loc = EuropePMCPreprintProvider().locate(
        ReferenceIdentifiers(doi="10.1101/x"), config
    )
    assert loc is None


@patch("linkml_reference_validator.etl.fulltext.epmc_preprint.requests.get")
def test_locate_non_ppr_source_ignored(mock_get, config):
    # A non-preprint record must not be treated as a preprint full-text hit.
    mock_get.return_value = _mock_search([_core_result(source="MED")])
    loc = EuropePMCPreprintProvider().locate(
        ReferenceIdentifiers(doi="10.1101/x"), config
    )
    assert loc is None


@patch("linkml_reference_validator.etl.fulltext.epmc_preprint.requests.get")
def test_locate_constructs_fulltextrepo_url_when_list_absent(mock_get, config):
    # Some core records flag hasPDF=Y but omit a usable pdf entry in the list;
    # fall back to constructing the fulltextRepo URL from the preprint id.
    result = _core_result(fullTextUrlList={"fullTextUrl": []})
    mock_get.return_value = _mock_search([result])

    loc = EuropePMCPreprintProvider().locate(
        ReferenceIdentifiers(doi="10.1101/2024.01.01.573333"), config
    )
    assert loc is not None
    assert "fulltextRepo" in loc.url
    assert "PPR123456" in loc.url
    assert loc.format_hint == "pdf"


@patch("linkml_reference_validator.etl.fulltext.epmc_preprint.requests.get")
def test_locate_no_full_text_returns_none(mock_get, config):
    # No PDF available at all (hasPDF=N, empty list): nothing to fetch.
    result = _core_result(hasPDF="N", fullTextUrlList={"fullTextUrl": []})
    mock_get.return_value = _mock_search([result])

    loc = EuropePMCPreprintProvider().locate(
        ReferenceIdentifiers(doi="10.1101/x"), config
    )
    assert loc is None


@patch("linkml_reference_validator.etl.fulltext.epmc_preprint.requests.get")
def test_locate_http_error_returns_none(mock_get, config):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_get.return_value = mock_response

    loc = EuropePMCPreprintProvider().locate(
        ReferenceIdentifiers(doi="10.1101/x"), config
    )
    assert loc is None


def test_registered_in_default_registry():
    from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
    import linkml_reference_validator.etl.fulltext  # noqa: F401

    assert FullTextProviderRegistry.get("epmc_preprint") is not None
