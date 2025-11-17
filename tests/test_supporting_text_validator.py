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
