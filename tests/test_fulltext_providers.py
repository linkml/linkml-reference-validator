"""Tests for full-text providers and their registry."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.etl.extract import MIN_FULLTEXT_CHARS
from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ReferenceIdentifiers,
    FullTextLocation,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)


@pytest.fixture
def config(tmp_path):
    """Config for the module-level tests below (classes define their own)."""
    return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)


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


class TestOpenAlexProvider:
    @pytest.fixture
    def config(self, tmp_path):
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
        )

    @patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
    def test_locate_returns_pdf_location(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "open_access": {"is_oa": True, "oa_status": "green", "oa_url": "https://oa/paper"},
            "best_oa_location": {
                "pdf_url": "https://oa.example.org/openalex.pdf",
                "license": "cc-by",
                "version": "acceptedVersion",
            },
        }
        mock_get.return_value = mock_response

        loc = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)
        assert loc is not None
        assert loc.url == "https://oa.example.org/openalex.pdf"
        assert loc.format_hint == "pdf"
        assert loc.oa_status == "green"
        assert loc.provider == "openalex"

    @patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
    def test_locate_falls_back_to_oa_url(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "open_access": {"is_oa": True, "oa_status": "bronze", "oa_url": "https://oa/landing"},
            "best_oa_location": {"pdf_url": None},
        }
        mock_get.return_value = mock_response

        loc = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)
        assert loc.url == "https://oa/landing"
        assert loc.format_hint == "html"

    @patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
    def test_locate_not_oa_returns_none(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"open_access": {"is_oa": False}, "best_oa_location": None}
        mock_get.return_value = mock_response

        assert OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config) is None


class TestPMCProvider:
    @pytest.fixture
    def config(self, tmp_path):
        return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)

    def test_name(self):
        from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

        assert PMCFullTextProvider.name() == "pmc"

    def test_locate_without_pmid_or_pmcid_returns_none(self, config):
        from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

        assert PMCFullTextProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config) is None

    def test_locate_returns_text_from_xml(self, config):
        from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

        provider = PMCFullTextProvider()
        # Sized from the floor rather than from an incidental paragraph count:
        # the previous fixture cleared MIN_FULLTEXT_CHARS by 28 characters, so
        # shortening a sentence or raising the floor would have failed this
        # test for a reason unrelated to what it checks.
        xml = _pmc_article_xml(MIN_FULLTEXT_CHARS + 500)

        with patch.object(provider, "_resolve_pmcid", return_value="999"), \
             patch.object(provider, "_fetch_pmc_xml_source", return_value=xml):
            loc = provider.locate(ReferenceIdentifiers(pmid="123", pmcid="999"), config)

        assert loc is not None
        assert loc.format_hint == "xml"
        assert loc.provider == "pmc"
        assert "Body sentence with enough prose" in loc.text
        assert len(loc.text) > MIN_FULLTEXT_CHARS


# ============================================================================
# The full-text floor
#
# MIN_FULLTEXT_CHARS is the only stub defence on the HTML paths, and carries
# the reasoning for both its own value and MAX_STUB_NOTICE_CHARS'. Nothing
# asserted it: changing > to >= or deleting a gate left the suite green.
# ============================================================================


def _pmc_article_xml(length: int) -> bytes:
    """Build PMC article XML whose extracted body text is at least `length`."""
    filler = "Body sentence with enough prose to be worth counting. "
    paragraphs = "".join(
        f"<p>{filler * 4}</p>" for _ in range(length // (len(filler) * 4) + 1)
    )
    return f"<article><body>{paragraphs}</body></article>".encode()


def test_pmc_locate_rejects_xml_below_the_floor(config):
    """A body no longer than a placeholder notice is not full text."""
    from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

    provider = PMCFullTextProvider()
    short = b"<article><body><p>Too little to be an article body.</p></body></article>"

    with patch.object(provider, "_resolve_pmcid", return_value="999"), \
         patch.object(provider, "_fetch_pmc_xml_source", return_value=short), \
         patch.object(provider, "_fetch_pmc_html", return_value=None):
        loc = provider.locate(ReferenceIdentifiers(pmid="123", pmcid="999"), config)

    assert loc is None


def test_pmc_locate_rejects_html_below_the_floor(config):
    """The HTML fallback is gated too - it has no is_stub_notice check at all."""
    from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

    provider = PMCFullTextProvider()

    with patch.object(provider, "_resolve_pmcid", return_value="999"), \
         patch.object(provider, "_fetch_pmc_xml_source", return_value=None), \
         patch.object(provider, "_fetch_pmc_html", return_value="Short landing page."):
        loc = provider.locate(ReferenceIdentifiers(pmid="123", pmcid="999"), config)

    assert loc is None


def test_pmc_locate_accepts_text_at_the_floor_boundary(config):
    """One character past the floor is full text; the gate is exclusive."""
    from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

    provider = PMCFullTextProvider()

    with patch.object(provider, "_resolve_pmcid", return_value="999"), \
         patch.object(provider, "_fetch_pmc_xml_source", return_value=None), \
         patch.object(provider, "_fetch_pmc_html", return_value="x" * MIN_FULLTEXT_CHARS):
        assert provider.locate(ReferenceIdentifiers(pmcid="999"), config) is None

    with patch.object(provider, "_resolve_pmcid", return_value="999"), \
         patch.object(provider, "_fetch_pmc_xml_source", return_value=None), \
         patch.object(
             provider, "_fetch_pmc_html", return_value="x" * (MIN_FULLTEXT_CHARS + 1)
         ):
        assert provider.locate(ReferenceIdentifiers(pmcid="999"), config) is not None


def test_pmid_fulltext_rejects_responses_below_the_floor(config):
    """The PMID path has its own two gates on the same floor."""
    from linkml_reference_validator.etl.sources.pmid import PMIDSource

    source = PMIDSource()

    with patch.object(source, "_get_pmcid", return_value="999"), \
         patch.object(source, "_fetch_pmc_xml", return_value="Too short."), \
         patch.object(source, "_fetch_pmc_html", return_value="Also too short."):
        text, content_type = source._fetch_pmc_fulltext("123", config)

    assert text is None
    assert content_type == "pmc_restricted"


def test_pmid_fulltext_accepts_a_body_past_the_floor(config):
    """The rejection tests above must not pass by rejecting everything."""
    from linkml_reference_validator.etl.sources.pmid import PMIDSource

    source = PMIDSource()
    body = "x" * (MIN_FULLTEXT_CHARS + 500)

    with patch.object(source, "_get_pmcid", return_value="999"), \
         patch.object(source, "_fetch_pmc_xml", return_value=body):
        text, content_type = source._fetch_pmc_fulltext("123", config)

    assert text == body
    assert content_type == "full_text_xml"
