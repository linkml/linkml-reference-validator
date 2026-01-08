"""Validation of supporting text against reference content."""

import logging
import re
from typing import Optional

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
    SupportingTextMatch,
    ValidationResult,
    ValidationSeverity,
)

logger = logging.getLogger(__name__)


class SupportingTextValidator:
    """Validate that supporting text quotes are found in references.

    This validator checks that quoted text (supporting_text) actually
    appears in the referenced publication using deterministic substring matching.

    Supports:
    - Editorial notes in [square brackets] that are ignored
    - Multi-part quotes with "..." separators indicating omitted text

    Examples:
        >>> config = ReferenceValidationConfig()
        >>> validator = SupportingTextValidator(config)
        >>> # In real usage, would validate against fetched references
    """

    def __init__(self, config: ReferenceValidationConfig):
        """Initialize the validator.

        Args:
            config: Configuration for validation

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> isinstance(validator.fetcher, ReferenceFetcher)
            True
        """
        self.config = config
        self.fetcher = ReferenceFetcher(config)

    def validate_title(
        self,
        reference_id: str,
        expected_title: str,
        path: Optional[str] = None,
    ) -> ValidationResult:
        """Validate title against a reference.

        Performs exact matching after normalization (case, whitespace, punctuation).
        Unlike excerpt validation, this is NOT substring matching.

        Args:
            reference_id: The reference identifier (e.g., "PMID:12345678")
            expected_title: The title to validate against reference
            path: Optional path in data structure for error reporting

        Returns:
            ValidationResult with match details

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> # Would validate in real usage:
            >>> # result = validator.validate_title("PMID:12345678", "Study Title")
        """
        reference = self.fetcher.fetch(reference_id)

        if not reference:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text="",
                severity=ValidationSeverity.ERROR,
                message=f"Could not fetch reference: {reference_id}",
                path=path,
            )

        if not reference.title:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text="",
                severity=ValidationSeverity.ERROR,
                message=f"Reference {reference_id} has no title to validate against",
                path=path,
            )

        normalized_expected = self.normalize_text(expected_title)
        normalized_actual = self.normalize_text(reference.title)

        if normalized_expected == normalized_actual:
            return ValidationResult(
                is_valid=True,
                reference_id=reference_id,
                supporting_text="",
                severity=ValidationSeverity.INFO,
                message=f"Title validated successfully for {reference_id}",
                path=path,
            )
        else:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text="",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Title mismatch for {reference_id}: "
                    f"expected '{expected_title}' but got '{reference.title}'"
                ),
                path=path,
            )

    def validate(
        self,
        supporting_text: str,
        reference_id: str,
        expected_title: Optional[str] = None,
        path: Optional[str] = None,
    ) -> ValidationResult:
        """Validate supporting text against a reference.

        Args:
            supporting_text: The quoted text to validate
            reference_id: The reference identifier (e.g., "PMID:12345678")
            expected_title: Optional expected title to validate against reference
            path: Optional path in data structure for error reporting

        Returns:
            ValidationResult with match details

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> # Would validate in real usage:
            >>> # result = validator.validate("quote", "PMID:12345678")
            >>> # With title validation:
            >>> # result = validator.validate("quote", "PMID:12345678", expected_title="Study Title")
        """
        reference = self.fetcher.fetch(reference_id)

        if not reference:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text=supporting_text,
                severity=ValidationSeverity.ERROR,
                message=f"Could not fetch reference: {reference_id}",
                path=path,
            )

        if not reference.content:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text=supporting_text,
                severity=ValidationSeverity.ERROR,
                message=f"No content available for reference: {reference_id}",
                path=path,
            )

        # Validate title if provided
        title_valid = True
        title_message = ""
        if expected_title and reference.title:
            if self.normalize_text(expected_title) != self.normalize_text(reference.title):
                title_valid = False
                title_message = (
                    f"Title mismatch: expected '{expected_title}' "
                    f"but got '{reference.title}'"
                )

        match = self.find_text_in_reference(supporting_text, reference)

        is_valid = match.found and title_valid

        if not is_valid:
            if not title_valid:
                message = title_message
            elif match.error_message:
                message = match.error_message
            else:
                message = f"Supporting text not found in reference {reference_id}"
        else:
            message = f"Supporting text validated successfully in {reference_id}"
            if expected_title:
                message += ", title validated"

        return ValidationResult(
            is_valid=is_valid,
            reference_id=reference_id,
            supporting_text=supporting_text,
            severity=ValidationSeverity.INFO if is_valid else ValidationSeverity.ERROR,
            message=message,
            match_result=match,
            path=path,
        )

    def find_text_in_reference(
        self,
        supporting_text: str,
        reference: ReferenceContent,
    ) -> SupportingTextMatch:
        """Find supporting text within reference content using substring matching.

        Uses deterministic substring matching after normalization.
        Supports [...] for editorial notes and ... for omitted text.

        Args:
            supporting_text: Text to find
            reference: Reference content to search

        Returns:
            SupportingTextMatch with results

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> ref = ReferenceContent(
            ...     reference_id="PMID:123",
            ...     content="The protein functions in cell cycle."
            ... )
            >>> match = validator.find_text_in_reference(
            ...     "protein functions",
            ...     ref
            ... )
            >>> match.found
            True
        """
        if not reference.content:
            return SupportingTextMatch(
                found=False,
                error_message="Reference has no content",
            )

        query_parts = self._split_query(supporting_text)

        # Empty query validation
        if not query_parts:
            return SupportingTextMatch(
                found=False,
                error_message="Query is empty after removing brackets and splitting",
            )

        return self._substring_match(query_parts, reference.content, supporting_text)

    def _split_query(self, text: str) -> list[str]:
        """Split query into parts separated by ... removing [...] editorial notes.

        Args:
            text: Query text

        Returns:
            List of text parts (empty if all text was in brackets)

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> validator._split_query("protein functions ... in cells")
            ['protein functions', 'in cells']
            >>> validator._split_query("protein [important] functions")
            ['protein functions']
            >>> validator._split_query("[editorial note]")
            []
        """
        text_without_brackets = re.sub(r"\[.*?\]", " ", text)
        parts = re.split(r"\s*\.{2,}\s*", text_without_brackets)
        parts = [p.strip() for p in parts if p.strip()]
        return parts

    def _substring_match(
        self,
        query_parts: list[str],
        content: str,
        original_query: Optional[str] = None,
    ) -> SupportingTextMatch:
        """Deterministic substring matching after normalization.

        All query parts must appear as substrings in the content (order independent).
        When validation fails, generates fuzzy matching suggestions to help users.

        Args:
            query_parts: List of query text parts
            content: Reference content to search
            original_query: Original query text for fuzzy suggestion generation

        Returns:
            SupportingTextMatch with optional suggestions when validation fails

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> match = validator._substring_match(
            ...     ["protein functions in cell cycle regulation"],
            ...     "The protein functions in cell cycle regulation pathway."
            ... )
            >>> match.found
            True
            >>> match.similarity_score
            1.0
        """
        normalized_content = self.normalize_text(content)
        matched_parts = []

        for part in query_parts:
            normalized_part = self.normalize_text(part)

            if normalized_part not in normalized_content:
                # Generate fuzzy suggestion for the failed part
                query_for_suggestion = original_query if original_query else part
                suggested_fix, best_match, similarity = self.generate_suggested_fix(
                    query_for_suggestion, content
                )

                return SupportingTextMatch(
                    found=False,
                    similarity_score=similarity / 100.0,  # Convert to 0-1 scale
                    error_message=f"Text part not found as substring: '{part}'",
                    suggested_fix=suggested_fix,
                    best_match=best_match,
                )

            matched_parts.append(part)

        return SupportingTextMatch(
            found=True,
            similarity_score=1.0,
            matched_text=" ... ".join(matched_parts),
        )

    def generate_suggested_fix(
        self,
        supporting_text: str,
        reference_content: str,
    ) -> tuple[Optional[str], Optional[str], float]:
        """Generate actionable fix suggestion when validation fails.

        Uses fuzzy matching ONLY for suggestions, NOT for validation.
        This helps users find the correct text when there are minor differences
        like capitalization changes or typos.

        Args:
            supporting_text: The text that failed strict validation
            reference_content: Full reference content to search

        Returns:
            Tuple of (suggested_fix, best_match, similarity_score 0-100)

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> # With exact case mismatch
            >>> fix, match, score = validator.generate_suggested_fix(
            ...     "jak1 protein is a tyrosine kinase",
            ...     "The JAK1 protein is a tyrosine kinase that activates STAT."
            ... )
            >>> score >= 90
            True
        """
        from linkml_reference_validator.validation.fuzzy_text_utils import (
            find_fuzzy_match_in_text,
        )

        found, similarity, best_match = find_fuzzy_match_in_text(
            supporting_text, reference_content, threshold=70.0
        )

        if best_match and similarity > 70:
            if similarity > 90:
                # Check if it's just a capitalization difference
                supporting_text_lower = supporting_text.lower()
                best_match_lower = best_match.lower()
                if supporting_text_lower == best_match_lower:
                    return (
                        f'Capitalization differs - try: "{best_match}"',
                        best_match,
                        similarity,
                    )
                else:
                    return (
                        f'Very close match ({similarity:.0f}%) - try: "{best_match}"',
                        best_match,
                        similarity,
                    )
            else:
                return (
                    f'Partial match found ({similarity:.0f}%): "{best_match}"',
                    best_match,
                    similarity,
                )

        return (None, best_match, similarity)

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text for comparison.

        Spells out Greek letters, removes punctuation, extra whitespace, and lowercases.

        Args:
            text: Text to normalize

        Returns:
            Normalized text

        Examples:
            >>> SupportingTextValidator.normalize_text("Hello, World!")
            'hello world'
            >>> SupportingTextValidator.normalize_text("T-Cell  Receptor")
            't cell receptor'
            >>> SupportingTextValidator.normalize_text("α-catenin")
            'alpha catenin'
            >>> SupportingTextValidator.normalize_text("β-actin")
            'beta actin'
            >>> SupportingTextValidator.normalize_text("γ-tubulin")
            'gamma tubulin'
        """
        # Greek letter mappings (both uppercase and lowercase)
        greek_map = {
            'α': 'alpha', 'Α': 'alpha',
            'β': 'beta', 'Β': 'beta',
            'γ': 'gamma', 'Γ': 'gamma',
            'δ': 'delta', 'Δ': 'delta',
            'ε': 'epsilon', 'Ε': 'epsilon',
            'ζ': 'zeta', 'Ζ': 'zeta',
            'η': 'eta', 'Η': 'eta',
            'θ': 'theta', 'Θ': 'theta',
            'ι': 'iota', 'Ι': 'iota',
            'κ': 'kappa', 'Κ': 'kappa',
            'λ': 'lambda', 'Λ': 'lambda',
            'μ': 'mu', 'Μ': 'mu',
            'ν': 'nu', 'Ν': 'nu',
            'ξ': 'xi', 'Ξ': 'xi',
            'ο': 'omicron', 'Ο': 'omicron',
            'π': 'pi', 'Π': 'pi',
            'ρ': 'rho', 'Ρ': 'rho',
            'σ': 'sigma', 'ς': 'sigma', 'Σ': 'sigma',
            'τ': 'tau', 'Τ': 'tau',
            'υ': 'upsilon', 'Υ': 'upsilon',
            'φ': 'phi', 'Φ': 'phi',
            'χ': 'chi', 'Χ': 'chi',
            'ψ': 'psi', 'Ψ': 'psi',
            'ω': 'omega', 'Ω': 'omega',
        }

        # Replace Greek letters with their spelled-out equivalents
        for greek, spelled in greek_map.items():
            text = text.replace(greek, spelled)

        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
