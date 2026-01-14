"""Tests for supporting text validator."""

import pytest
from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ReferenceContent,
    ValidationSeverity,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)


@pytest.fixture
def config(tmp_path):
    """Create a test configuration."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
    )


@pytest.fixture
def validator(config):
    """Create a validator."""
    return SupportingTextValidator(config)


def test_validator_initialization(validator):
    """Test validator initialization."""
    assert validator.config is not None
    assert validator.fetcher is not None


def test_normalize_text(validator):
    """Test text normalization."""
    assert validator.normalize_text("Hello, World!") == "hello world"
    assert validator.normalize_text("T-Cell Receptor") == "t cell receptor"
    assert validator.normalize_text("  Multiple   Spaces  ") == "multiple spaces"
    assert validator.normalize_text("CamelCase") == "camelcase"


@pytest.mark.parametrize(
    "input_text,expected",
    [
        # Basic Greek letters
        ("α-catenin", "alpha catenin"),
        ("β-actin", "beta actin"),
        ("γ-tubulin", "gamma tubulin"),
        ("δ-opioid", "delta opioid"),
        # Uppercase Greek letters
        ("Α-catenin", "alpha catenin"),
        ("Β-actin", "beta actin"),
        ("Γ-tubulin", "gamma tubulin"),
        ("Δ-opioid", "delta opioid"),
        # More Greek letters
        ("ε-toxin", "epsilon toxin"),
        ("θ-defensin", "theta defensin"),
        ("κ-casein", "kappa casein"),
        ("λ-phage", "lambda phage"),
        ("μ-opioid", "mu opioid"),
        ("π-helix", "pi helix"),
        ("σ-factor", "sigma factor"),
        ("ω-3 fatty acid", "omega 3 fatty acid"),
        # Special sigma variant
        ("ς-factor", "sigma factor"),
        # Multiple Greek letters
        ("α-β complex", "alpha beta complex"),
        # Greek letter in compound name (no separator, so spelled form is adjacent)
        ("ΔNp63", "deltanp63"),
        # Ensure distinction between different Greek letters
        ("α-catenin vs β-catenin", "alpha catenin vs beta catenin"),
    ],
)
def test_normalize_greek_letters(validator, input_text, expected):
    """Test that Greek letters are spelled out correctly."""
    assert validator.normalize_text(input_text) == expected


def test_split_query_simple(validator):
    """Test splitting simple query."""
    parts = validator._split_query("protein functions in cells")
    assert parts == ["protein functions in cells"]


def test_split_query_with_ellipsis(validator):
    """Test splitting query with ellipsis."""
    parts = validator._split_query("protein functions ... in cells")
    assert parts == ["protein functions", "in cells"]


def test_split_query_with_brackets(validator):
    """Test splitting query with editorial brackets."""
    parts = validator._split_query("protein [important] functions")
    assert len(parts) == 1
    assert "important" not in parts[0]


def test_substring_match_found(validator):
    """Test substring matching when text is found."""
    match = validator._substring_match(
        ["protein functions in cell cycle"],
        "The protein functions in cell cycle regulation.",
    )
    assert match.found is True
    assert match.similarity_score == 1.0


def test_substring_match_not_found(validator):
    """Test substring matching when text is not found."""
    match = validator._substring_match(
        ["protein inhibits apoptosis"],
        "The protein functions in cell cycle regulation.",
    )
    assert match.found is False
    assert match.similarity_score == 0.0


def test_find_text_in_reference_exact(validator):
    """Test finding exact text in reference."""
    ref = ReferenceContent(
        reference_id="PMID:123",
        content="The protein functions in cell cycle regulation.",
    )

    match = validator.find_text_in_reference("protein functions", ref)
    assert match.found is True
    assert match.similarity_score == 1.0


def test_find_text_in_reference_not_found(validator):
    """Test when text is not found in reference."""
    ref = ReferenceContent(
        reference_id="PMID:123",
        content="The protein functions in cell cycle regulation.",
    )

    match = validator.find_text_in_reference("inhibits apoptosis", ref)
    assert match.found is False


def test_find_text_no_content(validator):
    """Test finding text when reference has no content."""
    ref = ReferenceContent(
        reference_id="PMID:123",
        content=None,
    )

    match = validator.find_text_in_reference("some text", ref)
    assert match.found is False
    assert "no content" in match.error_message.lower()


def test_find_text_empty_query_after_brackets(validator):
    """Test that empty query after removing brackets returns error."""
    ref = ReferenceContent(
        reference_id="PMID:123",
        content="The protein functions in cell cycle regulation.",
    )

    match = validator.find_text_in_reference("[editorial note only]", ref)
    assert match.found is False
    assert "empty" in match.error_message.lower()


def test_validate_success(validator, mocker):
    """Test successful validation."""
    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = ReferenceContent(
        reference_id="PMID:123",
        content="The protein functions in cell cycle regulation.",
    )

    result = validator.validate(
        "protein functions in cell cycle",
        "PMID:123",
    )

    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO


def test_validate_not_found(validator, mocker):
    """Test validation when text not found."""
    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = ReferenceContent(
        reference_id="PMID:123",
        content="The protein functions in cell cycle regulation.",
    )

    result = validator.validate(
        "inhibits apoptosis",
        "PMID:123",
    )

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR


def test_validate_reference_not_found(validator, mocker):
    """Test validation when reference cannot be fetched."""
    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    result = validator.validate(
        "some text",
        "PMID:99999",
    )

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR
    assert "Could not fetch" in result.message


def test_validate_no_content(validator, mocker):
    """Test validation when reference has no content."""
    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = ReferenceContent(
        reference_id="PMID:123",
        content=None,
    )

    result = validator.validate(
        "some text",
        "PMID:123",
    )

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR
    assert "No content available" in result.message


def test_greek_letter_matching_greek_to_spelled(validator):
    """Test matching Greek letters in query against spelled-out text in reference."""
    ref = ReferenceContent(
        reference_id="PMID:123",
        content="The alpha-catenin protein is important for cell adhesion.",
    )

    match = validator.find_text_in_reference("α-catenin protein", ref)
    assert match.found is True
    assert match.similarity_score == 1.0


def test_greek_letter_matching_spelled_to_greek(validator):
    """Test matching spelled-out query against Greek letters in reference."""
    ref = ReferenceContent(
        reference_id="PMID:123",
        content="The α-catenin protein is important for cell adhesion.",
    )

    match = validator.find_text_in_reference("alpha-catenin protein", ref)
    assert match.found is True
    assert match.similarity_score == 1.0


def test_greek_letter_distinction(validator):
    """Test that different Greek letters are distinguished correctly."""
    ref = ReferenceContent(
        reference_id="PMID:123",
        content="Both alpha-catenin and beta-catenin play important roles.",
    )

    # Should find alpha-catenin
    match_alpha = validator.find_text_in_reference("α-catenin", ref)
    assert match_alpha.found is True

    # Should find beta-catenin
    match_beta = validator.find_text_in_reference("β-catenin", ref)
    assert match_beta.found is True

    # Both should be present (not collapsed to just "catenin")
    match_both = validator.find_text_in_reference("alpha-catenin and beta-catenin", ref)
    assert match_both.found is True


def test_validate_abstract_only_context_in_failure_message(validator, mocker):
    """Test that failure message includes abstract-only context when applicable.

    When validation fails and only abstract was available, the error message
    should indicate this so users know the excerpt may exist in the full text.
    """
    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = ReferenceContent(
        reference_id="PMID:123",
        content="This is just the abstract text.",
        content_type="abstract_only",
    )

    result = validator.validate(
        "text from the full paper introduction",
        "PMID:123",
    )

    assert result.is_valid is False
    assert "only abstract available" in result.message
    assert "full text may contain this excerpt" in result.message


def test_validate_full_text_no_abstract_context_in_failure_message(validator, mocker):
    """Test that failure message does NOT include abstract-only context for full text.

    When validation fails but full text was available, the message should
    not mention abstract-only limitation.
    """
    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = ReferenceContent(
        reference_id="PMID:123",
        content="This is the full text of the paper including introduction and methods.",
        content_type="full_text_xml",
    )

    result = validator.validate(
        "text that does not exist anywhere",
        "PMID:123",
    )

    assert result.is_valid is False
    assert "only abstract available" not in result.message


def test_skip_prefixes_single_prefix(tmp_path, mocker):
    """Test that references with skipped prefixes return INFO severity.

    When a reference prefix is in the skip_prefixes list, validation should
    return is_valid=True with INFO severity instead of ERROR.
    """
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA"],
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None  # Simulate unfetchable reference

    result = validator.validate(
        "some supporting text",
        "SRA:PRJNA290729",
    )

    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO
    assert "Skipping validation" in result.message
    assert "SRA:PRJNA290729" in result.message


def test_skip_prefixes_multiple_prefixes(tmp_path, mocker):
    """Test that multiple prefixes can be skipped."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA", "MGNIFY", "BIOPROJECT"],
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    # Test SRA
    result_sra = validator.validate("text", "SRA:PRJNA290729")
    assert result_sra.is_valid is True
    assert result_sra.severity == ValidationSeverity.INFO

    # Test MGNIFY
    result_mgnify = validator.validate("text", "MGNIFY:MGYS00000596")
    assert result_mgnify.is_valid is True
    assert result_mgnify.severity == ValidationSeverity.INFO

    # Test BIOPROJECT
    result_bioproject = validator.validate("text", "BIOPROJECT:PRJNA566284")
    assert result_bioproject.is_valid is True
    assert result_bioproject.severity == ValidationSeverity.INFO


