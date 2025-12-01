"""Data models and configuration for linkml-reference-validator."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class ValidationSeverity(str, Enum):
    """Severity levels for validation results."""

    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class ReferenceValidationConfig(BaseModel):
    r"""Configuration for reference validation.

    Examples:
        >>> config = ReferenceValidationConfig()
        >>> config.cache_dir
        PosixPath('references_cache')
        >>> config.rate_limit_delay
        0.5
        >>> config = ReferenceValidationConfig(
        ...     supporting_text_regex=r'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"',
        ...     text_group=1,
        ...     ref_group=2
        ... )
        >>> config.supporting_text_regex
        'ex:supporting_text="([^"]*)\\[(\\S+:\\S+)\\]"'
    """

    cache_dir: Path = Field(
        default=Path("references_cache"),
        description="Directory for caching downloaded references",
    )
    rate_limit_delay: float = Field(
        default=0.5,
        ge=0.0,
        description="Delay in seconds between API requests",
    )
    email: str = Field(
        default="linkml-reference-validator@example.com",
        description="Email for NCBI Entrez API (required by NCBI)",
    )
    supporting_text_regex: Optional[str] = Field(
        default=None,
        description="Regular expression for extracting supporting text and reference IDs from text files",
    )
    text_group: int = Field(
        default=1,
        ge=1,
        description="Regex capture group number containing the supporting text",
    )
    ref_group: int = Field(
        default=2,
        ge=1,
        description="Regex capture group number containing the reference ID",
    )

    def get_cache_dir(self) -> Path:
        """Create and return the cache directory.

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> cache_dir = config.get_cache_dir()
            >>> cache_dir.exists()
            True
        """
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        return self.cache_dir


@dataclass
class ReferenceContent:
    """Content retrieved from a reference.

    Examples:
        >>> ref = ReferenceContent(
        ...     reference_id="PMID:12345678",
        ...     title="Example Article",
        ...     content="This is the abstract and full text.",
        ...     content_type="abstract_only"
        ... )
        >>> ref.reference_id
        'PMID:12345678'
    """

    reference_id: str
    title: Optional[str] = None
    content: Optional[str] = None
    content_type: str = "unknown"  # abstract_only, full_text, etc.
    authors: Optional[list[str]] = None
    journal: Optional[str] = None
    year: Optional[str] = None
    doi: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class SupportingTextMatch:
    """Result of matching supporting text against reference content.

    Examples:
        >>> match = SupportingTextMatch(
        ...     found=True,
        ...     similarity_score=0.95,
        ...     matched_text="This is the exact text found",
        ...     match_location="abstract"
        ... )
        >>> match.found
        True
        >>> match.similarity_score
        0.95

        >>> # With fuzzy matching suggestion
        >>> match = SupportingTextMatch(
        ...     found=False,
        ...     similarity_score=0.0,
        ...     error_message="Text not found",
        ...     suggested_fix="Capitalization differs - try: 'JAK1 protein'",
        ...     best_match="JAK1 protein is a tyrosine kinase"
        ... )
        >>> match.suggested_fix
        "Capitalization differs - try: 'JAK1 protein'"
    """

    found: bool
    similarity_score: float = 0.0
    matched_text: Optional[str] = None
    match_location: Optional[str] = None  # abstract, full_text, etc.
    error_message: Optional[str] = None
    suggested_fix: Optional[str] = None  # Actionable suggestion when validation fails
    best_match: Optional[str] = None  # Closest matching text found via fuzzy matching


@dataclass
class ValidationResult:
    """Result of validating a single supporting text against a reference.

    Examples:
        >>> result = ValidationResult(
        ...     is_valid=True,
        ...     reference_id="PMID:12345678",
        ...     supporting_text="example quote",
        ...     severity=ValidationSeverity.INFO
        ... )
        >>> result.is_valid
        True
    """

    is_valid: bool
    reference_id: str
    supporting_text: str
    severity: ValidationSeverity = ValidationSeverity.ERROR
    message: Optional[str] = None
    match_result: Optional[SupportingTextMatch] = None
    path: Optional[str] = None  # Path in data structure (e.g., "annotations[0].evidence")


@dataclass
class ValidationReport:
    """Summary report of all validation results.

    Examples:
        >>> report = ValidationReport()
        >>> report.add_result(ValidationResult(
        ...     is_valid=True,
        ...     reference_id="PMID:12345678",
        ...     supporting_text="test"
        ... ))
        >>> report.total_validations
        1
        >>> report.valid_count
        1
    """

    results: list[ValidationResult] = field(default_factory=list)

    def add_result(self, result: ValidationResult) -> None:
        """Add a validation result to the report.

        Examples:
            >>> report = ValidationReport()
            >>> report.add_result(ValidationResult(
            ...     is_valid=False,
            ...     reference_id="PMID:99999",
            ...     supporting_text="not found"
            ... ))
            >>> report.total_validations
            1
            >>> report.error_count
            1
        """
        self.results.append(result)

    @property
    def total_validations(self) -> int:
        """Total number of validations performed.

        Examples:
            >>> report = ValidationReport()
            >>> report.total_validations
            0
        """
        return len(self.results)

    @property
    def valid_count(self) -> int:
        """Number of valid results.

        Examples:
            >>> report = ValidationReport()
            >>> report.add_result(ValidationResult(
            ...     is_valid=True,
            ...     reference_id="PMID:1",
            ...     supporting_text="test"
            ... ))
            >>> report.valid_count
            1
        """
        return sum(1 for r in self.results if r.is_valid)

    @property
    def invalid_count(self) -> int:
        """Number of invalid results.

        Examples:
            >>> report = ValidationReport()
            >>> report.add_result(ValidationResult(
            ...     is_valid=False,
            ...     reference_id="PMID:1",
            ...     supporting_text="test"
            ... ))
            >>> report.invalid_count
            1
        """
        return sum(1 for r in self.results if not r.is_valid)

    @property
    def error_count(self) -> int:
        """Number of errors.

        Examples:
            >>> report = ValidationReport()
            >>> report.add_result(ValidationResult(
            ...     is_valid=False,
            ...     reference_id="PMID:1",
            ...     supporting_text="test",
            ...     severity=ValidationSeverity.ERROR
            ... ))
            >>> report.error_count
            1
        """
        return sum(1 for r in self.results if r.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Number of warnings.

        Examples:
            >>> report = ValidationReport()
            >>> report.add_result(ValidationResult(
            ...     is_valid=False,
            ...     reference_id="PMID:1",
            ...     supporting_text="test",
            ...     severity=ValidationSeverity.WARNING
            ... ))
            >>> report.warning_count
            1
        """
        return sum(1 for r in self.results if r.severity == ValidationSeverity.WARNING)

    @property
    def is_valid(self) -> bool:
        """Whether all validations passed (no errors).

        Examples:
            >>> report = ValidationReport()
            >>> report.is_valid
            True
            >>> report.add_result(ValidationResult(
            ...     is_valid=False,
            ...     reference_id="PMID:1",
            ...     supporting_text="test",
            ...     severity=ValidationSeverity.ERROR
            ... ))
            >>> report.is_valid
            False
        """
        return self.error_count == 0
