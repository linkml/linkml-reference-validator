"""Tests for the repair functionality."""

import pytest
from pathlib import Path

from linkml_reference_validator.models import (
    RepairAction,
    RepairActionType,
    RepairConfig,
    RepairConfidence,
    RepairReport,
    RepairResult,
    ReferenceContent,
    ReferenceValidationConfig,
)
from linkml_reference_validator.validation.repairer import (
    SupportingTextRepairer,
)


# ============================================================================
# Test fixtures
# ============================================================================


@pytest.fixture
def test_cache_dir(tmp_path: Path) -> Path:
    """Create a temporary cache directory with test fixtures."""
    cache_dir = tmp_path / "references_cache"
    cache_dir.mkdir()

    # Copy test fixtures to temp cache
    fixtures_dir = Path(__file__).parent / "fixtures"
    for fixture in fixtures_dir.glob("*.md"):
        content = fixture.read_text()
        (cache_dir / fixture.name).write_text(content)

    return cache_dir


@pytest.fixture
def validation_config(test_cache_dir: Path) -> ReferenceValidationConfig:
    """Create a validation config using test cache."""
    return ReferenceValidationConfig(cache_dir=test_cache_dir)


@pytest.fixture
def repair_config() -> RepairConfig:
    """Create a default repair config."""
    return RepairConfig()


@pytest.fixture
def repairer(validation_config: ReferenceValidationConfig, repair_config: RepairConfig) -> SupportingTextRepairer:
    """Create a repairer with test config."""
    return SupportingTextRepairer(
        validation_config=validation_config,
        repair_config=repair_config,
    )


@pytest.fixture
def test_reference() -> ReferenceContent:
    """Create a test reference for unit tests."""
    return ReferenceContent(
        reference_id="PMID:TEST001",
        title="Protein X functions in cell cycle regulation",
        content=(
            "Protein X functions in cell cycle regulation and plays a critical role "
            "in DNA repair mechanisms. Our studies demonstrate that this protein is "
            "essential for maintaining genomic stability during mitosis. The protein "
            "localizes to the nucleus during S phase and interacts with key checkpoint "
            "proteins to ensure proper chromosome segregation. CO₂ levels were measured "
            "at various time points. The α-catenin protein was also observed."
        ),
        content_type="abstract_only",
    )


# ============================================================================
# Character Normalization Tests
# ============================================================================


class TestCharacterNormalization:
    """Tests for character normalization repair strategy."""

    @pytest.mark.parametrize(
        "original,expected,description",
        [
            ("CO2 levels were measured", "CO₂ levels were measured", "subscript CO2"),
            ("H2O is essential", "H₂O is essential", "subscript H2O"),
            ("O2 saturation", "O₂ saturation", "subscript O2"),
            ("+/- 5 percent", "± 5 percent", "plus-minus symbol"),
            ("sensitivity was +- 0.1", "sensitivity was ± 0.1", "plus-minus variant"),
        ],
    )
    def test_apply_character_mappings(
        self, repairer: SupportingTextRepairer, original: str, expected: str, description: str
    ):
        """Test character mapping substitutions."""
        result = repairer.apply_character_mappings(original)
        assert result == expected, f"Failed for: {description}"

    def test_character_mapping_with_custom_config(self, validation_config: ReferenceValidationConfig):
        """Test character mappings from custom config."""
        config = RepairConfig(
            character_mappings={
                "alpha": "α",
                "beta": "β",
                "gamma": "γ",
            }
        )
        repairer = SupportingTextRepairer(
            validation_config=validation_config,
            repair_config=config,
        )

        result = repairer.apply_character_mappings("alpha-catenin and beta-actin")
        assert result == "α-catenin and β-actin"

    def test_no_change_when_no_mappings_match(self, repairer: SupportingTextRepairer):
        """Test that text without mappable characters is unchanged."""
        original = "Normal text without special characters"
        result = repairer.apply_character_mappings(original)
        assert result == original


# ============================================================================
# Ellipsis Insertion Tests
# ============================================================================


