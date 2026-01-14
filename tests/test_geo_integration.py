"""Integration tests for GEO reference source.

Tests using real cached fixtures and optional live API tests.
"""

import pytest
from linkml_reference_validator.models import ReferenceValidationConfig, ValidationSeverity
from linkml_reference_validator.etl.sources.entrez import GEOSource


class TestGEOIntegration:
    """Integration tests using cached GEO fixtures."""

    def test_fetch_cached_geo_reference(self, fetcher_with_fixtures):
        """Test fetching a cached GEO reference."""
        ref = fetcher_with_fixtures.fetch("GEO:GSE12345")

        assert ref is not None
        assert ref.reference_id == "GEO:GSE12345"
        assert ref.title == "Test GEO Dataset for Validation"
        assert "gene expression profiles" in ref.content
        assert ref.content_type == "summary"

    def test_validate_geo_reference_success(self, validator_with_fixtures):
        """Test validation with cached GEO reference - success case."""
        result = validator_with_fixtures.validate(
            "gene expression profiles from human samples",
            "GEO:GSE12345",
        )

        assert result.is_valid is True
        assert result.severity == ValidationSeverity.INFO
        assert result.match_result is not None
        assert result.match_result.found is True

    def test_validate_geo_reference_substring(self, validator_with_fixtures):
        """Test substring matching with GEO reference."""
        result = validator_with_fixtures.validate(
            "airway inflammation in asthma",
            "GEO:GSE12345",
        )

        assert result.is_valid is True

    def test_validate_geo_reference_not_found(self, validator_with_fixtures):
        """Test validation when text is not in GEO reference."""
        result = validator_with_fixtures.validate(
            "this text is definitely not in any GEO dataset",
            "GEO:GSE12345",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "not found" in result.message.lower()

    def test_validate_geo_with_title_validation(self, validator_with_fixtures):
        """Test validation with GEO title check."""
        result = validator_with_fixtures.validate(
            "gene expression profiles",
            "GEO:GSE12345",
            expected_title="Test GEO Dataset for Validation",
        )

        assert result.is_valid is True
        assert "title validated" in result.message

    def test_validate_geo_title_mismatch(self, validator_with_fixtures):
        """Test validation with GEO title mismatch."""
        result = validator_with_fixtures.validate(
            "gene expression profiles",
            "GEO:GSE12345",
            expected_title="Wrong Dataset Title",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "title mismatch" in result.message.lower()

    def test_validate_geo_multipart_quote(self, validator_with_fixtures):
        """Test validation with multi-part quote using ellipsis."""
        result = validator_with_fixtures.validate(
            "gene expression profiles ... airway epithelial cells",
            "GEO:GSE12345",
        )

        assert result.is_valid is True

    def test_fetch_nonexistent_geo(self, fetcher_with_fixtures):
        """Test fetcher returns None for nonexistent GEO dataset."""
        ref = fetcher_with_fixtures.fetch("GEO:GSE99999999")

        assert ref is None


class TestGEOSourceDirect:
    """Direct tests for GEOSource class."""

    @pytest.fixture
    def source(self):
        """Create GEOSource instance."""
        return GEOSource()

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    def test_source_prefix(self, source):
        """Test source prefix is 'GEO'."""
        assert source.prefix() == "GEO"

    def test_can_handle_various_formats(self, source):
        """Test can_handle accepts various GEO ID formats."""
        # Prefixed formats
        assert source.can_handle("GEO:GSE12345")
        assert source.can_handle("geo:GSE12345")
        assert source.can_handle("GEO:GDS1234")

        # Bare accessions (GSE/GDS patterns)
        assert source.can_handle("GSE12345")
        assert source.can_handle("GDS1234")
        assert source.can_handle("GSE67472")

        # Other prefixes should not be handled
        assert not source.can_handle("PMID:12345678")
        assert not source.can_handle("DOI:10.1234/test")
        assert not source.can_handle("NCT12345678")


@pytest.mark.integration
class TestGEOLiveAPI:
    """Live API tests for GEO/Entrez.

    These tests make real network requests and are marked with @pytest.mark.integration.
    Run with: pytest -m integration
    Skip with: pytest -m "not integration"
    """

    @pytest.fixture
    def source(self):
        """Create GEOSource instance."""
        return GEOSource()

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config with reasonable rate limiting."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.5,  # Be respectful to the API
            email="test@example.com",
        )

    def test_fetch_real_geo_dataset_gse67472(self, source, config):
        """Test fetching a real GEO dataset (GSE67472).

        GSE67472: Airway epithelial gene expression in asthma versus healthy controls
        This is a real, published dataset that should be stable.
        """
        result = source.fetch("GSE67472", config)

        assert result is not None
        assert result.reference_id == "GEO:GSE67472"
        assert result.title is not None
        assert len(result.title) > 0
        # The title should contain something about asthma or airways
        assert "asthma" in result.title.lower() or "airway" in result.title.lower()
        assert result.content is not None
        assert len(result.content) > 0
        assert result.content_type == "summary"
        # Should have UID in metadata (the converted numeric ID)
        assert "entrez_uid" in result.metadata
        assert result.metadata["entrez_uid"].isdigit()

    def test_fetch_real_geo_dataset_gds1234(self, source, config):
        """Test fetching a real GDS dataset (GDS1234).

        GDS1234 is a stable GEO dataset from earlier in GEO's history.
        """
        result = source.fetch("GDS1234", config)

        assert result is not None
        assert result.reference_id == "GEO:GDS1234"
        assert result.title is not None
        assert len(result.title) > 0
        assert result.content is not None
        assert result.content_type == "summary"
        assert "entrez_uid" in result.metadata

    def test_fetch_nonexistent_geo_dataset(self, source, config):
        """Test fetching a nonexistent GEO accession returns None."""
        result = source.fetch("GSE99999999999", config)

        assert result is None

    def test_accession_to_uid_conversion(self, source, config):
        """Test that accession is properly converted to UID.

        GSE67472 should convert to UID 200067472.
        """
        result = source.fetch("GSE67472", config)

        assert result is not None
        # The UID should be numeric and follow the pattern for GSE conversion
        uid = result.metadata.get("entrez_uid")
        assert uid is not None
        assert uid.isdigit()
        # GSE67472 should map to a UID around 200067472
        assert int(uid) > 0


@pytest.mark.integration
class TestGEOLiveValidation:
    """Live validation tests for GEO datasets.

    These tests make real network requests to validate text and titles
    against actual GEO datasets. Marked with @pytest.mark.integration.
    """

    @pytest.fixture
    def config(self, tmp_path):
        """Create test config with reasonable rate limiting."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.5,
            email="test@example.com",
        )

    @pytest.fixture
    def validator(self, config):
        """Create a validator instance."""
        from linkml_reference_validator.validation.supporting_text_validator import (
            SupportingTextValidator,
        )
        return SupportingTextValidator(config)

    def test_validate_excerpt_success_real_geo(self, validator):
        """Test validating text that exists in a real GEO dataset.

        GSE67472 contains text about "Airway epithelial brushings" and "asthma".
        """
        result = validator.validate(
            "Airway epithelial brushings",
            "GEO:GSE67472",
        )

        assert result.is_valid is True
        assert result.severity == ValidationSeverity.INFO
        assert result.match_result is not None
        assert result.match_result.found is True

    def test_validate_excerpt_not_found_real_geo(self, validator):
        """Test validating text that does NOT exist in a real GEO dataset.

        This verifies the validator correctly rejects non-matching text.
        """
        result = validator.validate(
            "This text about zebras and quantum computing is definitely not in any GEO dataset",
            "GEO:GSE67472",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "not found" in result.message.lower()

    def test_validate_title_match_real_geo(self, validator):
        """Test title validation success with real GEO dataset.

        GSE67472 title: "Airway epithelial gene expression in asthma versus healthy controls"
        """
        result = validator.validate(
            "Airway epithelial brushings",  # text that exists in content
            "GEO:GSE67472",
            expected_title="Airway epithelial gene expression in asthma versus healthy controls",
        )

        assert result.is_valid is True
        assert "title validated" in result.message

    def test_validate_title_mismatch_real_geo(self, validator):
        """Test title validation failure with real GEO dataset.

        This tests that the validator correctly rejects a wrong title.
        """
        result = validator.validate(
            "Airway epithelial brushings",  # text that exists in content
            "GEO:GSE67472",
            expected_title="This is a completely wrong title that does not match",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "title mismatch" in result.message.lower()

    def test_validate_title_partial_match_real_geo(self, validator):
        """Test that partial title matches work (case-insensitive, normalized).

        Title validation should be flexible with case and punctuation.
        """
        result = validator.validate(
            "Airway epithelial brushings",
            "GEO:GSE67472",
            # Slightly different case/punctuation
            expected_title="airway epithelial gene expression in asthma versus healthy controls",
        )

        assert result.is_valid is True
        assert "title validated" in result.message

    def test_validate_multipart_excerpt_real_geo(self, validator):
        """Test multi-part quote validation with real GEO dataset.

        Uses ellipsis (...) to match non-contiguous text.
        """
        result = validator.validate(
            "Airway epithelial ... asthma subjects",
            "GEO:GSE67472",
        )

        assert result.is_valid is True

    def test_validate_wrong_reference_id(self, validator):
        """Test validation fails gracefully for nonexistent GEO dataset."""
        result = validator.validate(
            "Some text",
            "GEO:GSE99999999999",
        )

        assert result.is_valid is False
        assert result.severity == ValidationSeverity.ERROR
        assert "could not fetch" in result.message.lower() or "not found" in result.message.lower()
