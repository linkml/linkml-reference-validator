"""Public, forward-compatible contract for Markdown reference cache files.

Validation is read-only and independent of extractor freshness or source policy.
Unknown fields are preserved, so consumers can add metadata without a namespace.
"""

from dataclasses import dataclass, field
import hashlib
from pathlib import Path
import re

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


# Match delimiter lines, never a --- substring inside a metadata value.
_FRONTMATTER_DELIMITER = re.compile(r"^---[ \t]*$", re.MULTILINE)


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
    svg_extraction_version: int | None = None
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


def cache_key(reference_id: str) -> str:
    """Return the identity a normalized reference ID is cached under.

    A ``url:`` reference drops its fragment: a client never sends the part
    after ``#`` to the server, so ``report.pdf#page=54`` and
    ``report.pdf#page=55`` fetch the same bytes and share one entry (#114).
    The query string is kept, since it can change what the server returns.
    Every other reference ID is its own key.

    >>> cache_key("url:https://example.org/report.pdf#page=54")
    'url:https://example.org/report.pdf'
    >>> cache_key("url:https://example.org/report.pdf?v=2#page=54")
    'url:https://example.org/report.pdf?v=2'
    >>> cache_key("url:https://example.org/report.pdf")
    'url:https://example.org/report.pdf'
    >>> cache_key("file:./notes.md#intro")
    'file:./notes.md#intro'
    """
    if reference_id.startswith("url:"):
        return reference_id.partition("#")[0]
    return reference_id


def cache_filename(reference_id: str) -> str:
    """Return the writer's filename for an already normalized reference ID.

    This does not resolve prefix aliases or existing DOI case variants.

    >>> cache_filename("url:https://example.org/a?b=c")
    'url_https___example.org_a_b_c.md'
    >>> cache_filename("url:https://example.org/a.pdf#page=3")
    'url_https___example.org_a.pdf.md'
    """
    return _sanitized_filename(cache_key(reference_id))


def legacy_cache_filename(reference_id: str) -> str:
    """Return the filename used before ``url:`` fragments were dropped (#114).

    Read-only: entries are never written here any more, but caches committed
    before the change still hold them.

    >>> legacy_cache_filename("url:https://example.org/a.pdf#page=3")
    'url_https___example.org_a.pdf#page_3.md'
    """
    return _sanitized_filename(reference_id)


#: The longest cache filename written, in UTF-8 bytes. Common filesystems allow
#: 255; this leaves room for a ``.txt`` legacy probe and other tools' suffixes.
MAX_CACHE_FILENAME_BYTES = 200

#: Hex digits of the reference ID's SHA-256 kept in a capped filename.
_FILENAME_HASH_CHARS = 16


def _sanitized_filename(reference_id: str) -> str:
    """Sanitize a reference ID into a filename, keeping everything else verbatim.

    A name over ``MAX_CACHE_FILENAME_BYTES`` is cut on a character boundary and
    ends in ``_`` plus a hash of the full ID, so it fits the filesystem and two
    long IDs that share a prefix still get different files (#132). A DOI is
    hashed case-insensitively, so case variants of one DOI still differ only in
    case, as the fetcher's case-variant lookup and the checker expect.

    >>> _sanitized_filename("PMID:1")
    'PMID_1.md'
    >>> name = _sanitized_filename("url:https://example.org/?q=" + "x" * 300)
    >>> len(name.encode("utf-8")) <= MAX_CACHE_FILENAME_BYTES, name[-20:]
    (True, '_8d32b36eb989401f.md')
    """
    name = re.sub(r"[:/?=]", "_", reference_id)
    if len(name.encode("utf-8")) + len(".md") <= MAX_CACHE_FILENAME_BYTES:
        return name + ".md"
    digest_source = (
        reference_id.casefold() if reference_id.upper().startswith("DOI:") else reference_id
    )
    digest = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()[:_FILENAME_HASH_CHARS]
    room = MAX_CACHE_FILENAME_BYTES - len(".md") - len("_") - len(digest)
    prefix = name.encode("utf-8")[:room].decode("utf-8", errors="ignore")
    return f"{prefix}_{digest}.md"


def _same_reference_id(first: str, second: str) -> bool:
    """Compare stored IDs exactly, except for case-insensitive DOI identity."""
    if first.upper().startswith("DOI:"):
        return first.casefold() == second.casefold()
    return first == second


def _recover_legacy_scalars(metadata: dict) -> dict:
    """Recover scalar text that older writers emitted without YAML quoting.

    Restricted to disk reads, never the public checker or source plugin values.
    Collections remain invalid, and extension values are left untouched.
    """

    def recover(fields: dict, model: type[BaseModel]) -> dict:
        """Copy a mapping, recovering scalar text according to the public model."""
        fields = fields.copy()
        for name, spec in model.model_fields.items():
            # A bare number cannot be a normalized reference ID. Booleans and
            # versions are typed fields, not legacy text, so remain untouched.
            if name == "reference_id" or spec.annotation not in (str, str | None):
                continue
            value = fields.get(name)
            if isinstance(value, (int, float)):
                fields[name] = str(value)
        return fields

    metadata = recover(metadata, CacheFrontmatter)
    attachments = metadata.get("supplementary_files")
    if isinstance(attachments, list):
        metadata["supplementary_files"] = [
            recover(item, CacheSupplementaryFile) if isinstance(item, dict) else item
            for item in attachments
        ]
    return metadata


def validate_cache_file(path: str | Path) -> CacheValidationResult:
    """Check a UTF-8 Markdown cache file without fetching or changing anything.

    Report read errors, missing delimiters, invalid/duplicate-key YAML, known
    field type errors, and filename/ID mismatches as structured findings. A DOI
    filename may differ in case. The body is unrestricted Markdown: this cannot
    detect a well-formed hand edit or verify the truth of the cached source text.
    Legacy ``.txt`` caches are outside this contract.
    """
    return _validate_cache_file(path)


def _validate_cache_file(
    path: str | Path, *, recover_legacy_scalars: bool = False
) -> CacheValidationResult:
    """Read a header, optionally applying the fetcher's legacy scalar recovery."""
    path = Path(path)
    result = CacheValidationResult(path=path)
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        result.findings.append(CacheFinding("read_error", str(exc)))
        return result

    parts = _FRONTMATTER_DELIMITER.split(text, maxsplit=2)
    if len(parts) != 3 or parts[0]:
        result.findings.append(
            CacheFinding(
                "invalid_frontmatter",
                "Expected YAML between opening and closing --- lines at the start of the file.",
            )
        )
        return result
    # Keep parser state local so a malformed file cannot affect a later scan entry.
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
    if recover_legacy_scalars:
        metadata = _recover_legacy_scalars(metadata)
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
    # A fragment-keyed name from before #114 is still read, so still valid.
    accepted = {expected, legacy_cache_filename(reference_id)}
    matches = path.name in accepted
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