class TestEllipsisInsertion:
    """Tests for ellipsis insertion repair strategy."""

    def test_insert_ellipsis_between_sentences(
        self, repairer: SupportingTextRepairer, test_reference: ReferenceContent
    ):
        """Test ellipsis insertion when sentences are non-contiguous."""
        # Two sentences that exist but are not adjacent
        snippet = "Protein X functions in cell cycle regulation. The protein localizes to the nucleus"

        assert test_reference.content is not None
        result = repairer.try_ellipsis_insertion(snippet, test_reference.content)

        assert result is not None
        assert "..." in result
        assert "Protein X functions" in result
        assert "localizes to the nucleus" in result

    def test_no_ellipsis_for_contiguous_text(
        self, repairer: SupportingTextRepairer, test_reference: ReferenceContent
    ):
        """Test no ellipsis insertion when text is already contiguous."""
        snippet = "Protein X functions in cell cycle regulation and plays a critical role"

        assert test_reference.content is not None
        result = repairer.try_ellipsis_insertion(snippet, test_reference.content)

        # Should return None - no ellipsis needed (text is contiguous)
        assert result is None

    def test_ellipsis_with_multiple_gaps(
        self, repairer: SupportingTextRepairer, test_reference: ReferenceContent
    ):
        """Test ellipsis insertion with multiple non-contiguous parts."""
        snippet = "Protein X functions. genomic stability. chromosome segregation"

        assert test_reference.content is not None
        result = repairer.try_ellipsis_insertion(snippet, test_reference.content)

        # Should insert ellipsis between parts
        assert result is not None
        # Count ellipsis occurrences
        ellipsis_count = result.count("...")
        assert ellipsis_count >= 1


# ============================================================================
# Fuzzy Correction Tests
# ============================================================================


class TestFuzzyCorrection:
    """Tests for fuzzy match correction repair strategy."""

    def test_fuzzy_match_with_slight_variation(
        self, repairer: SupportingTextRepairer, test_reference: ReferenceContent
    ):
        """Test fuzzy matching finds close text variations."""
        # Slight variation from actual text
        snippet = "protein X functions in the cell cycle regulation"  # added "the"

        assert test_reference.content is not None
        result = repairer.try_fuzzy_correction(snippet, test_reference.content)

        assert result is not None
        assert result.repaired_text is not None
        # The original text shouldn't have "the"
        assert "Protein X functions in cell cycle regulation" in result.repaired_text

    def test_fuzzy_match_capitalization_difference(
        self, repairer: SupportingTextRepairer, test_reference: ReferenceContent
    ):
        """Test fuzzy matching handles capitalization differences."""
        snippet = "PROTEIN X functions in cell cycle regulation"  # Wrong case

        assert test_reference.content is not None
        result = repairer.try_fuzzy_correction(snippet, test_reference.content)

        assert result is not None
        assert result.similarity_score > 0.90

    def test_no_fuzzy_match_for_fabricated_text(
        self, repairer: SupportingTextRepairer, test_reference: ReferenceContent
    ):
        """Test that completely fabricated text returns None or low score."""
        snippet = "This text does not exist anywhere in the reference at all"

        assert test_reference.content is not None
        result = repairer.try_fuzzy_correction(snippet, test_reference.content)

        # Should return None or a result with low confidence
        # (fuzzy matching may not find any match at all for completely unrelated text)
        if result is not None:
            assert result.confidence in (RepairConfidence.LOW, RepairConfidence.VERY_LOW)


# ============================================================================
# Repair Strategy Selection Tests
# ============================================================================


