"""Tests for full-text providers and their registry."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ReferenceIdentifiers,
    FullTextLocation,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)


class _FakeProvider(FullTextProvider):
    @classmethod
    def name(cls):
        return "fake"

    def locate(self, ids, config):
        return FullTextLocation(text="some text", format_hint="text", provider="fake")


def test_registry_register_and_get():
    FullTextProviderRegistry.register(_FakeProvider)
    provider = FullTextProviderRegistry.get("fake")
    assert provider is not None
    loc = provider.locate(ReferenceIdentifiers(), ReferenceValidationConfig())
    assert loc.text == "some text"


def test_registry_get_unknown_returns_none():
    assert FullTextProviderRegistry.get("nope") is None


class TestUnpaywallProvider:
    @pytest.fixture
    def config(self, tmp_path):
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
        )

    @patch("linkml_reference_validator.etl.fulltext.unpaywall.requests.get")
    def test_locate_returns_pdf_location(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://oa.example.org/paper.pdf",
                "url": "https://oa.example.org/paper",
                "license": "cc-by",
                "version": "publishedVersion",
            },
        }
        mock_get.return_value = mock_response

        loc = UnpaywallProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)
        assert loc is not None
        assert loc.url == "https://oa.example.org/paper.pdf"
        assert loc.format_hint == "pdf"
        assert loc.oa_status == "gold"
        assert loc.license == "cc-by"
        assert loc.provider == "unpaywall"

    @patch("linkml_reference_validator.etl.fulltext.unpaywall.requests.get")
    def test_locate_not_oa_returns_none(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"is_oa": False, "best_oa_location": None}
        mock_get.return_value = mock_response

        assert UnpaywallProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config) is None

    def test_locate_without_doi_returns_none(self, config):
        from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

        assert UnpaywallProvider().locate(ReferenceIdentifiers(pmid="123"), config) is None
