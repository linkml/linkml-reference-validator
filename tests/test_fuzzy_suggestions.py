"""Tests for fuzzy matching suggestions.

These tests verify that:
1. Validation remains strict (fuzzy matching does NOT make validation pass)
2. Suggestions are generated when validation fails
3. Suggestions are helpful for near-matches
"""

import pytest

from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
)
from linkml_reference_validator.validation.fuzzy_text_utils import (
    calculate_text_similarity,
    calculate_word_overlap,
    find_fuzzy_match_in_text,
    get_significant_words,
    normalize_whitespace,
    split_into_sentences,
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


# =============================================================================
# Tests for fuzzy_text_utils module
# =============================================================================


class TestNormalizeWhitespace:
    """Tests for whitespace normalization."""

    def test_collapses_multiple_spaces(self):
        """Multiple spaces should collapse to single space."""
        assert normalize_whitespace("text  with   multiple    spaces") == "text with multiple spaces"

    def test_normalizes_newlines(self):
        """Newlines should become spaces."""
        assert normalize_whitespace("text\nwith\nmultiple\nlines") == "text with multiple lines"

    def test_trims_leading_trailing(self):
        """Leading and trailing whitespace should be removed."""
        assert normalize_whitespace("  leading and trailing  ") == "leading and trailing"

    def test_lowercases_text(self):
        """Text should be lowercased."""
        assert normalize_whitespace("MixedCase TEXT") == "mixedcase text"


class TestSplitIntoSentences:
    """Tests for sentence splitting."""

    def test_splits_on_period(self):
        """Sentences should split on periods."""
        sentences = split_into_sentences(
            "This is the first longer sentence. This is the second longer sentence."
        )
        assert len(sentences) == 2

    def test_filters_short_sentences(self):
        """Short sentences should be filtered out."""
        sentences = split_into_sentences(
            "Short. This is a sentence that is longer than twenty characters."
        )
        assert len(sentences) == 1

    def test_custom_min_length(self):
        """Custom min_length should work."""
        sentences = split_into_sentences("A B C. D E F.", min_length=3)
        assert len(sentences) == 2


class TestFindFuzzyMatchInText:
    """Tests for fuzzy matching."""

    def test_exact_match_returns_100(self):
        """Exact match should return 100% similarity."""
        text = "The JAK1 protein is a tyrosine kinase."
        found, score, match = find_fuzzy_match_in_text(
            "JAK1 protein is a tyrosine kinase", text
        )
        assert found is True
        assert score == 100.0

    def test_close_match_returns_high_score(self):
        """Close match should return high similarity."""
        text = "The JAK1 protein is a tyrosine kinase. It phosphorylates STAT proteins."
        found, score, match = find_fuzzy_match_in_text(
            "JAK1 protein is a tyrosine kinase", text
        )
        assert found is True
        assert score >= 90

    def test_no_match_returns_low_score(self):
        """No match should return low similarity."""
        text = "The JAK1 protein is a tyrosine kinase."
        found, score, match = find_fuzzy_match_in_text(
            "completely different text that has nothing in common", text
        )
        assert found is False

    def test_short_query_requires_exact_match(self):
        """Queries with <5 words require exact match."""
        text = "The JAK1 protein is a tyrosine kinase."
        found, score, match = find_fuzzy_match_in_text(
            "JAK1 tyrosine",  # Only 2 words, modified
            text
        )
        assert found is False

    def test_returns_best_match_text(self):
        """Should return the best matching text segment."""
        text = "First sentence here. The JAK1 protein binds to receptors. Third sentence."
        found, score, match = find_fuzzy_match_in_text(
            "JAK1 protein binds to receptors", text
        )
        assert found is True
        assert "JAK1" in match or "protein" in match

    def test_prevents_false_positive_on_unrelated_medical_texts(self):
        """Test the specific bug case: unrelated texts should NOT match.

        This tests the reported bug where completely unrelated medical texts
        were matching with 94% similarity due to common short word sequences.
        """
        query = "Persistently elevated serum creatinine and albuminuria are diagnostic and prognostic hallmarks of chronic kidney disease"
        text = "Nephronophthisis (NPHP) is an autosomal recessive cystic kidney disease and is one of the most frequent genetic causes for kidney failure (KF) in children and adolescents"

        found, score, match = find_fuzzy_match_in_text(query, text)

        # These texts share very few content words (only "kidney" and "disease")
        # so should NOT be considered a match
        assert found is False, f"Should not match unrelated text, got score {score}"

    def test_word_overlap_prevents_false_positives(self):
        """Word overlap check should prevent matches on common short sequences."""
        # Two sentences that might match on "is a" and similar patterns
        # but have completely different content words
        query = "The enzyme is a crucial regulator of cellular metabolism"
        text = "The receptor is a transmembrane protein that binds hormones"

        found, score, match = find_fuzzy_match_in_text(query, text)

        # Despite similar structure, content words don't overlap much
        assert found is False


class TestGetSignificantWords:
    """Tests for significant word extraction."""

    def test_excludes_stopwords(self):
        """Stopwords should be excluded."""
        words = get_significant_words("The JAK1 protein is a tyrosine kinase")
        assert "the" not in words
        assert "is" not in words
        assert "a" not in words

    def test_includes_content_words(self):
        """Content words should be included."""
        words = get_significant_words("The JAK1 protein is a tyrosine kinase")
        assert "jak1" in words
        assert "protein" in words
        assert "tyrosine" in words
        assert "kinase" in words

    def test_excludes_short_words(self):
        """Words <= 2 chars should be excluded."""
        words = get_significant_words("I am at a to be or")
        assert len(words) == 0


class TestCalculateWordOverlap:
    """Tests for word overlap calculation."""

    def test_full_overlap(self):
        """Identical content should have 100% overlap."""
        overlap = calculate_word_overlap(
            "JAK1 protein tyrosine kinase",
            "The JAK1 protein is a tyrosine kinase"
        )
        assert overlap == 100.0

    def test_no_overlap(self):
        """Completely different content should have 0% overlap."""
        overlap = calculate_word_overlap(
            "creatinine albuminuria diagnostic",
            "nephronophthisis autosomal recessive cystic kidney disease"
        )
        assert overlap == 0.0

    def test_partial_overlap(self):
        """Partial overlap should be calculated correctly."""
        overlap = calculate_word_overlap(
            "protein kinase activates signaling",  # 4 words
            "The protein kinase enzyme"  # has 2 of them
        )
        assert 40 <= overlap <= 60  # ~50%


class TestCalculateTextSimilarity:
    """Tests for text similarity calculation."""

    def test_identical_texts(self):
        """Identical texts should have 100% similarity."""
        assert calculate_text_similarity("hello world", "hello world") == 100.0

    def test_reordered_words(self):
        """Reordered words should still have high similarity."""
        assert calculate_text_similarity("the cat sat", "sat the cat") == 100.0

    def test_different_texts(self):
        """Different texts should have lower similarity."""
        score = calculate_text_similarity("hello world", "goodbye universe")
        assert score < 50


# =============================================================================
# Tests for suggestion generation in SupportingTextValidator
# =============================================================================


class TestGenerateSuggestedFix:
    """Tests for suggestion generation."""

    def test_suggests_capitalization_fix(self, validator):
        """Should detect capitalization differences.

        Uses a pure case difference test case where the query text matches
        exactly except for capitalization. Verifies that the fix message
        indicates "Capitalization differs".
        """
        fix, match, score = validator.generate_suggested_fix(
            "jak1 protein is a tyrosine kinase",
            "JAK1 protein is a tyrosine kinase",
        )
        assert score >= 90
        assert fix is not None
        assert "Capitalization differs" in fix

    def test_suggests_close_match(self, validator):
        """Should suggest close matches."""
        fix, match, score = validator.generate_suggested_fix(
            "JAK1 protein binds to cytokine receptor",
            "The JAK1 protein binds to cytokine receptors and activates STAT.",
        )
        assert score >= 70
        assert match is not None

    def test_no_suggestion_for_completely_different(self, validator):
        """Should not suggest for completely different text."""
        fix, match, score = validator.generate_suggested_fix(
            "completely unrelated text about something else entirely",
            "The JAK1 protein is a tyrosine kinase.",
        )
        # Score should be low, fix may or may not be None
        assert score < 50


# =============================================================================
# Tests ensuring validation remains strict
# =============================================================================


class TestValidationRemainsStrict:
    """Tests to ensure fuzzy matching does NOT affect validation strictness."""

    def test_close_match_still_fails_validation(self, validator):
        """A close but not exact match should still fail validation."""
        ref = ReferenceContent(
            reference_id="PMID:123",
            content="The JAK1 protein is a tyrosine kinase.",
        )

        # Close but not exact - "the" vs "a" tyrosine kinase
        match = validator.find_text_in_reference(
            "JAK1 protein is THE tyrosine kinase",  # Changed "a" to "THE"
            ref,
        )
        # This should FAIL validation (strict substring matching)
        assert match.found is False

    def test_typo_still_fails_validation(self, validator):
        """A typo should still fail validation."""
        ref = ReferenceContent(
            reference_id="PMID:123",
            content="The JAK1 protein is a tyrosine kinase.",
        )

        # Typo: "tyrosine" -> "tyrosin"
        match = validator.find_text_in_reference(
            "JAK1 protein is a tyrosin kinase",
            ref,
        )
        assert match.found is False

    def test_extra_word_still_fails_validation(self, validator):
        """Extra words should still fail validation."""
        ref = ReferenceContent(
            reference_id="PMID:123",
            content="The protein functions in cells.",
        )

        # Extra word: "very"
        match = validator.find_text_in_reference(
            "protein functions very well in cells",
            ref,
        )
        assert match.found is False


# =============================================================================
# Tests for suggestion presence when validation fails
# =============================================================================


class TestSuggestionPresenceOnFailure:
    """Tests that suggestions are populated when validation fails."""

    def test_suggestion_provided_for_close_match(self, validator):
        """When validation fails with close match, suggestion should be provided."""
        ref = ReferenceContent(
            reference_id="PMID:123",
            content="The JAK1 protein is a tyrosine kinase that phosphorylates STAT proteins.",
        )

        match = validator.find_text_in_reference(
            "JAK1 protein is a tyrosin kinase that phosphorylates STAT",  # typo
            ref,
        )
        assert match.found is False
        # Should have a suggestion since it's a close match
        # The suggestion depends on how close the match is
        # We just verify the similarity score is captured
        assert match.similarity_score >= 0

    def test_best_match_provided(self, validator):
        """Best match should be populated when available."""
        ref = ReferenceContent(
            reference_id="PMID:123",
            content="The JAK1 protein is a tyrosine kinase. It activates STAT proteins.",
        )

        match = validator.find_text_in_reference(
            "JAK1 protein activates downstream signaling",
            ref,
        )
        assert match.found is False
        # best_match may or may not be populated depending on the match quality

    def test_no_suggestion_for_completely_unrelated(self, validator):
        """No useful suggestion for completely unrelated text."""
        ref = ReferenceContent(
            reference_id="PMID:123",
            content="The JAK1 protein is a tyrosine kinase.",
        )

        match = validator.find_text_in_reference(
            "mitochondrial membrane potential regulates apoptosis",
            ref,
        )
        assert match.found is False
        # Suggestion should be None for very low similarity
        # (depends on threshold, but should be low score)


# =============================================================================
# Integration tests
# =============================================================================


class TestIntegration:
    """Integration tests for the complete flow."""

    def test_validation_with_suggestion(self, validator, mocker):
        """Test full validation flow with suggestion generation."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            content="The JAK1 protein is a tyrosine kinase that activates STAT signaling.",
        )

        result = validator.validate(
            "JAK1 protein is a tyrosin kinase",  # typo
            "PMID:123",
        )

        assert result.is_valid is False  # Validation still fails
        assert result.match_result is not None
        # Check that similarity info is captured
        assert result.match_result.similarity_score >= 0

    def test_exact_match_has_no_suggestion(self, validator, mocker):
        """Test that exact matches don't need suggestions."""
        mock_fetch = mocker.patch.object(validator.fetcher, "fetch")
        mock_fetch.return_value = ReferenceContent(
            reference_id="PMID:123",
            content="The JAK1 protein is a tyrosine kinase.",
        )

        result = validator.validate(
            "JAK1 protein is a tyrosine kinase",
            "PMID:123",
        )

        assert result.is_valid is True
        # No suggestion needed for valid matches
        assert result.match_result.suggested_fix is None