def test_skip_prefixes_case_insensitive(tmp_path, mocker):
    """Test that prefix matching is case-insensitive."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["sra"],  # lowercase in config
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    # Test with uppercase prefix in reference
    result = validator.validate("text", "SRA:PRJNA290729")
    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO


def test_skip_prefixes_not_skipped(tmp_path, mocker):
    """Test that references NOT in skip list still get ERROR."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA"],
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    # MGNIFY is not in skip list, should get ERROR
    result = validator.validate("text", "MGNIFY:MGYS00000596")
    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR


def test_unknown_prefix_severity_warning(tmp_path, mocker):
    """Test that unknown_prefix_severity=WARNING downgrades unfetchable references.

    When a reference cannot be fetched and unknown_prefix_severity is WARNING,
    the validation should return is_valid=False with WARNING severity.
    """
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        unknown_prefix_severity=ValidationSeverity.WARNING,
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    result = validator.validate("text", "UNKNOWN:12345")
    assert result.is_valid is False
    assert result.severity == ValidationSeverity.WARNING
    assert "Could not fetch reference" in result.message


def test_unknown_prefix_severity_info(tmp_path, mocker):
    """Test that unknown_prefix_severity=INFO further downgrades unfetchable references."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        unknown_prefix_severity=ValidationSeverity.INFO,
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    result = validator.validate("text", "BIOPROJECT:PRJNA566284")
    assert result.is_valid is False
    assert result.severity == ValidationSeverity.INFO


def test_unknown_prefix_severity_default_error(tmp_path, mocker):
    """Test that default behavior is ERROR for unfetchable references."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        # No unknown_prefix_severity specified, should default to ERROR
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    result = validator.validate("text", "UNKNOWN:12345")
    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR


