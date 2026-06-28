"""Tests for the Europe PMC preprint (PPR) reference source."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.etl.sources.ppr import PPRSource
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
    )


@pytest.fixture
def source():
    return PPRSource()


def _mock_search(result):
    mock_response = MagicMock()
    mock_response.status_code = 200
    results = [result] if result is not None else []
    mock_response.json.return_value = {
        "hitCount": len(results),
        "resultList": {"result": results},
    }
    return mock_response


def _core_result(**overrides):
    result = {
        "id": "PPR123456",
        "source": "PPR",
        "doi": "10.1101/2024.01.01.573333",
        "title": "A mechanistic preprint",
        "authorString": "Smith J, Doe A.",
        "pubYear": "2024",
        "abstractText": "We report a mechanistic finding in early form.",
        "journalInfo": {"journal": {"title": "bioRxiv"}},
    }
    result.update(overrides)
    return result


def test_prefix(source):
    assert source.prefix() == "PPR"


def test_can_handle(source):
    assert source.can_handle("PPR:PPR123456")
    assert source.can_handle("ppr:PPR123456")
    assert not source.can_handle("DOI:10.1101/x")
    assert not source.can_handle("PMID:123")


def test_registered_in_registry():
    assert ReferenceSourceRegistry.get_source("PPR:PPR123456") is PPRSource


@patch("linkml_reference_validator.etl.sources.ppr.requests.get")
def test_fetch_marks_preprint(mock_get, source, config):
    mock_get.return_value = _mock_search(_core_result())

    result = source.fetch("PPR123456", config)

    assert result is not None
    assert result.reference_id == "PPR:PPR123456"
    assert result.title == "A mechanistic preprint"
    assert result.doi == "10.1101/2024.01.01.573333"
    assert result.year == "2024"
    assert result.authors == ["Smith J", "Doe A"]
    assert result.journal == "bioRxiv"
    assert result.content_type == "abstract_only"
    assert "mechanistic finding" in result.content
    assert result.is_preprint is True
    assert result.peer_review_status == "preprint"


@patch("linkml_reference_validator.etl.sources.ppr.requests.get")
def test_fetch_without_abstract_is_unavailable(mock_get, source, config):
    mock_get.return_value = _mock_search(_core_result(abstractText=""))

    result = source.fetch("PPR123456", config)

    assert result is not None
    assert result.content_type == "unavailable"
    assert result.is_preprint is True


@patch("linkml_reference_validator.etl.sources.ppr.requests.get")
def test_fetch_no_results_returns_none(mock_get, source, config):
    mock_get.return_value = _mock_search(None)
    assert source.fetch("PPR999999", config) is None


@patch("linkml_reference_validator.etl.sources.ppr.requests.get")
def test_fetch_http_error_returns_none(mock_get, source, config):
    mock_response = MagicMock()
    mock_response.status_code = 500
    mock_get.return_value = mock_response
    assert source.fetch("PPR123456", config) is None


@patch("linkml_reference_validator.etl.sources.ppr.requests.get")
def test_fetch_normalizes_bare_numeric_id(mock_get, source, config):
    # A user may write "PPR:123456" without the "PPR" prefix on the id itself.
    mock_get.return_value = _mock_search(_core_result())
    result = source.fetch("123456", config)
    assert result is not None
    sent_params = mock_get.call_args.kwargs.get("params", {})
    assert "PPR123456" in sent_params.get("query", "")
