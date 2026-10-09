"""Public, forward-compatible contract for Markdown reference cache files.

Validation is read-only and independent of extractor freshness or source policy.
Unknown fields are preserved, so consumers can add metadata without a namespace.
"""

from dataclasses import dataclass, field
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


class CacheSupplementaryFile(BaseModel):
    """Typed supplementary-file metadata, with unrestricted extension fields."""

    model_config = ConfigDict(extra="allow", strict=True)

    filename: str = Field(min_length=1)
    download_url: str | None = None
    content_type: str | None = None
    size_bytes: int | None = None
    checksum: str | None = None
    description: str | None = None
    local_path: str | None = None


class CacheFrontmatter(BaseModel):
    """The library-owned schema for a Markdown cache header.

    Only ``reference_id`` and ``content_type`` are required. Known fields are
    type-checked without coercion; unknown fields are accepted and preserved.
    Strings such as content types are open vocabularies. Extraction stamps are
    optional integers, not a file-format version or a freshness requirement.
    ``year`` also accepts an integer for older, unquoted YAML years.

    Examples:
        >>> header = CacheFrontmatter.model_validate({
        ...     "reference_id": "PMID:1", "content_type": "abstract_only",
        ...     "database": "Orphanet",
        ... })
        >>> header.model_dump()["database"]
        'Orphanet'
        >>> CacheFrontmatter.model_json_schema()["additionalProperties"]
        True
    """

    model_config = ConfigDict(extra="allow", strict=True)

    reference_id: str = Field(min_length=1, pattern=r"\S")
    extractor_version: int | None = None
    html_full_text_version: int | None = None
    xml_extraction_version: int | None = None
    url_source_version: int | None = None
    absent_content_version: int | None = None
    title: str | None = None
    authors: list[str] | None = None
    journal: str | None = None
    year: str | int | None = None
    doi: str | None = None
    keywords: list[str] | None = None
    publication_types: list[str] | None = None
    content_type: str = Field(min_length=1, pattern=r"\S")
    is_preprint: bool | None = None
    peer_review_status: str | None = None
    full_text_attempted: bool | None = None
    full_text_declined: str | None = None
    full_text_provider: str | None = None
    full_text_url: str | None = None
    oa_status: str | None = None
    license: str | None = None
    local_pdf_path: str | None = None
    full_text_access_type: str | None = None
    full_text_source_item_id: str | None = None
    extra_fields_captured: list[str] | None = None
    supplementary_files: list[CacheSupplementaryFile] | None = None


@dataclass(frozen=True)
class CacheFinding:
    """A format error with a stable code and optional dotted field location."""

    code: str
    message: str
    field: str | None = None


@dataclass
class CacheValidationResult:
    """One file's parsed metadata and findings; valid files have no findings."""

    path: Path
    frontmatter: CacheFrontmatter | None = None
    findings: list[CacheFinding] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Whether the header and filename satisfy the cache contract."""
        return not self.findings


def cache_filename(reference_id: str) -> str:
    """Return the writer's filename for an already normalized reference ID.

    This does not resolve prefix aliases or existing DOI case variants.

    >>> cache_filename("url:https://example.org/a?b=c")
    'url_https___example.org_a_b_c.md'
    """
    return re.sub(r"[:/?=]", "_", reference_id) + ".md"


def validate_cache_file(path: str | Path) -> CacheValidationResult:
    """Check a UTF-8 Markdown cache file without fetching or changing anything.

    Report read errors, missing delimiters, invalid/duplicate-key YAML, known
    field type errors, and filename/ID mismatches as structured findings. A DOI
    filename may differ in case. The body is unrestricted Markdown: this cannot
    detect a well-formed hand edit or verify the truth of the cached source text.
    Legacy ``.txt`` caches are outside this contract.
    """
    path = Path(path)
    result = CacheValidationResult(path=path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        result.findings.append(CacheFinding("read_error", str(exc)))
        return result

    parts = re.split(r"^---[ \t]*$", text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) != 3 or parts[0]:
        result.findings.append(
            CacheFinding(
                "invalid_frontmatter",
                "Expected YAML between opening and closing --- lines at the start of the file.",
            )
        )
        return result
    try:
        metadata = YAML(typ="safe").load(parts[1])
    except YAMLError as exc:
        result.findings.append(CacheFinding("invalid_yaml", str(exc)))
        return result
    if not isinstance(metadata, dict):
        result.findings.append(
            CacheFinding("invalid_frontmatter", "Frontmatter must be a YAML mapping.")
        )
        return result
    try:
        result.frontmatter = CacheFrontmatter.model_validate(metadata)
    except ValidationError as exc:
        for error in exc.errors():
            result.findings.append(
                CacheFinding(
                    "invalid_field",
                    error["msg"],
                    ".".join(str(part) for part in error["loc"]),
                )
            )
        return result

    reference_id = result.frontmatter.reference_id
    expected = cache_filename(reference_id)
    matches = path.name == expected
    if reference_id.upper().startswith("DOI:"):
        matches = path.name.casefold() == expected.casefold()
    if not matches:
        result.findings.append(
            CacheFinding(
                "filename_mismatch",
                f"Expected filename {expected!r} for {reference_id!r}.",
                "reference_id",
            )
        )
    return result


def scan_cache_dir(
    directory: str | Path, *, recursive: bool = False
) -> list[CacheValidationResult]:
    """Validate every ``*.md`` file in deterministic path order.

    By default only immediate children are scanned. Other file types (including
    legacy ``.txt`` entries) are ignored. File errors do not stop the scan; an
    absent or unreadable directory raises ``OSError`` rather than passing an
    empty gate. An existing empty directory returns an empty list.
    """
    directory = Path(directory)
    # Unlike glob, iterdir reports missing and non-directory paths.
    entries = sorted(directory.iterdir())
    results = []
    for path in entries:
        if path.is_file() and path.suffix == ".md":
            results.append(validate_cache_file(path))
        elif recursive and path.is_dir() and not path.is_symlink():
            results.extend(scan_cache_dir(path, recursive=True))
    return results
