"""Validation of supporting text against reference content."""

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML  # type: ignore
from ruamel.yaml.error import YAMLError  # type: ignore

from linkml_reference_validator.cache import (
    _same_reference_id,
    cache_filename,
    disambiguated_cache_filename,
)
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.matching import (
    FIGURE_CONTENT_TYPES,
    SVG_LABEL_SEPARATOR,
    split_supporting_text,
)
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
    SupportingTextMatch,
    ValidationResult,
    ValidationSeverity,
)

logger = logging.getLogger(__name__)

#: Message used whenever a blank excerpt is rejected, so every layer reports
#: the same diagnosis for the same defect.
EMPTY_SUPPORTING_TEXT_MESSAGE = (
    "Supporting text is empty: an excerpt must quote actual text from the "
    "reference (the empty string trivially matches any document)"
)

#: An excerpt made only of editorial notes and ellipses quotes nothing, so it
#: is exactly as vacuous as a blank one and is diagnosed the same way.
NO_QUOTED_TEXT_MESSAGE = (
    "Supporting text is empty once editorial brackets and '...' separators are "
    "removed: it quotes nothing from the reference"
)


def _is_verified(excerpt: object) -> bool:
    """Whether a signed-excerpt entry records the source text it was verified against.

    Examples:
        >>> _is_verified({"text": "x", "verification": {"source_sha256": "ab12"}})
        True
        >>> _is_verified({"text": "x"})
        False
        >>> _is_verified("x")
        False
    """
    if not isinstance(excerpt, dict):
        return False
    verification = excerpt.get("verification")
    return isinstance(verification, dict) and bool(verification.get("source_sha256"))


def is_blank_text(value: object) -> bool:
    """Report whether a value is a string with no non-whitespace characters.

    Blank excerpts are the core of the "vacuous pass" bug: substring checks
    succeed for the empty string against every possible document, so a blank
    excerpt would otherwise be recorded as verified evidence.

    Args:
        value: Value to test; non-strings are never blank text

    Returns:
        True if the value is a string containing only whitespace (or nothing)

    Examples:
        >>> is_blank_text("")
        True
        >>> is_blank_text("   \\n")
        True
        >>> is_blank_text("protein functions")
        False
        >>> is_blank_text(None)
        False
    """
    return isinstance(value, str) and not value.strip()


#: Digits a citation marker welded onto a word can carry: decimal digits and
#: the superscript digits that text printing the marker itself uses (``ears¹``).
_CITATION_DIGITS = r"\d¹²³⁴⁵⁶⁷⁸⁹⁰"

#: Characters typesetters print for a minus sign: "-", the Unicode hyphens
#: U+2010 and U+2011, the figure dash U+2012, the en dash, "−" (U+2212) and the
#: small and fullwidth hyphen-minus. The em dash is left out: it is a
#: parenthetical dash, not a minus.
MINUS_SIGN_SPELLINGS = "-‐‑‒–−﹣－"


