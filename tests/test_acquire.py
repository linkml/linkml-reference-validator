"""Tests for the content acquirer."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.etl.acquire import ContentAcquirer, resolve_format


def test_resolve_format_by_content_type():
    assert resolve_format("application/pdf", "https://x/y", None) == "pdf"
    assert resolve_format("text/html; charset=utf-8", "https://x/y", None) == "html"
    assert resolve_format("application/xml", "https://x/y", None) == "xml"


def test_resolve_format_by_url_suffix():
    assert resolve_format(None, "https://x/y.pdf", None) == "pdf"
    assert resolve_format(None, "https://x/y.html", None) == "html"


def test_resolve_format_by_hint():
    assert resolve_format(None, "https://x/y", "pdf") == "pdf"


def test_resolve_format_precedence_content_type_wins():
    assert resolve_format("application/pdf", "https://x/y.html", "html") == "pdf"


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_returns_content_and_type(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/pdf", "content-length": "5"}
    mock_response.iter_content.return_value = [b"%PDF-"]
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    data, ctype = ContentAcquirer().fetch_bytes("https://x/y.pdf", config)
    assert data == b"%PDF-"
    assert ctype == "application/pdf"


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_enforces_size_cap(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/pdf"}
    mock_response.iter_content.return_value = [b"x" * 10, b"x" * 10]
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        max_supplementary_file_size=15,
    )
    data, ctype = ContentAcquirer().fetch_bytes("https://x/y.pdf", config)
    assert data is None  # exceeded cap → not returned


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_non_200_returns_none(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    data, ctype = ContentAcquirer().fetch_bytes("https://x/missing.pdf", config)
    assert data is None
