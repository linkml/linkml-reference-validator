"""Tests using real cached references instead of mocks."""

from linkml_reference_validator.models import ValidationSeverity


def test_validate_with_real_reference_success(validator_with_fixtures):
    """Test validation with real cached reference - success case."""
    result = validator_with_fixtures.validate(
        "Protein X functions in cell cycle regulation and plays a critical role in DNA repair",
        "PMID:TEST001",
    )

    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO
    assert "validated" in result.message.lower()
    assert result.match_result is not None
    assert result.match_result.found is True


def test_validate_with_title_validation_success(validator_with_fixtures):
    """Test validation with title check - success case."""
    result = validator_with_fixtures.validate(
        "Protein X functions in cell cycle regulation and plays a critical role",
        "PMID:TEST001",
        expected_title="Protein X functions in cell cycle regulation",
    )

    assert result.is_valid is True
    assert "title validated" in result.message


def test_validate_with_title_mismatch(validator_with_fixtures):
    """Test validation with title mismatch."""
    result = validator_with_fixtures.validate(
        "Protein X functions in cell cycle regulation and plays a critical role",
        "PMID:TEST001",
        expected_title="Wrong Title",
    )

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR
    assert "title mismatch" in result.message.lower()


def test_validate_text_not_found(validator_with_fixtures):
    """Test validation when text is not in reference."""
    result = validator_with_fixtures.validate(
        "this text is definitely not in the reference at all",
        "PMID:TEST001",
    )

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR
    assert "not found" in result.message.lower()


def test_validate_substring_parts_match(validator_with_fixtures):
    """Test substring matching with all parts present."""
    # All these substrings should be found independently
    result = validator_with_fixtures.validate(
        "Protein X functions in cell cycle regulation",
        "PMID:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.similarity_score == 1.0


def test_validate_multi_part_quote(validator_with_fixtures):
    """Test validation with multi-part quote using ... separator."""
    result = validator_with_fixtures.validate(
        "Protein X functions ... plays a critical role",
        "PMID:TEST001",
    )

    assert result.is_valid is True


def test_validate_with_editorial_brackets(validator_with_fixtures):
    """Test validation with editorial notes in brackets."""
    result = validator_with_fixtures.validate(
        "Protein X [also known as PROT-X] functions in cell cycle regulation",
        "PMID:TEST001",
    )

    # Should match even with editorial notes
    assert result.is_valid is True


def test_validate_full_text_reference(validator_with_fixtures):
    """Test validation against reference with full text."""
    result = validator_with_fixtures.validate(
        "Protein Y inhibits apoptosis through direct interaction with caspase-3",
        "PMID:TEST002",
    )

    assert result.is_valid is True
    assert result.match_result.found is True


def test_validate_with_longer_full_text(validator_with_fixtures):
    """Test validation against longer full text content."""
    result = validator_with_fixtures.validate(
        "gene Z is required for neuronal differentiation",
        "PMID:TEST003",
    )

    assert result.is_valid is True


def test_substring_requires_exact_words(validator_with_fixtures):
    """Test substring matching requires exact word match after normalization."""
    # "operates" is not in the text, should fail
    result = validator_with_fixtures.validate(
        "Protein X operates in cell cycle regulation",  # "operates" instead of "functions"
        "PMID:TEST001",
    )

    assert result.is_valid is False


def test_reference_fetcher_loads_from_cache(fetcher_with_fixtures):
    """Test that fetcher loads references from cache."""
    ref = fetcher_with_fixtures.fetch("PMID:TEST001")

    assert ref is not None
    assert ref.reference_id == "PMID:TEST001"
    assert ref.title == "Protein X functions in cell cycle regulation"
    assert "cell cycle regulation" in ref.content
    assert ref.authors == ["Smith J", "Doe A", "Johnson K"]
    assert ref.journal == "Nature Cell Biology"
    assert ref.year == "2024"


def test_reference_fetcher_handles_missing(fetcher_with_fixtures):
    """Test fetcher returns None for missing references."""
    ref = fetcher_with_fixtures.fetch("PMID:NONEXISTENT")

    assert ref is None


def test_validate_multiple_references(validator_with_fixtures):
    """Test validating against multiple different references."""
    # First reference
    result1 = validator_with_fixtures.validate(
        "Protein X functions in cell cycle regulation",
        "PMID:TEST001",
    )
    assert result1.is_valid is True

    # Second reference
    result2 = validator_with_fixtures.validate(
        "Protein Y inhibits apoptosis",
        "PMID:TEST002",
    )
    assert result2.is_valid is True

    # Third reference
    result3 = validator_with_fixtures.validate(
        "gene Z expression patterns vary significantly",
        "PMID:TEST003",
    )
    assert result3.is_valid is True


def test_validate_preserves_path_info(validator_with_fixtures):
    """Test that validation preserves path information."""
    result = validator_with_fixtures.validate(
        "protein functions",
        "PMID:TEST001",
        path="evidence[0].supporting_text",
    )

    assert result.path == "evidence[0].supporting_text"