def test_skip_prefixes_takes_precedence_over_unknown_severity(tmp_path, mocker):
    """Test that skip_prefixes takes precedence over unknown_prefix_severity.

    When a prefix is in skip_prefixes, it should return INFO with is_valid=True,
    regardless of the unknown_prefix_severity setting.
    """
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA"],
        unknown_prefix_severity=ValidationSeverity.ERROR,  # This should be ignored for SRA
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    result = validator.validate("text", "SRA:PRJNA290729")
    assert result.is_valid is True  # skip_prefixes makes it valid
    assert result.severity == ValidationSeverity.INFO


def test_combined_skip_and_severity_config(tmp_path, mocker):
    """Test that skip_prefixes and unknown_prefix_severity work together.

    Skipped prefixes get INFO with is_valid=True.
    Non-skipped unfetchable references get the configured severity.
    """
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA"],
        unknown_prefix_severity=ValidationSeverity.WARNING,
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    # SRA is skipped
    result_sra = validator.validate("text", "SRA:PRJNA290729")
    assert result_sra.is_valid is True
    assert result_sra.severity == ValidationSeverity.INFO

    # MGNIFY is not skipped, gets WARNING
    result_mgnify = validator.validate("text", "MGNIFY:MGYS00000596")
    assert result_mgnify.is_valid is False
    assert result_mgnify.severity == ValidationSeverity.WARNING


