# Reference cache format and validation

The library owns the contract for Markdown cache files. Use its public model and
checkers instead of maintaining a downstream copy of the frontmatter fields:

```python
from linkml_reference_validator import (
    CacheFrontmatter,
    scan_cache_dir,
    validate_cache_file,
)

result = validate_cache_file("references_cache/PMID_12345.md")
for finding in result.findings:
    print(result.path, finding.code, finding.field, finding.message)

results = scan_cache_dir("references_cache")
invalid = [result for result in results if not result.is_valid]
if invalid:
    raise SystemExit(f"{len(invalid)} invalid cache files")
```

These functions read files without fetching references, refreshing extraction
stamps, or rewriting the cache. They return `CacheValidationResult` objects with
`path`, `frontmatter`, `findings`, and an `is_valid` property. `frontmatter` is a
`CacheFrontmatter` instance when the header passes validation, including when the
filename fails its separate check; otherwise it is `None`.

`scan_cache_dir(directory, recursive=False)` returns a list in path order. It
checks immediate `*.md` files by default; pass `recursive=True` to include nested
directories. It skips symlinked directories during recursion but reads symlinked
Markdown files. Non-Markdown files, including legacy `.txt` caches and downloaded
XML/PDF files, are outside this contract and are ignored. An existing empty directory returns `[]`. Missing,
unreadable, or non-directory scan roots raise `OSError` (including its subclasses)
so a mistaken path cannot silently pass a gate. Individual file errors are
reported as findings and do not stop the scan.

## Frontmatter contract

Files contain UTF-8 text without a byte-order mark (BOM), with a YAML mapping
between opening and closing `---` lines, beginning on the first line. The remaining
text is an unrestricted Markdown body. Duplicate YAML keys are invalid.

Only `reference_id` and `content_type` are required; both must be nonblank strings.
All other known fields are optional and may be null:

- Bibliography: `title`, `authors`, `journal`, `year`, `doi`, `keywords`, and
  `publication_types`.
- Extraction stamps: `extractor_version`, `html_full_text_version`,
  `xml_extraction_version`, `url_source_version`, and `absent_content_version`.
- Publication status: `is_preprint` and `peer_review_status`.
- Full-text metadata: `full_text_attempted`, `full_text_declined`,
  `full_text_provider`, `full_text_url`, `oa_status`, `license`, `local_pdf_path`,
  `full_text_access_type`, and `full_text_source_item_id`.
- Captured fields and attachments: `extra_fields_captured` and
  `supplementary_files`.

Known fields are checked without coercion. Extraction stamps and supplementary
file sizes are integers (booleans do not count); `is_preprint` and
`full_text_attempted` are booleans. Authors, keywords, publication types, and
captured field names are lists of strings. `year` accepts a string or an integer
for compatibility with older unquoted YAML years. Other scalar metadata is text.
Each supplementary file requires a nonempty string `filename`; its optional fields
are `download_url`, `content_type`, `size_bytes`, `checksum`, `description`, and
`local_path`. Older cache files may contain unquoted numeric values in fields
such as `checksum` that require strings. These are reported as `invalid_field`;
quote the intended text to repair them. The lenient fetcher also recovers numeric
and boolean scalars in string-valued metadata fields (including attachment
metadata) by converting their parsed values to strings. The field types come
from the public model; reference IDs, version stamps, booleans, lists, and
unknown extension fields are not coerced.
A cache rewrite then quotes these strings and retains consumer extensions.
This compatibility recovery applies only to disk reads, not source plugin output
or the public validator. It cannot reconstruct leading zeros or original
scientific notation already lost during YAML parsing; check the source when the
exact spelling matters.

**Unknown keys are allowed and preserved**, both in the header and in
supplementary-file metadata. No extension namespace is required: a consumer's
`database: Orphanet` is valid. String vocabularies such as `content_type`,
`peer_review_status`, and `full_text_access_type` are open, so future values do not
break older consumers. Extraction stamps may be absent, old, or newer than this
library; format validity does not imply freshness.

When rewriting an existing cache with a valid header for the same reference,
the fetcher carries over unknown fields, including explicit null values. Unknown
fields are retained as-is, not recalculated or certified current on refresh;
this also applies to fields written by a newer version of the library. Known
fields always come from the new reference. Attachment extensions follow filenames
that are unique in both the old and new attachment lists; removed or ambiguous
attachments do not transfer their extensions. Preservation reads only the file
being overwritten, so metadata is not copied between public and private caches
or between different references whose sanitized filenames collide. A damaged
header that remains invalid after legacy scalar recovery cannot supply validated
extensions: the fetcher logs a warning and permits
a fresh fetch to repair the file.

The writer omits empty optional attachment strings, retaining the historical
serialization policy. Invalid known metadata supplied by a source or carried
through a lenient read raises `pydantic.ValidationError` before a cache write;
`fetch()` propagates that error. An existing cache file is left intact. This
makes a source's type-contract error visible instead of silently coercing values
or reporting a successful cache write that never happened.

`CacheFrontmatter` is a public Pydantic model released with the library. The writer
serializes this same model. To inspect the complete, machine-readable contract:

```python
schema = CacheFrontmatter.model_json_schema()
header = CacheFrontmatter.model_validate({
    "reference_id": "PMID:12345",
    "content_type": "abstract_only",
    "database": "Orphanet",
})
assert header.model_dump()["database"] == "Orphanet"
```

The checker derives the filename from the stored `reference_id` by replacing
`:`, `/`, `?`, and `=` with `_` and appending `.md`. DOI filenames are compared
case-insensitively, matching the fetcher's existing behavior. Other filenames must
match exactly. This uses the ID already stored in the file, without applying
configured prefix aliases or requiring a currently registered reference source.

## Findings and local policy

Each `CacheFinding` has a stable `code`, a human-readable `message`, and a `field`
when applicable. Field locations use dotted paths, for example `authors.0` or
`supplementary_files.0.size_bytes`.

| Code | Meaning |
| --- | --- |
| `read_error` | The file cannot be read or is not valid UTF-8. |
| `invalid_frontmatter` | Delimiters are missing/misplaced or the YAML is not a mapping. |
| `invalid_yaml` | YAML parsing failed, including duplicate keys. |
| `invalid_field` | A required field is absent or a known field has an invalid type/value. |
| `filename_mismatch` | The filename does not match the stored reference ID. |

Apply local requirements after `result.is_valid`, using `result.frontmatter`.
Requiring authors or a journal for particular reference sources, for example,
is a consumer policy rather than a format rule. The ordinary fetcher's reader
remains lenient for recovering old cache data; the checker reports malformed
known fields instead of silently recovering them. In particular, the reader
accepts text before the opening frontmatter delimiter; the checker requires the
opening delimiter on the first line.

Validation cannot prove that a file was never hand-edited, that its text agrees
with the publication, or that its bibliography is complete. A well-formed edit
still passes; use version-control review or an external integrity record to
track changes when needed.