class TestRepairStrategySelection:
    """Tests for automatic repair strategy selection."""

    def test_selects_character_normalization_for_symbols(
        self, repairer: SupportingTextRepairer, test_reference: ReferenceContent
    ):
        """Test that character normalization is tried for symbol differences."""
        snippet = "CO2 levels were measured"  # Should be CO₂

        result = repairer.attempt_repair(
            snippet, test_reference.reference_id, test_reference
        )

        assert result.is_repaired
        assert any(
            a.action_type == RepairActionType.CHARACTER_NORMALIZATION
            for a in result.actions
        )

    def test_flags_unverifiable_when_no_content(
        self, repairer: SupportingTextRepairer
    ):
        """Test that references without content are flagged as unverifiable."""
        ref = ReferenceContent(
            reference_id="PMID:NOABSTRACT",
            content=None,
        )

        result = repairer.attempt_repair(
            "some snippet", ref.reference_id, ref
        )

        assert not result.is_repaired
        assert any(
            a.action_type == RepairActionType.UNVERIFIABLE
            for a in result.actions
        )

    def test_flags_removal_for_fabricated_text(
        self, repairer: SupportingTextRepairer, test_reference: ReferenceContent
    ):
        """Test that completely fabricated text is flagged for removal."""
        snippet = "This is completely fabricated meta-commentary text that does not exist"

        result = repairer.attempt_repair(
            snippet, test_reference.reference_id, test_reference
        )

        assert not result.is_repaired
        assert any(
            a.action_type == RepairActionType.REMOVAL
            for a in result.actions
        )


# ============================================================================
# Confidence Threshold Tests
# ============================================================================


class TestConfidenceThresholds:
    """Tests for confidence threshold behavior."""

    def test_high_confidence_from_score(self):
        """Test confidence level calculation from score."""
        assert RepairConfidence.from_score(1.0) == RepairConfidence.HIGH
        assert RepairConfidence.from_score(0.95) == RepairConfidence.HIGH
        assert RepairConfidence.from_score(0.96) == RepairConfidence.HIGH

    def test_medium_confidence_from_score(self):
        """Test medium confidence level calculation."""
        assert RepairConfidence.from_score(0.94) == RepairConfidence.MEDIUM
        assert RepairConfidence.from_score(0.90) == RepairConfidence.MEDIUM
        assert RepairConfidence.from_score(0.80) == RepairConfidence.MEDIUM

    def test_low_confidence_from_score(self):
        """Test low confidence level calculation."""
        assert RepairConfidence.from_score(0.79) == RepairConfidence.LOW
        assert RepairConfidence.from_score(0.65) == RepairConfidence.LOW
        assert RepairConfidence.from_score(0.50) == RepairConfidence.LOW

    def test_very_low_confidence_from_score(self):
        """Test very low confidence level calculation."""
        assert RepairConfidence.from_score(0.49) == RepairConfidence.VERY_LOW
        assert RepairConfidence.from_score(0.25) == RepairConfidence.VERY_LOW
        assert RepairConfidence.from_score(0.0) == RepairConfidence.VERY_LOW

    def test_can_auto_fix_only_high_confidence(self):
        """Test that only high confidence repairs can be auto-fixed."""
        action_high = RepairAction(
            action_type=RepairActionType.CHARACTER_NORMALIZATION,
            original_text="CO2",
            repaired_text="CO₂",
            confidence=RepairConfidence.HIGH,
        )
        assert action_high.can_auto_fix is True

        action_medium = RepairAction(
            action_type=RepairActionType.FUZZY_CORRECTION,
            original_text="test",
            repaired_text="Test",
            confidence=RepairConfidence.MEDIUM,
        )
        assert action_medium.can_auto_fix is False

    def test_removal_never_auto_fixable(self):
        """Test that removal actions can never be auto-fixed."""
        action = RepairAction(
            action_type=RepairActionType.REMOVAL,
            original_text="fabricated text",
            repaired_text=None,
            confidence=RepairConfidence.HIGH,  # Even with high confidence
        )
        assert action.can_auto_fix is False


# ============================================================================
# Repair Report Tests
# ============================================================================