def test_skip_prefixes_with_fetchable_reference(tmp_path, mocker):
    """Test that skip_prefixes is checked before attempting fetch.

    Even if a source exists for a skipped prefix, it should be skipped.
    """
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["PMID"],  # Skip even valid PMID references
    )
    validator = SupportingTextValidator(config)

    # Mock should not be called since we skip before fetching
    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = ReferenceContent(
        reference_id="PMID:123",
        content="Some content",
    )

    result = validator.validate("text", "PMID:123")
    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO
    # Note: fetch should still be called, but the result is ignored
    assert "Skipping validation" in result.message


# =============================================================================
# validate_title tests
# =============================================================================


def test_validate_title_skip_prefixes(tmp_path, mocker):
    """Test that validate_title respects skip_prefixes configuration.

    When a reference prefix is in the skip_prefixes list, validate_title should
    return is_valid=True with INFO severity instead of attempting to fetch.
    """
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA"],
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    result = validator.validate_title(
        "SRA:PRJNA290729",
        "Some Dataset Title",
    )

    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO
    assert "Skipping" in result.message
    assert "SRA" in result.message
    # Fetch should not be called when prefix is skipped
    mock_fetch.assert_not_called()


def test_validate_title_skip_prefixes_multiple(tmp_path, mocker):
    """Test that validate_title handles multiple skip_prefixes."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA", "MGNIFY", "BIOPROJECT"],
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    # Test each prefix
    for prefix, ref_id in [
        ("SRA", "SRA:PRJNA290729"),
        ("MGNIFY", "MGNIFY:MGYS00000596"),
        ("BIOPROJECT", "BIOPROJECT:PRJNA566284"),
    ]:
        result = validator.validate_title(ref_id, "Some Title")
        assert result.is_valid is True, f"Failed for {prefix}"
        assert result.severity == ValidationSeverity.INFO, f"Failed for {prefix}"
        assert "Skipping" in result.message, f"Failed for {prefix}"


def test_validate_title_skip_prefixes_case_insensitive(tmp_path, mocker):
    """Test that validate_title prefix matching is case-insensitive."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["sra"],  # lowercase in config
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    # Test with uppercase prefix in reference
    result = validator.validate_title("SRA:PRJNA290729", "Some Title")
    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO


def test_validate_title_unknown_prefix_severity(tmp_path, mocker):
    """Test that validate_title uses unknown_prefix_severity for unfetchable refs.

    When a reference cannot be fetched and is not in skip_prefixes,
    the severity should match the configured unknown_prefix_severity.
    """
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        unknown_prefix_severity=ValidationSeverity.WARNING,
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    result = validator.validate_title("MGNIFY:MGYS00000596", "Some Title")
    assert result.is_valid is False
    assert result.severity == ValidationSeverity.WARNING


def test_validate_title_unknown_prefix_severity_default_error(tmp_path, mocker):
    """Test that validate_title defaults to ERROR for unfetchable refs."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        # unknown_prefix_severity defaults to ERROR
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    result = validator.validate_title("UNKNOWN:12345", "Some Title")
    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR


def test_validate_title_skip_prefixes_takes_precedence(tmp_path, mocker):
    """Test that skip_prefixes takes precedence over unknown_prefix_severity."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA"],
        unknown_prefix_severity=ValidationSeverity.ERROR,
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = None

    # SRA is skipped, should return INFO with is_valid=True
    result = validator.validate_title("SRA:PRJNA290729", "Some Title")
    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO


def test_validate_title_normal_flow_still_works(tmp_path, mocker):
    """Test that validate_title still works normally for non-skipped prefixes."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["SRA"],
    )
    validator = SupportingTextValidator(config)

    mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
    mock_fetch.return_value = ReferenceContent(
        reference_id="PMID:123",
        title="The Expected Title",
        content="Some content",
    )

    # PMID is not skipped, should validate normally
    result = validator.validate_title("PMID:123", "The Expected Title")
    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO
    mock_fetch.assert_called_once()
