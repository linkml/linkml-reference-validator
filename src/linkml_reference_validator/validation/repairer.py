"""Repair functionality for supporting text validation errors.

This module provides automated repair capabilities for common validation
errors, including:
- Character normalization (Unicode/symbol fixes)
- Ellipsis insertion for non-contiguous text
- Fuzzy match correction for minor variations
- Flagging fabricated or unverifiable text for removal

Examples:
    >>> from linkml_reference_validator.models import ReferenceValidationConfig, RepairConfig
    >>> from linkml_reference_validator.validation.repairer import SupportingTextRepairer
    >>> val_config = ReferenceValidationConfig()
    >>> repair_config = RepairConfig()
    >>> repairer = SupportingTextRepairer(val_config, repair_config)
"""

import logging
import re
from typing import Optional

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
    RepairAction,
    RepairActionType,
    RepairConfig,
    RepairConfidence,
    RepairReport,
    RepairResult,
)
from linkml_reference_validator.validation.fuzzy_text_utils import (
    calculate_text_similarity,
    find_fuzzy_match_in_text,
    normalize_whitespace,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

logger = logging.getLogger(__name__)


class SupportingTextRepairer:
    """Repair supporting text validation errors.

    This class attempts to automatically fix or flag validation errors
    based on configurable confidence thresholds.

    Repair strategies (in order of preference):
    1. Character normalization - fix Unicode/symbol differences
    2. Ellipsis insertion - connect non-contiguous text parts
    3. Fuzzy correction - replace with closest matching text
    4. Removal recommendation - flag fabricated text

    Examples:
        >>> from linkml_reference_validator.models import ReferenceValidationConfig, RepairConfig
        >>> val_config = ReferenceValidationConfig()
        >>> repair_config = RepairConfig()
        >>> repairer = SupportingTextRepairer(val_config, repair_config)
        >>> isinstance(repairer.validator, SupportingTextValidator)
        True
    """

    def __init__(
        self,
        validation_config: ReferenceValidationConfig,
        repair_config: Optional[RepairConfig] = None,
    ):
        """Initialize the repairer.

        Args:
            validation_config: Configuration for reference validation
            repair_config: Configuration for repair operations (uses defaults if None)

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig, RepairConfig
            >>> val_config = ReferenceValidationConfig()
            >>> repairer = SupportingTextRepairer(val_config)
            >>> repairer.repair_config.auto_fix_threshold
            0.95
        """
        self.validation_config = validation_config
        self.repair_config = repair_config or RepairConfig()
        self.validator = SupportingTextValidator(validation_config)
        self.fetcher = ReferenceFetcher(validation_config)

    def apply_character_mappings(self, text: str) -> str:
        """Apply character normalization mappings to text.

        Replaces ASCII approximations with proper Unicode characters.

        Args:
            text: Text to normalize

        Returns:
            Text with character substitutions applied

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> repairer = SupportingTextRepairer(ReferenceValidationConfig())
            >>> repairer.apply_character_mappings("CO2 and H2O")
            'CO₂ and H₂O'
            >>> repairer.apply_character_mappings("+/- 5 percent")
            '± 5 percent'
        """
        result = text
        for original, replacement in self.repair_config.character_mappings.items():
            result = result.replace(original, replacement)
        return result

    def try_ellipsis_insertion(
        self, snippet: str, reference_content: str
    ) -> Optional[str]:
        """Try to insert ellipsis between non-contiguous text parts.

        Splits the snippet into sentences and finds each in the reference.
        If sentences are non-contiguous, inserts '...' between them.

        Args:
            snippet: Supporting text snippet
            reference_content: Full reference content

        Returns:
            Repaired text with ellipsis inserted, or None if not applicable

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> repairer = SupportingTextRepairer(ReferenceValidationConfig())
            >>> # Returns None when snippet exists as-is in content
            >>> result = repairer.try_ellipsis_insertion(
            ...     "First sentence",
            ...     "First sentence here."
            ... )
            >>> result is None
            True
        """
        # If already contains ellipsis, skip
        if "..." in snippet:
            return None

        # Normalize both texts
        snippet_norm = normalize_whitespace(snippet)
        content_norm = normalize_whitespace(reference_content)

        # Check if snippet already exists as-is
        if snippet_norm in content_norm:
            return None  # No repair needed

        # Split snippet into sentences
        sentences = self._split_into_fragments(snippet)
        if len(sentences) < 2:
            return None  # Need at least 2 parts for ellipsis

        # Find each sentence's position in the reference
        positions = []
        for sentence in sentences:
            sentence_norm = normalize_whitespace(sentence)
            if not sentence_norm:
                continue

            pos = content_norm.find(sentence_norm)
            if pos == -1:
                # Try fuzzy match for this sentence
                found, score, match = find_fuzzy_match_in_text(
                    sentence, reference_content, threshold=90.0
                )
                if found and match:
                    positions.append((sentence, content_norm.find(normalize_whitespace(match)), match))
                else:
                    return None  # Can't find this sentence
            else:
                positions.append((sentence, pos, sentence))

        if len(positions) < 2:
            return None

        # Sort by position
        positions.sort(key=lambda x: x[1])

        # Check if parts are contiguous (allowing some gap for punctuation/whitespace)
        is_contiguous = True
        for i in range(len(positions) - 1):
            current_end = positions[i][1] + len(normalize_whitespace(positions[i][2]))
            next_start = positions[i + 1][1]
            gap = next_start - current_end

            # Allow small gaps for punctuation, but flag larger gaps
            if gap > 50:  # More than ~50 chars between parts
                is_contiguous = False
                break

        if is_contiguous:
            return None  # No ellipsis needed

        # Build repaired text with ellipsis
        repaired_parts = []
        for i, (orig_sentence, pos, matched) in enumerate(positions):
            # Use original sentence text, not normalized
            repaired_parts.append(orig_sentence.strip())
            if i < len(positions) - 1:
                repaired_parts.append("...")

        return " ".join(repaired_parts)

    def _split_into_fragments(self, text: str) -> list[str]:
        """Split text into sentence fragments.

        Args:
            text: Text to split

        Returns:
            List of sentence fragments

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> repairer = SupportingTextRepairer(ReferenceValidationConfig())
            >>> repairer._split_into_fragments("Hello world. Goodbye world.")
            ['Hello world', 'Goodbye world.']
        """
        # Split on sentence boundaries
        parts = re.split(r"[.!?]\s+", text)
        return [p.strip() for p in parts if p.strip()]

    def try_fuzzy_correction(
        self, snippet: str, reference_content: str
    ) -> Optional[RepairAction]:
        """Try to find and suggest the best fuzzy match.

        Args:
            snippet: Supporting text snippet
            reference_content: Full reference content

        Returns:
            RepairAction with fuzzy correction, or None if no good match found

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> repairer = SupportingTextRepairer(ReferenceValidationConfig())
            >>> result = repairer.try_fuzzy_correction(
            ...     "protein X functions",
            ...     "The Protein X functions in cell cycle regulation."
            ... )
            >>> result is not None
            True
        """
        found, similarity, best_match = find_fuzzy_match_in_text(
            snippet, reference_content, threshold=50.0  # Lower threshold for suggestions
        )

        if not best_match:
            return None

        # Convert similarity from 0-100 to 0-1 scale
        similarity_normalized = similarity / 100.0
        confidence = RepairConfidence.from_score(similarity_normalized)

        # Determine action type based on similarity
        if similarity >= 95:
            action_type = RepairActionType.FUZZY_CORRECTION
            description = f"Very close match ({similarity:.0f}%)"
        elif similarity >= 80:
            action_type = RepairActionType.FUZZY_CORRECTION
            description = f"Close match ({similarity:.0f}%)"
        else:
            action_type = RepairActionType.FUZZY_CORRECTION
            description = f"Partial match ({similarity:.0f}%)"

        return RepairAction(
            action_type=action_type,
            original_text=snippet,
            repaired_text=best_match,
            confidence=confidence,
            similarity_score=similarity_normalized,
            description=description,
        )

    def attempt_repair(
        self,
        supporting_text: str,
        reference_id: str,
        reference: Optional[ReferenceContent] = None,
    ) -> RepairResult:
        """Attempt to repair a validation error.

        Tries repair strategies in order:
        1. Character normalization
        2. Ellipsis insertion
        3. Fuzzy correction
        4. Removal recommendation

        Args:
            supporting_text: The text that failed validation
            reference_id: The reference identifier
            reference: Optional pre-fetched reference content

        Returns:
            RepairResult with actions taken

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig, ReferenceContent
            >>> repairer = SupportingTextRepairer(ReferenceValidationConfig())
            >>> ref = ReferenceContent(
            ...     reference_id="PMID:123",
            ...     content="CO₂ levels were measured at various time points."
            ... )
            >>> result = repairer.attempt_repair("CO2 levels", "PMID:123", ref)
            >>> len(result.actions) > 0
            True
        """
        actions: list[RepairAction] = []

        # Handle missing reference content
        if reference is None or reference.content is None:
            actions.append(RepairAction(
                action_type=RepairActionType.UNVERIFIABLE,
                original_text=supporting_text,
                reference_id=reference_id,
                confidence=RepairConfidence.VERY_LOW,
                description="No content available for reference",
            ))
            return RepairResult(
                reference_id=reference_id,
                original_text=supporting_text,
                was_valid=False,
                is_repaired=False,
                actions=actions,
                message="Reference content not available - cannot verify",
            )

        reference_content = reference.content

        # Strategy 1: Try character normalization
        normalized = self.apply_character_mappings(supporting_text)
        if normalized != supporting_text:
            # Check if normalized version validates
            normalized_lower = SupportingTextValidator.normalize_text(normalized)
            content_lower = SupportingTextValidator.normalize_text(reference_content)

            if normalized_lower in content_lower:
                # Calculate similarity for the normalization
                similarity = calculate_text_similarity(normalized, supporting_text)
                actions.append(RepairAction(
                    action_type=RepairActionType.CHARACTER_NORMALIZATION,
                    original_text=supporting_text,
                    repaired_text=normalized,
                    confidence=RepairConfidence.HIGH,
                    similarity_score=similarity / 100.0,
                    description="Character normalization fix",
                    reference_id=reference_id,
                ))
                return RepairResult(
                    reference_id=reference_id,
                    original_text=supporting_text,
                    was_valid=False,
                    is_repaired=True,
                    repaired_text=normalized,
                    actions=actions,
                    message="Fixed via character normalization",
                )

        # Strategy 2: Try ellipsis insertion
        ellipsis_result = self.try_ellipsis_insertion(supporting_text, reference_content)
        if ellipsis_result:
            # Verify the ellipsis version validates
            parts = self.validator._split_query(ellipsis_result)
            all_found = True
            for part in parts:
                part_norm = SupportingTextValidator.normalize_text(part)
                content_norm = SupportingTextValidator.normalize_text(reference_content)
                if part_norm not in content_norm:
                    all_found = False
                    break

            if all_found:
                actions.append(RepairAction(
                    action_type=RepairActionType.ELLIPSIS_INSERTION,
                    original_text=supporting_text,
                    repaired_text=ellipsis_result,
                    confidence=RepairConfidence.MEDIUM,  # Ellipsis needs review
                    similarity_score=0.85,
                    description="Inserted ellipsis between non-contiguous parts",
                    reference_id=reference_id,
                ))
                return RepairResult(
                    reference_id=reference_id,
                    original_text=supporting_text,
                    was_valid=False,
                    is_repaired=True,
                    repaired_text=ellipsis_result,
                    actions=actions,
                    message="Fixed via ellipsis insertion",
                )

        # Strategy 3: Try fuzzy correction
        fuzzy_action = self.try_fuzzy_correction(supporting_text, reference_content)
        if fuzzy_action:
            actions.append(fuzzy_action)

            if fuzzy_action.confidence in (RepairConfidence.HIGH, RepairConfidence.MEDIUM):
                return RepairResult(
                    reference_id=reference_id,
                    original_text=supporting_text,
                    was_valid=False,
                    is_repaired=fuzzy_action.confidence == RepairConfidence.HIGH,
                    repaired_text=fuzzy_action.repaired_text,
                    actions=actions,
                    message=f"Suggested fix via fuzzy matching ({fuzzy_action.similarity_score*100:.0f}%)",
                )

        # Strategy 4: Flag for removal (low similarity)
        if not actions or (actions and actions[-1].similarity_score < self.repair_config.removal_threshold):
            actions.append(RepairAction(
                action_type=RepairActionType.REMOVAL,
                original_text=supporting_text,
                confidence=RepairConfidence.VERY_LOW,
                similarity_score=actions[-1].similarity_score if actions else 0.0,
                description="Text not found in reference - likely fabricated",
                reference_id=reference_id,
            ))
            return RepairResult(
                reference_id=reference_id,
                original_text=supporting_text,
                was_valid=False,
                is_repaired=False,
                actions=actions,
                message="Flagged for removal - text not found in reference",
            )

        return RepairResult(
            reference_id=reference_id,
            original_text=supporting_text,
            was_valid=False,
            is_repaired=False,
            actions=actions,
            message="Could not find a suitable repair",
        )

    def repair_single(
        self,
        supporting_text: str,
        reference_id: str,
        path: Optional[str] = None,
    ) -> RepairResult:
        """Repair a single supporting text quote.

        First validates the text, then attempts repair if invalid.

        Args:
            supporting_text: Text to validate/repair
            reference_id: Reference identifier
            path: Optional path in data structure

        Returns:
            RepairResult with validation/repair status

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> # In real usage:
            >>> # repairer = SupportingTextRepairer(ReferenceValidationConfig())
            >>> # result = repairer.repair_single("some text", "PMID:123")
        """
        # Check skip list
        if reference_id in self.repair_config.skip_references:
            return RepairResult(
                reference_id=reference_id,
                original_text=supporting_text,
                was_valid=False,
                is_repaired=False,
                message=f"Skipped - reference {reference_id} is in skip list",
                path=path,
            )

        # First, validate the text
        validation_result = self.validator.validate(supporting_text, reference_id, path=path)

        if validation_result.is_valid:
            return RepairResult(
                reference_id=reference_id,
                original_text=supporting_text,
                was_valid=True,
                is_repaired=False,
                message="Already valid",
                path=path,
            )

        # Fetch reference for repair attempts
        reference = self.fetcher.fetch(reference_id)

        # Check trusted list - don't flag for removal
        if reference_id in self.repair_config.trusted_low_similarity:
            result = self.attempt_repair(supporting_text, reference_id, reference)
            # Remove any REMOVAL actions for trusted references
            result.actions = [
                a for a in result.actions
                if a.action_type != RepairActionType.REMOVAL
            ]
            result.path = path
            return result

        result = self.attempt_repair(supporting_text, reference_id, reference)
        result.path = path
        return result

    def repair_batch(
        self,
        items: list[tuple[str, str, Optional[str]]],
    ) -> RepairReport:
        """Repair multiple supporting text items.

        Args:
            items: List of (supporting_text, reference_id, path) tuples

        Returns:
            RepairReport with all results

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> # In real usage:
            >>> # repairer = SupportingTextRepairer(ReferenceValidationConfig())
            >>> # report = repairer.repair_batch([
            >>> #     ("text1", "PMID:1", "path1"),
            >>> #     ("text2", "PMID:2", "path2"),
            >>> # ])
        """
        report = RepairReport()

        for supporting_text, reference_id, path in items:
            result = self.repair_single(supporting_text, reference_id, path)
            report.add_result(result)

        return report

    def format_report(self, report: RepairReport, verbose: bool = False) -> str:
        """Format a repair report for display.

        Args:
            report: RepairReport to format
            verbose: Include detailed information

        Returns:
            Formatted report string

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig, RepairReport
            >>> repairer = SupportingTextRepairer(ReferenceValidationConfig())
            >>> report = RepairReport()
            >>> output = repairer.format_report(report)
            >>> "Summary" in output
            True
        """
        lines = []
        lines.append("=" * 60)
        lines.append("Repair Report")
        lines.append("=" * 60)
        lines.append("")

        # Group by action type
        high_confidence = []
        suggestions = []
        removals = []
        unverifiable = []
        already_valid = []

        for result in report.results:
            if result.was_valid:
                already_valid.append(result)
                continue

            for action in result.actions:
                if action.can_auto_fix:
                    high_confidence.append((result, action))
                elif action.action_type == RepairActionType.REMOVAL:
                    removals.append((result, action))
                elif action.action_type == RepairActionType.UNVERIFIABLE:
                    unverifiable.append((result, action))
                elif action.confidence == RepairConfidence.MEDIUM:
                    suggestions.append((result, action))

        # High confidence fixes
        if high_confidence:
            lines.append("HIGH CONFIDENCE FIXES (auto-applicable):")
            for result, action in high_confidence:
                path_str = f" at {result.path}" if result.path else ""
                lines.append(f"  {result.reference_id}{path_str}:")
                lines.append(f"    {action.description}")
                lines.append(f"    '{action.original_text[:50]}...' → '{action.repaired_text[:50] if action.repaired_text else 'N/A'}...'")
            lines.append("")

        # Suggestions
        if suggestions:
            lines.append("SUGGESTED FIXES (review recommended):")
            for result, action in suggestions:
                path_str = f" at {result.path}" if result.path else ""
                lines.append(f"  {result.reference_id}{path_str}:")
                lines.append(f"    {action.description}")
                if verbose and action.repaired_text:
                    lines.append(f"    Suggestion: '{action.repaired_text[:80]}...'")
            lines.append("")

        # Removals
        if removals:
            lines.append("RECOMMENDED REMOVALS (low confidence):")
            for result, action in removals:
                path_str = f" at {result.path}" if result.path else ""
                lines.append(f"  {result.reference_id}{path_str}:")
                lines.append(f"    Similarity: {action.similarity_score*100:.0f}%")
                lines.append(f"    Snippet: '{result.original_text[:60]}...'")
            lines.append("")

        # Unverifiable
        if unverifiable:
            lines.append("UNVERIFIABLE (no abstract available):")
            for result, action in unverifiable:
                path_str = f" at {result.path}" if result.path else ""
                lines.append(f"  {result.reference_id}{path_str}:")
                lines.append(f"    {action.description}")
            lines.append("")

        # Summary
        lines.append("-" * 60)
        lines.append("Summary:")
        lines.append(f"  Total items: {report.total_items}")
        lines.append(f"  Already valid: {report.already_valid_count}")
        lines.append(f"  Auto-fixes: {report.auto_fixed_count}")
        lines.append(f"  Suggestions: {report.suggested_count}")
        lines.append(f"  Removals: {report.removal_count}")
        lines.append(f"  Unverifiable: {report.unverifiable_count}")

        return "\n".join(lines)
