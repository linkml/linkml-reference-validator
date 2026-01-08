"""Integration tests for ClinicalTrials.gov reference source.

Tests using real cached fixtures and optional live API tests.

Uses the bioregistry standard prefix 'clinicaltrials'.
See: https://bioregistry.io/registry/clinicaltrials
"""

import pytest
from linkml_reference_validator.models import ReferenceValidationConfig, ValidationSeverity
from linkml_reference_validator.etl.sources.clinicaltrials import ClinicalTrialsSource


class TestClinicalTrialsIntegration:
    """Integration tests using cached clinical trials fixtures."""

    def test_fetch_cached_clinicaltrials_reference(self, fetcher_with_fixtures):
        """Test fetching a cached clinical trials reference."""
        ref = fetcher_with_fixtures.fetch("clinicaltrials:NCT00000001")

        assert ref is not None
        assert ref.reference_id == "clinicaltrials:NCT00000001"
        assert ref.title == "A Phase III Study of Drug X for Treatment of Disease Y"
        assert "efficacy and safety of Drug X" in ref.content
        assert ref.content_type == "summary"

    def test_validate_clinicaltrials_reference_success(self, validator_with_fixtures):
        """Test validation with cached clinical trials reference - success case."""
        result = validator_with_fixtures.validate(
            "efficacy and safety of Drug X in patients with Disease Y",
            "clinicaltrials:NCT00000001",
        )

        assert result.is_valid is True
        assert result.severity == ValidationSeverity.INFO
        assert result.match_result is not None
        assert result.match_result.found is True

    def test_validate_clinicaltrials_reference_substring(self, validator_with_fixtures):
        """Test substring matching with clinical trials reference."""
        result = validator_with_fixtures.validate(
            "primary endpoint is overall survival at 12 months",
            "clinicaltrials:NCT00000001",
        )

        assert result.is_valid is True

    def test_validate_clinicaltrials_reference_not_found(self, validator_with_fixtures):
        """Test validation when text is not in clinical trials reference."""
        result = validator_with_fixtures.validate(
            "this text is definitely not in any clinical trial",
            "clinicaltrials:NCT00000001",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "not found" in result.message.lower()

    def test_validate_clinicaltrials_with_title_validation(self, validator_with_fixtures):
        """Test validation with clinical trials title check."""
        result = validator_with_fixtures.validate(
            "efficacy and safety of Drug X",
            "clinicaltrials:NCT00000001",
            expected_title="A Phase III Study of Drug X for Treatment of Disease Y",
        )

        assert result.is_valid is True
        assert "title validated" in result.message

    def test_validate_clinicaltrials_title_mismatch(self, validator_with_fixtures):
        """Test validation with clinical trials title mismatch."""
        result = validator_with_fixtures.validate(
            "efficacy and safety of Drug X",
            "clinicaltrials:NCT00000001",
            expected_title="Wrong Trial Title",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "title mismatch" in result.message.lower()

    def test_validate_clinicaltrials_multipart_quote(self, validator_with_fixtures):
        """Test validation with multi-part quote using ellipsis."""
        result = validator_with_fixtures.validate(
            "primary endpoint is overall survival ... progression-free survival",
            "clinicaltrials:NCT00000001",
        )

        assert result.is_valid is True

    def test_fetch_nonexistent_clinicaltrials(self, fetcher_with_fixtures):
        """Test fetcher returns None for nonexistent clinical trial."""
        ref = fetcher_with_fixtures.fetch("clinicaltrials:NCT99999999")

        assert ref is None


class TestClinicalTrialsSourceDirect:
    """Direct tests for ClinicalTrialsSource class."""

    @pytest.fixture
    def source(self):
        """Create ClinicalTrialsSource instance."""
        return ClinicalTrialsSource()

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    def test_source_prefix(self, source):
        """Test source prefix is 'clinicaltrials' (bioregistry standard)."""
        assert source.prefix() == "clinicaltrials"

    def test_can_handle_various_formats(self, source):
        """Test can_handle accepts various clinical trials ID formats."""
        # Prefixed formats (bioregistry standard)
        assert source.can_handle("clinicaltrials:NCT00000001")
        assert source.can_handle("clinicaltrials:NCT12345678")

        # Bare NCT ID
        assert source.can_handle("NCT00000001")
        assert source.can_handle("NCT12345678")

        # With prefix, any identifier is accepted (validation happens during fetch)
        assert source.can_handle("clinicaltrials:12345")

        # Other prefixes should not be handled
        assert not source.can_handle("PMID:12345678")
        assert not source.can_handle("DOI:10.1234/test")
        assert not source.can_handle("GSE12345")


@pytest.mark.integration
class TestClinicalTrialsLiveAPI:
    """Live API tests for ClinicalTrials.gov.

    These tests make real network requests and are marked with @pytest.mark.integration.
    Run with: pytest -m integration
    Skip with: pytest -m "not integration"
    """

    @pytest.fixture
    def source(self):
        """Create ClinicalTrialsSource instance."""
        return ClinicalTrialsSource()

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config with reasonable rate limiting."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.5,  # Be respectful to the API
        )

    def test_fetch_real_clinical_trial(self, source, config):
        """Test fetching a real clinical trial from ClinicalTrials.gov API.

        Uses NCT00001372 - a real, completed trial that should be stable.
        """
        result = source.fetch("NCT00001372", config)

        assert result is not None
        assert result.reference_id == "clinicaltrials:NCT00001372"
        assert result.title is not None
        assert len(result.title) > 0
        assert result.content is not None
        assert len(result.content) > 0
        assert result.content_type == "summary"

    def test_fetch_nonexistent_trial(self, source, config):
        """Test fetching a nonexistent NCT ID returns None."""
        result = source.fetch("NCT99999999", config)

        assert result is None