class SupportingTextValidator:
    """Validate that supporting text quotes are found in references.

    This validator checks that quoted text (supporting_text) actually
    appears in the referenced publication using deterministic substring matching.

    Supports:
    - Editorial notes in [square brackets] that are ignored by default
    - Configurable literal bracket patterns for bracketed source text
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
        # Keep only recent publication/figure-label normalizations, not each
        # query. Key by text rather than reference ID so refreshed content is
        # never matched against an earlier version. Each validator owns its
        # cache; finishing a batch releases it instead of retaining texts globally.
        # normalize_text is static, so the wrapper does not retain self in a cycle.
        self._normalize_reference_text = lru_cache(maxsize=128)(self.normalize_text)
        self._literal_bracket_regexes = [
            re.compile(pattern) for pattern in config.literal_bracket_patterns
        ]
        # Track distinct excerpts quoted per normalized reference ID so cumulative
        # fair-use caps (max_total_chars_per_reference and max_reference_fraction)
        # can be enforced across a validation run.
        self._quoted_by_reference: dict[str, dict[str, int]] = {}
        self._signed_excerpts_cache: dict[str, Optional[dict[str, Any]]] = {}

    def reset_fair_use_tracking(self) -> None:
        """Reset cumulative per-reference excerpt character counts."""
        self._quoted_by_reference.clear()

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
        # Check if this prefix should be skipped
        prefix = reference_id.split(":")[0].upper() if ":" in reference_id else ""
        skip_prefixes_upper = [p.upper() for p in self.config.skip_prefixes]

        if prefix and prefix in skip_prefixes_upper:
            return ValidationResult(
                is_valid=True,
                reference_id=reference_id,
                supporting_text="",
                severity=ValidationSeverity.INFO,
                skipped=True,
                message=f"Skipping title validation for reference with prefix '{prefix}': {reference_id}",
                path=path,
            )

        reference = self.fetcher.fetch(reference_id)

        if not reference:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text="",
                severity=self.config.unknown_prefix_severity,
                unavailable=True,
                message=f"Could not fetch reference: {reference_id}",
                path=path,
            )

        if not reference.title:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text="",
                severity=ValidationSeverity.ERROR,
                unavailable=True,
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
                title_checked=True,
                message=f"Title validated successfully for {reference_id}",
                path=path,
            )
        else:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text="",
                severity=ValidationSeverity.ERROR,
                title_checked=True,
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
            >>> # A blank excerpt is rejected without any reference lookup:
            >>> result = validator.validate("   ", "PMID:12345678")
            >>> result.is_valid
            False
        """
        # An insubstantial excerpt is a defect in the data regardless of what it
        # cites, so reject it before skip-prefix handling or any lookup.
        content_problem = self.check_excerpt_content(supporting_text)
        if content_problem:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text=supporting_text,
                severity=ValidationSeverity.ERROR,
                message=f"{content_problem}: {reference_id}",
                path=path,
            )

        # Check if this prefix should be skipped
        prefix = reference_id.split(":")[0].upper() if ":" in reference_id else ""
        skip_prefixes_upper = [p.upper() for p in self.config.skip_prefixes]

        if prefix and prefix in skip_prefixes_upper:
            return ValidationResult(
                is_valid=True,
                reference_id=reference_id,
                supporting_text=supporting_text,
                severity=ValidationSeverity.INFO,
                skipped=True,
                message=f"Skipping validation for reference with prefix '{prefix}': {reference_id}",
                path=path,
            )

        reference = self.fetcher.fetch(reference_id)
        signed_record = self._load_signed_excerpts(reference_id)
        signed_match = self._match_signed_excerpt(supporting_text, signed_record)

        if not reference and not signed_match:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text=supporting_text,
                severity=self.config.unknown_prefix_severity,
                unavailable=True,
                message=f"Could not fetch reference: {reference_id}",
                path=path,
            )

        if (not reference or not reference.content) and not signed_match:
            return ValidationResult(
                is_valid=False,
                reference_id=reference_id,
                supporting_text=supporting_text,
                severity=ValidationSeverity.ERROR,
                unavailable=True,
                message=f"No content available for reference: {reference_id}",
                path=path,
            )

        # Validate title if provided
        title_valid = True
        title_message = ""
        actual_title = (reference.title if reference and reference.title else None) or (
            str(signed_record["title"])
            if signed_record and isinstance(signed_record.get("title"), str) and signed_record.get("title")
            else None
        )
        # The message and title_checked report this, so they agree with it (#130).
        title_compared = bool(expected_title and actual_title)
        if expected_title and actual_title:  # spelled out for type narrowing
            if self.normalize_text(expected_title) != self.normalize_text(actual_title):
                title_valid = False
                title_message = (
                    f"Title mismatch: expected '{expected_title}' "
                    f"but got '{actual_title}'"
                )

        if reference and reference.content:
            match = self.find_text_in_reference(supporting_text, reference)
            if not match.found and signed_match is not None:
                match = signed_match
        elif signed_match is not None:
            match = signed_match
        else:
            match = SupportingTextMatch(
                found=False,
                error_message="Reference has no content",
            )

        fair_use_problem: Optional[str] = None
        if match.found and title_valid:
            fair_use_problem = self._check_and_record_reference_budget(
                supporting_text, reference_id, reference, signed_record
            )

        is_valid = match.found and title_valid and fair_use_problem is None

        if not is_valid:
            if not title_valid:
                message = title_message
            elif fair_use_problem:
                message = fair_use_problem
            elif match.error_message:
                message = match.error_message
            else:
                message = f"Supporting text not found in reference {reference_id}"
            # Add context when validation fails and only abstract was available
            if not match.found and reference and reference.content_type == "abstract_only":
                message += (
                    f" (note: only abstract available for {reference_id}, "
                    "full text may contain this excerpt)"
                )
        else:
            if match.match_location == "signed_excerpts":
                message = f"Supporting text verified via signed excerpt in {reference_id}"
            else:
                message = f"Supporting text validated successfully in {reference_id}"
            # Claim a title check only when one was made (#130).
            if title_compared:
                message += ", title validated"
            elif expected_title:
                message += "; title not checked: the reference has no title"

        return ValidationResult(
            is_valid=is_valid,
            reference_id=reference_id,
            supporting_text=supporting_text,
            severity=ValidationSeverity.INFO if is_valid else ValidationSeverity.ERROR,
            message=message,
            match_result=match,
            title_checked=title_compared,
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
            >>> validator.find_text_in_reference("", ref).found
            False
        """
        # Checked before content, so a thin excerpt is always diagnosed as thin
        # rather than blamed on the reference.
        content_problem = self.check_excerpt_content(supporting_text)
        if content_problem:
            return SupportingTextMatch(
                found=False,
                error_message=content_problem,
            )

        if not reference.content:
            return SupportingTextMatch(
                found=False,
                error_message="Reference has no content",
            )

        query_parts = self._split_query(supporting_text)
        return self._substring_match(
            query_parts, reference.content, supporting_text, self.searchable_texts(reference)
        )

    @classmethod
    def searchable_texts(cls, reference: ReferenceContent) -> list[str]:
        """The texts each quote part must fall within one of, and fuzzy matches are drawn from.

        A reference is one text, except an SVG figure: its labels are searched
        one at a time, because labels adjacent in the extracted text may sit
        anywhere in the figure and a quote running from one into the next says
        what neither does. ``...`` still joins parts from different labels.

        Examples:
            >>> figure = ReferenceContent(
            ...     reference_id="file:fig.svg", content="PTEN\\n\\nactivates AKT",
            ...     content_type="local_svg")
            >>> SupportingTextValidator.searchable_texts(figure)
            ['PTEN', 'activates AKT']
            >>> notes = ReferenceContent(reference_id="file:notes.md", content="PTEN\\n\\nactivates AKT")
            >>> SupportingTextValidator.searchable_texts(notes)
            ['PTEN\\n\\nactivates AKT']
        """
        content = reference.content or ""
        if reference.content_type in FIGURE_CONTENT_TYPES.values():
            return content.split(SVG_LABEL_SEPARATOR)
        return [content]

    def _split_query(self, text: str) -> list[str]:
        """Split query into parts while stripping editorial brackets by default.

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
            >>> config = ReferenceValidationConfig(literal_bracket_patterns=[r"\\d"])
            >>> validator = SupportingTextValidator(config)
            >>> validator._split_query("protein [important] binds [2Fe-2S] cluster")
            ['protein binds [2Fe-2S] cluster']
            >>> validator._split_query("[editorial note]")
            []
        """
        return split_supporting_text(text, self._literal_bracket_regexes)

    def count_quoted_characters(self, supporting_text: str) -> int:
        """Count the non-whitespace characters an excerpt actually quotes.

        Editorial brackets and ``...`` separators are excluded because they are
        never matched against the reference. Whitespace is excluded so that
        PDF-to-text extraction artifacts ("t he pro tein") measure the same as
        clean text, and so that no tokenizing is needed - chemical nomenclature
        and other punctuation-dense strings are counted in full.

        Args:
            supporting_text: The excerpt to measure

        Returns:
            Number of non-whitespace characters of quoted text

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> validator.count_quoted_characters("the protein")
            10
            >>> validator.count_quoted_characters("t he pro tein")
            10
            >>> validator.count_quoted_characters("protein [important] functions")
            16
            >>> validator.count_quoted_characters("2,3-dihydroxybenzoate")
            21
        """
        return sum(
            len(re.sub(r"\s", "", part))
            for part in self._split_query(supporting_text)
        )

    def check_excerpt_content(self, supporting_text: str) -> Optional[str]:
        """Report why an excerpt is too insubstantial to be evidence, if it is.

        Applied before any reference is fetched, because these are defects in
        the data itself: they hold regardless of what the excerpt cites, and no
        lookup could change the verdict.

        Args:
            supporting_text: The excerpt to check

        Returns:
            An error message, or None if the excerpt has enough substance

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> validator = SupportingTextValidator(config)
            >>> validator.check_excerpt_content("protein functions") is None
            True
            >>> "empty" in validator.check_excerpt_content("   ")
            True
            >>> "empty" in validator.check_excerpt_content("[editorial note]")
            True
            >>> strict = ReferenceValidationConfig(min_excerpt_length=20)
            >>> validator = SupportingTextValidator(strict)
            >>> "too short" in validator.check_excerpt_content("the gene")
            True
            >>> fair_use = ReferenceValidationConfig(max_excerpt_length=25, max_excerpt_part_length=15)
            >>> validator = SupportingTextValidator(fair_use)
            >>> validator.check_excerpt_content("Protein X ... binds Y") is None
            True
            >>> "contiguous part" in validator.check_excerpt_content("Protein X binds directly to Y")
            True
            >>> "too long" in validator.check_excerpt_content("Protein X binds ... directly to Y ... in the nucleus")
            True
        """
        if is_blank_text(supporting_text):
            return EMPTY_SUPPORTING_TEXT_MESSAGE

        length = self.count_quoted_characters(supporting_text)

        # Independent of min_excerpt_length: an excerpt that quotes nothing is
        # the defect this check exists for, not a threshold judgement.
        if length == 0:
            return NO_QUOTED_TEXT_MESSAGE

        if self.config.min_excerpt_length > 0 and length < self.config.min_excerpt_length:
            return (
                f"Supporting text is too short: {length} non-whitespace "
                f"characters of quoted text, minimum is "
                f"{self.config.min_excerpt_length} (min_excerpt_length)"
            )

        if self.config.max_excerpt_part_length > 0:
            for part in self._split_query(supporting_text):
                part_len = len(re.sub(r"\s", "", part))
                if part_len > self.config.max_excerpt_part_length:
                    return (
                        f"Supporting text contiguous part is too long for fair use: "
                        f"{part_len} non-whitespace characters in '{part[:40]}...', "
                        f"maximum per part is {self.config.max_excerpt_part_length} "
                        f"(max_excerpt_part_length; use '...' to omit non-essential words)"
                    )

        if self.config.max_excerpt_length > 0 and length > self.config.max_excerpt_length:
            return (
                f"Supporting text is too long for fair use: {length} non-whitespace "
                f"characters of quoted text, maximum is "
                f"{self.config.max_excerpt_length} (max_excerpt_length)"
            )

        return None

    def _load_signed_excerpts(self, reference_id: str) -> Optional[dict[str, Any]]:
        """Load the signed excerpts YAML file for ``reference_id`` if configured and present."""
        if not self.config.signed_excerpts_dir:
            return None
        normalized_id = self.fetcher.normalize_reference_id(reference_id)
        if normalized_id in self._signed_excerpts_cache:
            return self._signed_excerpts_cache[normalized_id]

        signed_dir = Path(self.config.signed_excerpts_dir)
        if not signed_dir.is_dir():
            self._signed_excerpts_cache[normalized_id] = None
            return None

        stem = Path(cache_filename(normalized_id)).stem
        disambig_stem = Path(disambiguated_cache_filename(normalized_id)).stem
        candidates = [
            signed_dir / f"{stem}.yaml",
            signed_dir / f"{stem}.yml",
            signed_dir / f"{disambig_stem}.yaml",
            signed_dir / f"{disambig_stem}.yml",
        ]
        yaml = YAML(typ="safe")
        for candidate in candidates:
            if not candidate.is_file():
                continue
            try:
                data = yaml.load(candidate.read_text(encoding="utf-8"))
            except (OSError, YAMLError, UnicodeError):
                continue
            if isinstance(data, dict):
                stored_id = data.get("reference_id")
                if stored_id is None or _same_reference_id(
                    self.fetcher.normalize_reference_id(str(stored_id)), normalized_id
                ):
                    self._signed_excerpts_cache[normalized_id] = data
                    return data

        self._signed_excerpts_cache[normalized_id] = None
        return None

    @staticmethod
    def _collapse_whitespace(text: str) -> str:
        """Collapse whitespace runs to single spaces and strip ends."""
        return re.sub(r"\s+", " ", text).strip()

    def _match_signed_excerpt(
        self, supporting_text: str, signed_record: Optional[dict[str, Any]]
    ) -> Optional[SupportingTextMatch]:
        """Return a match if ``supporting_text`` exact-matches an entry in ``signed_record``.

        Exact match (after folding whitespace runs) is required so any deviation
        from the verified excerpt in the private store is flagged. With
        ``signed_excerpts_require_verification``, only entries carrying a
        ``verification`` record (see :mod:`~linkml_reference_validator.excerpt_signing`)
        are considered.
        """
        if not signed_record:
            return None
        excerpts = signed_record.get("excerpts")
        if not isinstance(excerpts, list):
            return None
        target = self._collapse_whitespace(supporting_text)
        if not target:
            return None

        for item in excerpts:
            if isinstance(item, str):
                candidate = item
            elif isinstance(item, dict):
                raw = (
                    item.get("text")
                    or item.get("snippet")
                    or item.get("supporting_text")
                )
                candidate = raw if isinstance(raw, str) else ""
            else:
                continue
            if self.config.signed_excerpts_require_verification and not _is_verified(item):
                continue
            if candidate and self._collapse_whitespace(candidate) == target:
                return SupportingTextMatch(
                    found=True,
                    similarity_score=1.0,
                    matched_text=candidate,
                    match_location="signed_excerpts",
                )
        return None

    def _check_and_record_reference_budget(
        self,
        supporting_text: str,
        reference_id: str,
        reference: Optional[ReferenceContent],
        signed_record: Optional[dict[str, Any]],
    ) -> Optional[str]:
        """Check and update cumulative per-reference character and fraction caps."""
        max_total = self.config.max_total_chars_per_reference
        max_fraction = self.config.max_reference_fraction
        if max_total <= 0 and max_fraction <= 0.0:
            return None

        normalized_id = self.fetcher.normalize_reference_id(reference_id)
        excerpt_key = self._collapse_whitespace(supporting_text)
        char_count = self.count_quoted_characters(supporting_text)

        seen = self._quoted_by_reference.setdefault(normalized_id, {})
        previous_total = sum(
            count for key, count in seen.items() if key != excerpt_key
        )
        new_total = previous_total + char_count

        if max_total > 0 and new_total > max_total:
            return (
                f"Cumulative quoted text for {reference_id} exceeds fair-use limit: "
                f"{new_total} non-whitespace characters across {len(seen) + (0 if excerpt_key in seen else 1)} "
                f"excerpt(s), maximum is {max_total} (max_total_chars_per_reference)"
            )

        if max_fraction > 0.0:
            ref_chars: Optional[int] = None
            if reference and reference.content:
                ref_chars = len(re.sub(r"\s", "", reference.content))
            elif signed_record and isinstance(signed_record.get("source_char_count"), int):
                ref_chars = int(signed_record["source_char_count"])
            if ref_chars and ref_chars > 0:
                allowed_chars = int(ref_chars * max_fraction)
                if new_total > allowed_chars:
                    return (
                        f"Cumulative quoted text for {reference_id} exceeds fair-use fraction: "
                        f"{new_total} of {ref_chars} non-whitespace characters "
                        f"({new_total / ref_chars:.1%}), maximum allowed is "
                        f"{max_fraction:.1%} ({allowed_chars} characters, max_reference_fraction)"
                    )

        seen[excerpt_key] = char_count
        return None

    def _substring_match(
        self,
        query_parts: list[str],
        content: str,
        original_query: Optional[str] = None,
        searchable: Optional[list[str]] = None,
    ) -> SupportingTextMatch:
        """Deterministic substring matching after normalization.

        Each query part must appear as a substring of one searchable text (order independent).
        With ``searchable`` (see :meth:`searchable_texts`), each part must appear
        within one of those texts instead, and the fuzzy suggestion is the best
        drawn from any one of them.
        When validation fails, generates fuzzy matching suggestions to help users.

        Args:
            query_parts: List of query text parts
            content: Reference content to search
            original_query: Original query text for fuzzy suggestion generation
            searchable: Texts a part must fall within one of; defaults to
                the whole content

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
            >>> validator._substring_match([], "any document at all").found
            False
        """
        # Guarded here rather than in the caller: with no parts the loop below
        # never runs and every quote "matches", which is the vacuous pass this
        # whole check exists to prevent. check_excerpt_content already rejects
        # such excerpts upstream, so this is the invariant that keeps the
        # primitive honest if it is ever called from somewhere else.
        if not query_parts:
            return SupportingTextMatch(
                found=False,
                error_message=NO_QUOTED_TEXT_MESSAGE,
            )

        texts = searchable if searchable is not None else [content]
        normalized_texts = [self._normalize_reference_text(text) for text in texts]
        matched_parts = []

        for part in query_parts:
            normalized_part = self.normalize_text(part)

            if not any(self.contains_words(normalized_part, text) for text in normalized_texts):
                # Generate fuzzy suggestion for the failed part, from one text
                # at a time: a suggestion spanning two would fail again.
                query_for_suggestion = original_query if original_query else part
                suggested_fix, best_match, similarity = max(
                    (self.generate_suggested_fix(query_for_suggestion, text) for text in texts),
                    key=lambda suggestion: suggestion[2],
                )

                error_message = f"Text part not found as substring: '{part}'"
                if any(normalized_part in text for text in normalized_texts):
                    error_message = (
                        f"Text part occurs only inside longer words: '{part}'. "
                        "A match must start and end on whole words, so a quote "
                        "of 'activates' does not match 'inactivates'"
                    )
                elif len(normalized_texts) > 1 and self.contains_words(
                    normalized_part, " ".join(normalized_texts)
                ):
                    error_message = (
                        f"Text part is not within any one figure label: '{part}'. "
                        "It matches only labels joined in document order, so it "
                        "may run across them: quote each label on its own, "
                        "joined with '...'"
                    )
                return SupportingTextMatch(
                    found=False,
                    similarity_score=similarity / 100.0,  # Convert to 0-1 scale
                    error_message=error_message,
                    suggested_fix=suggested_fix,
                    best_match=best_match,
                )

            matched_parts.append(part)

        return SupportingTextMatch(
            found=True,
            similarity_score=1.0,
            matched_text=" ... ".join(matched_parts),
        )

    @staticmethod
    def contains_words(part: str, text: str) -> bool:
        """Whether normalized ``part`` occurs in normalized ``text`` as whole words.

        A bare substring test lets a quote begin or end inside a word, so
        "activates" would match "inactivates" and a quote stating the
        opposite of the reference would pass. Both arguments must already be
        normalized with :meth:`normalize_text`, which collapses whitespace
        to single spaces, so padding each with one space anchors the part
        on word boundaries at both ends.

        One allowance: when the part ends in a letter, the reference word it
        ends on may carry trailing digits. Extraction welds superscript
        citations onto the word before them (JATS ``suppressor<sup>12</sup>``,
        PMC HTML and PDF text all give ``suppressor12``, and text that prints
        the citation itself as superscript gives ``ears¹``), and a quote of
        that sentence must not fail on its last word. A part ending in a digit gets
        no allowance, so ``10`` never matches ``105``.

        An empty part (one that was all punctuation) is found, as with a
        plain substring test; a quote with no quoted text at all is
        rejected before matching.

        Args:
            part: Normalized query part
            text: Normalized text to search

        Returns:
            True if ``part`` starts and ends on word boundaries within ``text``

        Examples:
            >>> SupportingTextValidator.contains_words("activates akt", "pten activates akt")
            True
            >>> SupportingTextValidator.contains_words("activates akt", "pten inactivates akt")
            False
            >>> SupportingTextValidator.contains_words("pten is not", "pten is nothing")
            False
            >>> SupportingTextValidator.contains_words("pten", "pten")
            True
            >>> SupportingTextValidator.contains_words("tumor suppressor", "a tumor suppressor12 in")
            True
            >>> SupportingTextValidator.contains_words("tumor suppressor", "a tumor suppressor1,2")
            True
            >>> SupportingTextValidator.contains_words("a dose of 10", "a dose of 105 mg")
            False
            >>> SupportingTextValidator.contains_words("small ears", "small ears¹ ³ both")
            True
            >>> SupportingTextValidator.contains_words("", "anything")
            True
        """
        if not part:
            return True
        if f" {part} " in f" {text} ":
            return True
        if not part[-1].isalpha():
            return False
        citation = rf"(?:^| ){re.escape(part)}[{_CITATION_DIGITS}][{_CITATION_DIGITS},]*(?: |$)"
        return re.search(citation, text) is not None

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

        Folds Latin compatibility ligatures, spells out Greek letters, removes
        punctuation and extra whitespace, and lowercases. A point or comma
        between two digits is kept, so a number such as ``10.5`` stays one
        word. Symbols that carry meaning become words: ``<`` ``>`` ``≤`` ``≥``
        (and ``<=`` ``>=``) become ``lt`` ``gt`` ``le`` ``ge``, ``±`` and
        ``+/-`` become ``pm``, and a minus sign before a number stays on it as
        ``neg``. Publisher spellings of these count the same: ``>/=`` and
        ``</=`` (MEDLINE's ASCII for ``≥`` ``≤``), a middle-dot decimal
        (``57·4``), and an en dash or Unicode hyphen printed as a minus sign
        or inside ``+/–``. Arrows such as ``->`` are punctuation. The same normalization
        applies to reference content and queries (including split query
        parts).

        IJ (Ĳ/ĳ) is folded because Unicode defines its compatibility decomposition
        as I + J. Distinct letters Æ/æ and Œ/œ are preserved: equating them with
        AE/OE would broaden validation beyond typographic repair. An explicit
        table avoids broad NFKC normalization, which also changes scientific
        notation such as superscripts and subscripts (``10⁶`` would read as
        ``106``). The micro sign ``µ`` and the variant Greek forms (``ϕ ϵ ϑ ϐ
        ϖ ϰ ϱ``) are spelled out like the ordinary letters they stand for, since
        sources use them interchangeably: ``5 µM`` matches ``5 μM``.

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
            >>> SupportingTextValidator.normalize_text("amyloid ﬁbrils")
            'amyloid fibrils'
            >>> SupportingTextValidator.normalize_text("ﬀ ﬁ ﬂ ﬃ ﬄ ﬅ ﬆ Ĳ ĳ")
            'ff fi fl ffi ffl st st ij ij'
            >>> SupportingTextValidator.normalize_text("10.5 mM, 3,4-dihydroxy, p<0.05.")
            '10.5 mm 3,4 dihydroxy p lt 0.05'
            >>> SupportingTextValidator.normalize_text("p<0.05, 5 ± 2, by −2.5 fold")
            'p lt 0.05 5 pm 2 by neg2.5 fold'
            >>> SupportingTextValidator.normalize_text("57·4, ≥ 4 or >/= 4, (z score, –1.98), Wdr26+/–")
            '57.4 ge 4 or ge 4 z score neg1.98 wdr26 pm'
            >>> SupportingTextValidator.normalize_text("IL-6, Ca2+-dependent, A -> B")
            'il 6 ca2 dependent a b'
            >>> SupportingTextValidator.normalize_text("Æ Œ æ œ H₂O 10⁶")
            'æ œ æ œ h₂o 10⁶'
            >>> SupportingTextValidator.normalize_text("5 µM") == SupportingTextValidator.normalize_text("5 μM")
            True
        """
        # Only compatibility ligatures; do not apply general Unicode NFKC.
        ligature_map = {
            "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
            "ﬅ": "st", "ﬆ": "st", "Ĳ": "IJ", "ĳ": "ij",
        }
        text = text.translate({ord(ligature): expanded for ligature, expanded in ligature_map.items()})

        # Greek letter mappings: both cases, the micro sign and variant forms
        greek_map = {
            'α': 'alpha', 'Α': 'alpha',
            'β': 'beta', 'Β': 'beta', 'ϐ': 'beta',
            'γ': 'gamma', 'Γ': 'gamma',
            'δ': 'delta', 'Δ': 'delta',
            'ε': 'epsilon', 'Ε': 'epsilon', 'ϵ': 'epsilon',
            'ζ': 'zeta', 'Ζ': 'zeta',
            'η': 'eta', 'Η': 'eta',
            'θ': 'theta', 'Θ': 'theta', 'ϑ': 'theta',
            'ι': 'iota', 'Ι': 'iota',
            'κ': 'kappa', 'Κ': 'kappa', 'ϰ': 'kappa',
            'λ': 'lambda', 'Λ': 'lambda',
            'μ': 'mu', 'Μ': 'mu', 'µ': 'mu',
            'ν': 'nu', 'Ν': 'nu',
            'ξ': 'xi', 'Ξ': 'xi',
            'ο': 'omicron', 'Ο': 'omicron',
            'π': 'pi', 'Π': 'pi', 'ϖ': 'pi',
            'ρ': 'rho', 'Ρ': 'rho', 'ϱ': 'rho',
            'σ': 'sigma', 'ς': 'sigma', 'Σ': 'sigma',
            'τ': 'tau', 'Τ': 'tau',
            'υ': 'upsilon', 'Υ': 'upsilon',
            'φ': 'phi', 'Φ': 'phi', 'ϕ': 'phi',
            'χ': 'chi', 'Χ': 'chi',
            'ψ': 'psi', 'Ψ': 'psi',
            'ω': 'omega', 'Ω': 'omega',
        }

        # Replace Greek letters with their spelled-out equivalents
        for greek, spelled in greek_map.items():
            text = text.replace(greek, spelled)

        text = text.lower()
        # Collapse whitespace first, so the rules below that look one
        # character back see a single space however the source spaced it.
        text = re.sub(r"\s+", " ", text)

        # A middle dot between digits is a decimal point (the Lancet journals
        # print 57·4 for 57.4), so it is spelled as one before the decimal rule
        # below keeps a point between digits. Only after a whole number: in a
        # formula such as MgCl2·6H2O the dot joins a hydrate, not a decimal.
        text = re.sub(r"(?<![^\W_])(\d+)[·∙⋅](?=\d)", r"\1.", text)

        # Symbols that carry meaning become words before punctuation is
        # stripped, so a quote that reverses a comparison or drops a sign
        # fails (issue #125). Arrows go first, or "->" would read as ">"; a
        # "<-" before a digit is "<" then a negative number, not an arrow.
        text = re.sub(r"<[-=]+>|[-=]+>|<-+(?!\d)", " ", text)
        # MEDLINE abstracts transliterate ≤ and ≥ as "</=" and ">/=".
        text = re.sub(r"</?=|[≤⩽]", " le ", text)
        text = re.sub(r">/?=|[≥⩾]", " ge ", text)
        text = text.replace("<", " lt ").replace(">", " gt ")
        # A bare "+-" before a letter is a charge then a hyphen
        # ("Ca2+-dependent"); "+/-" is plus-minus even before one ("+/-SD").
        # "+/–" with any minus spelling is "+/-".
        # Escaped, so no reordering of the string can make "-" a range.
        dash = re.escape(MINUS_SIGN_SPELLINGS)
        text = re.sub(rf"±|\+/[{dash}]|\+[{dash}](?![^\W\d_])", " pm ", text)
        # A minus sign stays on its number, so "2.5" does not match "-2.5".
        # It is a sign only at the start, after a space, an opening bracket or
        # curly quote, "=", ":", "~", "≈" or an exponent's "^" (10^-5 is not
        # 10^5); anywhere else it is a hyphen or a range dash: IL-6, 3-5,
        # 3'-5', 10%-20%, 5°-10°. Straight quotes are left out because they
        # double as primes and inch marks (5"-10"). Any dash above counts,
        # since an en dash in sign position ("z score, –1.98") is a minus.
        sign_position = r"(?:^|(?<=[\s(\[{=:~≈^“‘«]))"
        text = re.sub(rf"{sign_position}[{dash}](?=\d)", "neg", text)
        # "−" (U+2212) is never a range dash, so it is a sign even when set
        # off from its number by a space ("from − 2.92") -- unless a number
        # comes before it, where it is a subtraction ("10 − 2").
        text = re.sub(rf"{sign_position}(?<![\d)\]%]\s)−\s+(?=\d)", "neg", text)

        # A point or comma between digits is part of the number: splitting
        # "10.5" into "10 5" would let a quote of "5 mM" match "10.5 mM".
        text = re.sub(r"(?!(?<=\d)[.,](?=\d))[^\w\s]", " ", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip()
