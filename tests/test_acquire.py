"""Tests for the content acquirer."""

from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.etl.acquire import (
    ContentAcquirer,
    resolve_format,
    sniff_format,
)


def _cm_response(**attrs):
    """Build a MagicMock requests response that is its own context manager."""
    response = MagicMock()
    response.__enter__.return_value = response
    for key, value in attrs.items():
        setattr(response, key, value)
    return response


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


def test_sniff_format_detects_pdf():
    assert sniff_format(b"%PDF-1.7\n...") == "pdf"


def test_sniff_format_detects_html():
    assert sniff_format(b"<!DOCTYPE html><html><body>hi</body></html>") == "html"
    assert sniff_format(b"  \n<html><head></head></html>") == "html"


def test_sniff_format_detects_xml():
    assert sniff_format(b"<?xml version='1.0'?><article/>") == "xml"


def test_sniff_format_unknown_returns_none():
    assert sniff_format(b"just some plain text") is None
    assert sniff_format(b"") is None


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_returns_content_and_type(mock_get, tmp_path):
    mock_response = _cm_response(
        status_code=200,
        headers={"content-type": "application/pdf", "content-length": "5"},
    )
    mock_response.iter_content.return_value = [b"%PDF-"]
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    data, ctype = ContentAcquirer().fetch_bytes("https://x/y.pdf", config)
    assert data == b"%PDF-"
    assert ctype == "application/pdf"


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_enforces_size_cap(mock_get, tmp_path):
    mock_response = _cm_response(
        status_code=200, headers={"content-type": "application/pdf"}
    )
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
def test_fetch_bytes_closes_response_on_size_cap(mock_get, tmp_path):
    """The streamed response must be closed even when the cap aborts the read."""
    mock_response = _cm_response(
        status_code=200, headers={"content-type": "application/pdf"}
    )
    mock_response.iter_content.return_value = [b"x" * 10, b"x" * 10]
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        max_supplementary_file_size=15,
    )
    ContentAcquirer().fetch_bytes("https://x/y.pdf", config)
    mock_response.__exit__.assert_called()  # context manager released the connection


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_non_200_returns_none(mock_get, tmp_path):
    mock_response = _cm_response(status_code=404)
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    data, ctype = ContentAcquirer().fetch_bytes("https://x/missing.pdf", config)
    assert data is None
