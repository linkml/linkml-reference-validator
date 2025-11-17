"""Tests for data models and configuration."""

from pathlib import Path
from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ReferenceContent,
    SupportingTextMatch,
    ValidationResult,
    ValidationReport,
    ValidationSeverity,
)


def test_config_defaults():
    """Test default configuration values."""
    config = ReferenceValidationConfig()
    assert config.cache_dir == Path("references_cache")
    assert config.rate_limit_delay == 0.5


def test_config_custom_values():
    """Test configuration with custom values."""
    config = ReferenceValidationConfig(
        cache_dir=Path("/tmp/cache"),
        rate_limit_delay=1.0,
    )
    assert config.cache_dir == Path("/tmp/cache")
    assert config.rate_limit_delay == 1.0


def test_config_get_cache_dir(tmp_path):
    """Test cache directory creation."""
    cache_dir = tmp_path / "test_cache"
    config = ReferenceValidationConfig(cache_dir=cache_dir)
    result_dir = config.get_cache_dir()
    assert result_dir == cache_dir
    assert result_dir.exists()


def test_reference_content_creation():
    """Test creating a ReferenceContent object."""
    ref = ReferenceContent(
        reference_id="PMID:12345678",
        title="Test Article",
        content="This is the abstract and full text.",
        content_type="full_text",
        authors=["Smith J", "Doe A"],
        journal="Nature",
        year="2024",
    )
    assert ref.reference_id == "PMID:12345678"
    assert ref.title == "Test Article"
    assert ref.content_type == "full_text"
    assert len(ref.authors) == 2


def test_supporting_text_match():
    """Test SupportingTextMatch creation."""
    match = SupportingTextMatch(
        found=True,
        similarity_score=1.0,
        matched_text="protein functions in cells",
        match_location="abstract",
    )
    assert match.found is True
    assert match.similarity_score == 1.0
    assert match.matched_text == "protein functions in cells"


def test_validation_result():
    """Test ValidationResult creation."""
    result = ValidationResult(
        is_valid=True,
        reference_id="PMID:12345678",
        supporting_text="test quote",
        severity=ValidationSeverity.INFO,
        message="Validation passed",
    )
    assert result.is_valid is True
    assert result.reference_id == "PMID:12345678"
    assert result.severity == ValidationSeverity.INFO


def test_validation_report():
    """Test ValidationReport functionality."""
    report = ValidationReport()
    assert report.total_validations == 0
    assert report.valid_count == 0
    assert report.invalid_count == 0
    assert report.is_valid is True


def test_validation_report_add_results():
    """Test adding results to validation report."""
    report = ValidationReport()

    report.add_result(
        ValidationResult(
            is_valid=True,
            reference_id="PMID:1",
            supporting_text="test",
            severity=ValidationSeverity.INFO,
        )
    )

    report.add_result(
        ValidationResult(
            is_valid=False,
            reference_id="PMID:2",
            supporting_text="test",
            severity=ValidationSeverity.ERROR,
        )
    )

    report.add_result(
        ValidationResult(
            is_valid=False,
            reference_id="PMID:3",
            supporting_text="test",
            severity=ValidationSeverity.WARNING,
        )
    )

    assert report.total_validations == 3
    assert report.valid_count == 1
    assert report.invalid_count == 2
    assert report.error_count == 1
    assert report.warning_count == 1
    assert report.is_valid is False  # Has errors
