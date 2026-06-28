"""Tests for preprint detection in the DOI (Crossref) source."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.etl.sources.doi import DOISource


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
    )


@pytest.fixture
def source():
    return DOISource()


def _crossref_response(message):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok", "message": message}
    return mock_response


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_posted_content_preprint_is_marked(mock_get, source, config):
    mock_get.return_value = _crossref_response(
        {
            "type": "posted-content",
            "subtype": "preprint",
            "title": ["A bioRxiv preprint"],
            "abstract": "<jats:p>Early findings.</jats:p>",
            "publisher": "Cold Spring Harbor Laboratory",
            "published-online": {"date-parts": [[2024]]},
        }
    )

    result = source.fetch("10.1101/2024.01.01.573333", config)

    assert result is not None
    assert result.is_preprint is True
    assert result.peer_review_status == "preprint"


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_posted_content_without_subtype_is_marked(mock_get, source, config):
    # Some posted-content records omit the explicit "preprint" subtype.
    mock_get.return_value = _crossref_response(
        {
            "type": "posted-content",
            "title": ["A preprint"],
            "publisher": "openRxiv",
            "published-online": {"date-parts": [[2026]]},
        }
    )

    result = source.fetch("10.64898/2026.01.01.000001", config)

    assert result is not None
    assert result.is_preprint is True
    assert result.peer_review_status == "preprint"


@patch("linkml_reference_validator.etl.sources.doi.requests.get")
def test_journal_article_is_not_marked_preprint(mock_get, source, config):
    mock_get.return_value = _crossref_response(
        {
            "type": "journal-article",
            "title": ["A peer-reviewed paper"],
            "abstract": "<jats:p>Results.</jats:p>",
            "container-title": ["Nature"],
            "published-print": {"date-parts": [[2023]]},
        }
    )

    result = source.fetch("10.1038/s41586-023-12345", config)

    assert result is not None
    # We only positively assert preprint status; peer-reviewed papers are left
    # unannotated rather than asserted as "peer_reviewed".
    assert result.is_preprint is None
    assert result.peer_review_status is None
