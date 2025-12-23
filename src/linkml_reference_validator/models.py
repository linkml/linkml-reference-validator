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


class RepairActionType(str, Enum):
    """Types of repair actions.

    Examples:
        >>> RepairActionType.CHARACTER_NORMALIZATION.value
        'CHARACTER_NORMALIZATION'
        >>> RepairActionType.ELLIPSIS_INSERTION.value
        'ELLIPSIS_INSERTION'
    """

    CHARACTER_NORMALIZATION = "CHARACTER_NORMALIZATION"  # Unicode/symbol fixes
    ELLIPSIS_INSERTION = "ELLIPSIS_INSERTION"  # Insert ... between non-contiguous parts
    FUZZY_CORRECTION = "FUZZY_CORRECTION"  # Replace with closest matching text
    REMOVAL = "REMOVAL"  # Flag for removal (fabricated/not found)
    UNVERIFIABLE = "UNVERIFIABLE"  # No abstract available


class RepairConfidence(str, Enum):
    """Confidence levels for repair actions.

    Examples:
        >>> RepairConfidence.HIGH.value
        'HIGH'
        >>> RepairConfidence.from_score(0.98) == RepairConfidence.HIGH
        True
        >>> RepairConfidence.from_score(0.88) == RepairConfidence.MEDIUM
        True
        >>> RepairConfidence.from_score(0.65) == RepairConfidence.LOW
        True
        >>> RepairConfidence.from_score(0.30) == RepairConfidence.VERY_LOW
        True
    """

    HIGH = "HIGH"  # 0.95-1.00 - Auto-fix safe
    MEDIUM = "MEDIUM"  # 0.80-0.95 - Suggest fix
    LOW = "LOW"  # 0.50-0.80 - Flag for review
    VERY_LOW = "VERY_LOW"  # 0.00-0.50 - Recommend removal

    @classmethod
    def from_score(cls, score: float) -> "RepairConfidence":
        """Determine confidence level from similarity score.

        Args:
            score: Similarity score between 0.0 and 1.0

        Returns:
            Appropriate confidence level

        Examples:
            >>> RepairConfidence.from_score(1.0) == RepairConfidence.HIGH
            True
            >>> RepairConfidence.from_score(0.95) == RepairConfidence.HIGH
            True
            >>> RepairConfidence.from_score(0.90) == RepairConfidence.MEDIUM
            True
            >>> RepairConfidence.from_score(0.70) == RepairConfidence.LOW
            True
            >>> RepairConfidence.from_score(0.40) == RepairConfidence.VERY_LOW
            True
        """
        if score >= 0.95:
            return cls.HIGH
        elif score >= 0.80:
            return cls.MEDIUM
        elif score >= 0.50:
            return cls.LOW
        else:
            return cls.VERY_LOW


@dataclass
class RepairAction:
    """A single repair action to apply.

    Examples:
        >>> action = RepairAction(
        ...     action_type=RepairActionType.CHARACTER_NORMALIZATION,
        ...     original_text="CO2 levels",
        ...     repaired_text="CO₂ levels",
        ...     confidence=RepairConfidence.HIGH,
        ...     similarity_score=0.98,
        ...     description="Replaced ASCII subscript"
        ... )
        >>> action.action_type.value
        'CHARACTER_NORMALIZATION'
        >>> action.can_auto_fix
        True
    """

    action_type: RepairActionType
    original_text: str
    repaired_text: Optional[str] = None
    confidence: RepairConfidence = RepairConfidence.LOW
    similarity_score: float = 0.0
    description: str = ""
    reference_id: Optional[str] = None
    path: Optional[str] = None  # Location in data structure

    @property
    def can_auto_fix(self) -> bool:
        """Whether this action can be automatically applied.

        Examples:
            >>> action = RepairAction(
            ...     action_type=RepairActionType.CHARACTER_NORMALIZATION,
            ...     original_text="test",
            ...     repaired_text="TEST",
            ...     confidence=RepairConfidence.HIGH
            ... )
            >>> action.can_auto_fix
            True
            >>> action2 = RepairAction(
            ...     action_type=RepairActionType.REMOVAL,
            ...     original_text="test",
            ...     confidence=RepairConfidence.VERY_LOW
            ... )
            >>> action2.can_auto_fix
            False
        """
        # Never auto-remove, always require review
        if self.action_type == RepairActionType.REMOVAL:
            return False
        if self.action_type == RepairActionType.UNVERIFIABLE:
            return False
        return self.confidence == RepairConfidence.HIGH and self.repaired_text is not None