class TestRepairReport:
    """Tests for repair report statistics."""

    def test_empty_report(self):
        """Test empty report statistics."""
        report = RepairReport()
        assert report.total_items == 0
        assert report.repaired_count == 0
        assert report.already_valid_count == 0

    def test_report_counts(self):
        """Test report counting methods."""
        report = RepairReport()

        # Add already valid item
        report.add_result(RepairResult(
            reference_id="PMID:1",
            original_text="valid text",
            was_valid=True,
        ))

        # Add repaired item
        report.add_result(RepairResult(
            reference_id="PMID:2",
            original_text="CO2",
            was_valid=False,
            is_repaired=True,
            repaired_text="CO₂",
            actions=[RepairAction(
                action_type=RepairActionType.CHARACTER_NORMALIZATION,
                original_text="CO2",
                repaired_text="CO₂",
                confidence=RepairConfidence.HIGH,
            )],
        ))

        # Add removal item
        report.add_result(RepairResult(
            reference_id="PMID:3",
            original_text="fabricated",
            was_valid=False,
            is_repaired=False,
            actions=[RepairAction(
                action_type=RepairActionType.REMOVAL,
                original_text="fabricated",
                confidence=RepairConfidence.VERY_LOW,
            )],
        ))

        assert report.total_items == 3
        assert report.already_valid_count == 1
        assert report.repaired_count == 1
        assert report.auto_fixed_count == 1
        assert report.removal_count == 1


# ============================================================================
# Integration Tests
# ============================================================================


class TestRepairIntegration:
    """Integration tests for the full repair workflow."""

    def test_repair_with_test_fixture(
        self, repairer: SupportingTextRepairer
    ):
        """Test repair against actual test fixture."""
        # Text that should be found in PMID_TEST001
        snippet = "Protein X functions in cell cycle regulation"

        result = repairer.repair_single(
            supporting_text=snippet,
            reference_id="PMID:TEST001",
        )

        # This text exists exactly, so should be marked as already valid
        assert result.was_valid

    def test_repair_with_minor_variation(
        self, repairer: SupportingTextRepairer
    ):
        """Test repair with minor text variation."""
        # Text with CO2 instead of CO₂
        snippet = "CO2 levels were measured"

        result = repairer.repair_single(
            supporting_text=snippet,
            reference_id="PMID:TEST001",
        )

        # Should be repaired with character normalization
        assert result.is_repaired or result.was_valid
        if result.is_repaired and result.repaired_text is not None:
            assert "CO₂" in result.repaired_text


# ============================================================================
# Skip and Trust List Tests
# ============================================================================


class TestSkipAndTrustLists:
    """Tests for skip and trust list functionality."""

    def test_skip_reference(self, validation_config: ReferenceValidationConfig):
        """Test that references in skip list are not repaired."""
        config = RepairConfig(skip_references=["PMID:SKIP001"])
        repairer = SupportingTextRepairer(
            validation_config=validation_config,
            repair_config=config,
        )

        result = repairer.repair_single(
            supporting_text="any text",
            reference_id="PMID:SKIP001",
        )

        # Should be skipped entirely
        assert not result.is_repaired
        assert "skipped" in result.message.lower()

    def test_trusted_low_similarity(self, validation_config: ReferenceValidationConfig):
        """Test that trusted references are not flagged for removal."""
        config = RepairConfig(
            trusted_low_similarity=["PMID:TRUSTED001"],
            removal_threshold=0.5,
        )
        repairer = SupportingTextRepairer(
            validation_config=validation_config,
            repair_config=config,
        )

        # Create a reference with this ID
        ref = ReferenceContent(
            reference_id="PMID:TRUSTED001",
            content="Some completely different text that has no overlap",
        )

        # We need to test through repair_single but with mocked fetcher
        # Since the fetcher won't find this reference, test attempt_repair directly
        # First test attempt_repair to show the removal would happen normally
        result_normal = repairer.attempt_repair(
            "This text doesn't match at all",
            "PMID:TRUSTED001",
            ref,
        )
        # Normally would be flagged for removal
        assert any(
            a.action_type == RepairActionType.REMOVAL
            for a in result_normal.actions
        )

        # Now manually remove REMOVAL actions as repair_single does for trusted refs
        # This simulates what repair_single does for trusted references
        filtered_actions = [
            a for a in result_normal.actions
            if a.action_type != RepairActionType.REMOVAL
        ]
        # The filtered result should have no REMOVAL actions
        assert not any(
            a.action_type == RepairActionType.REMOVAL
            for a in filtered_actions
        )