@dataclass
class RepairResult:
    """Result of attempting to repair a single validation error.

    Examples:
        >>> result = RepairResult(
        ...     reference_id="PMID:12345678",
        ...     original_text="CO2 levels",
        ...     was_valid=False,
        ...     is_repaired=True,
        ...     repaired_text="CO₂ levels",
        ...     actions=[RepairAction(
        ...         action_type=RepairActionType.CHARACTER_NORMALIZATION,
        ...         original_text="CO2",
        ...         repaired_text="CO₂",
        ...         confidence=RepairConfidence.HIGH
        ...     )]
        ... )
        >>> result.is_repaired
        True
    """

    reference_id: str
    original_text: str
    was_valid: bool = False
    is_repaired: bool = False
    repaired_text: Optional[str] = None
    actions: list[RepairAction] = field(default_factory=list)
    message: str = ""
    path: Optional[str] = None


@dataclass
class RepairReport:
    """Summary report of all repair results.

    Examples:
        >>> report = RepairReport()
        >>> report.add_result(RepairResult(
        ...     reference_id="PMID:1",
        ...     original_text="test",
        ...     was_valid=False,
        ...     is_repaired=True,
        ...     repaired_text="TEST"
        ... ))
        >>> report.total_items
        1
        >>> report.repaired_count
        1
    """

    results: list[RepairResult] = field(default_factory=list)

    def add_result(self, result: RepairResult) -> None:
        """Add a repair result to the report."""
        self.results.append(result)

    @property
    def total_items(self) -> int:
        """Total number of items processed."""
        return len(self.results)

    @property
    def already_valid_count(self) -> int:
        """Number of items that were already valid."""
        return sum(1 for r in self.results if r.was_valid)

    @property
    def repaired_count(self) -> int:
        """Number of items that were repaired."""
        return sum(1 for r in self.results if r.is_repaired)

    @property
    def auto_fixed_count(self) -> int:
        """Number of items with high-confidence auto-fixes."""
        count = 0
        for r in self.results:
            if r.is_repaired and any(a.can_auto_fix for a in r.actions):
                count += 1
        return count

    @property
    def suggested_count(self) -> int:
        """Number of items with medium-confidence suggestions."""
        count = 0
        for r in self.results:
            if not r.was_valid:
                has_medium = any(
                    a.confidence == RepairConfidence.MEDIUM for a in r.actions
                )
                if has_medium:
                    count += 1
        return count

    @property
    def removal_count(self) -> int:
        """Number of items flagged for removal."""
        count = 0
        for r in self.results:
            has_removal = any(
                a.action_type == RepairActionType.REMOVAL for a in r.actions
            )
            if has_removal:
                count += 1
        return count

    @property
    def unverifiable_count(self) -> int:
        """Number of items that cannot be verified (no abstract)."""
        count = 0
        for r in self.results:
            has_unverifiable = any(
                a.action_type == RepairActionType.UNVERIFIABLE for a in r.actions
            )
            if has_unverifiable:
                count += 1
        return count


class RepairConfig(BaseModel):
    """Configuration for repair operations.

    Examples:
        >>> config = RepairConfig()
        >>> config.auto_fix_threshold
        0.95
        >>> config.suggest_threshold
        0.8
        >>> config = RepairConfig(auto_fix_threshold=0.98)
        >>> config.auto_fix_threshold
        0.98
    """

    auto_fix_threshold: float = Field(
        default=0.95,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for automatic fixes (0.95-1.00)",
    )
    suggest_threshold: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score for suggestions (0.80-0.95)",
    )
    removal_threshold: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description="Below this threshold, recommend removal (0.00-0.50)",
    )
    dry_run: bool = Field(
        default=True,
        description="If True, only show what would be changed without modifying files",
    )
    create_backup: bool = Field(
        default=True,
        description="Create backup of original file before modifying",
    )
    character_mappings: dict[str, str] = Field(
        default_factory=lambda: {
            "+/-": "±",
            "+-": "±",
            "CO2": "CO₂",
            "H2O": "H₂O",
            "O2": "O₂",
            "N2": "N₂",
        },
        description="Character substitution mappings for normalization",
    )
    skip_references: list[str] = Field(
        default_factory=list,
        description="Reference IDs to skip during repair (known issues)",
    )
    trusted_low_similarity: list[str] = Field(
        default_factory=list,
        description="Reference IDs that are trusted despite low similarity scores",
    )


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
        >>> config = ReferenceValidationConfig(
        ...     reference_prefix_map={"geo": "GEO", "NCBIGeo": "GEO"}
        ... )
        >>> config.reference_prefix_map["geo"]
        'GEO'
    """

    cache_dir: Path = Field(
        default=Path("references_cache"),
        description="Directory for caching downloaded references",
    )
    reference_base_dir: Optional[Path] = Field(
        default=None,
        description="Base directory for resolving relative file: references. If None, uses CWD.",
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
    reference_prefix_map: dict[str, str] = Field(
        default_factory=dict,
        description=(
            "Optional mapping of alternate prefixes to canonical prefixes, "
            "e.g. {'geo': 'GEO', 'NCBIGeo': 'GEO'}"
        ),
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
