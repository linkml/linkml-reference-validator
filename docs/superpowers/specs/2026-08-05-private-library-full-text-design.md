# Private Library Full-Text Integration — Design

**Date:** 2026-08-05
**Status:** Partially implemented; validation isolation revised
**Approach:** Keep user-authorized manuscript libraries in a separate research
workflow, outside the reproducible public validation path.

## Problem

The validator can obtain open full text from PMC, Europe PMC, Unpaywall, and
OpenAlex, but many references are available only through a user's lawful
subscription or personal manuscript library. The user may already have the PDF
in Zotero or Paperpile even when every open-access provider misses.

The first useful workflow is:

> Given an existing reference cache, report which abstract-only references have
> an exact-identity PDF match in the user's Zotero library, then optionally enrich
> those cache entries from the matched PDFs.

Earlier mentions of "Zenodo library" meant **Zotero**. This design concerns
Zotero and Paperpile personal libraries; existing Zenodo repository support is
unrelated.

## Goals

- Search user-authorized libraries in an explicit cache-enrichment workflow.
- Match references conservatively, preferring exact DOI, PMID, or PMCID matches.
- Reuse the existing PDF acquisition, extraction, minimum-text, and cache logic.
- Record that content came from a private/user library without claiming it is
  open access.
- Keep credentials out of configuration files and logs.
- Provide a dry-run inventory command before changing cached references.
- Support Zotero first, then Paperpile without depending on undocumented APIs.
- Keep validation deterministic: it reads only the public project cache and
  accepts evidence only from public providers.

## Non-goals

- Bypassing publisher authentication, DRM, or paywalls.
- Redistributing private PDFs or derived full text.
- Writing to Zotero, Paperpile, Google Drive, or Zenodo.
- Depending on Zotero's private SQLite schema for the production integration.
- Depending on reverse-engineered Paperpile web endpoints.
- Using fuzzy-only matches automatically.

## Existing architecture fit

The current pipeline already separates metadata resolution from full-text
location:

```text
reference ID
  -> metadata source
  -> ReferenceIdentifiers
  -> ordered FullTextProvider chain
  -> acquire PDF/HTML/XML
  -> extract text
  -> save content and provenance in the reference cache
```

Private libraries run beside, not inside, the validation pipeline:

```text
Zotero/Paperpile -> cache enrich -> private research cache -> agent context only

public reference cache -> public provider chain -> validation evidence
```

The existing `FullTextProvider.locate()` interface is nearly sufficient. Two
small generalizations are needed:

1. `ReferenceIdentifiers` needs matching metadata (`title`, `year`, and
   optionally first author) for diagnostic candidates and future guarded
   fallback matching.
2. `FullTextLocation` needs either a local path or request headers. Zotero's
   local API can return text or a localhost file URL, but Zotero Web API and
   Google Drive downloads require authenticated headers. A local synced
   Paperpile PDF should not be routed through `requests`.

The preferred model is:

```python
@dataclass
class FullTextLocation:
    url: Optional[str] = None
    local_path: Optional[Path] = None
    text: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    format_hint: Optional[str] = None
    provider: str = ""
    access_type: Optional[str] = None  # open | user_library | institutional
    source_item_id: Optional[str] = None
```

At most one of `url`, `local_path`, and `text` should be populated. Header
values must never be serialized into the cache.

## Identity matching policy

Wrong-paper matches are more harmful than misses. Matching therefore has
explicit confidence levels:

| Match | Automatic use | Notes |
|---|---:|---|
| Normalized DOI equality | Yes | Strip DOI URL/prefix, whitespace, and case |
| PMID or PMCID equality | Yes | Use structured library fields or a parsed explicit identifier |
| DOI equality found in PDF metadata/text | Yes, after identifier validation | Useful for an unindexed local folder |
| Title + year + first author | Report only initially | May become opt-in after measuring false positives |
| Title similarity alone | No | Diagnostic candidate only |

Ambiguous exact matches are not failures: choose a usable PDF only if all exact
matches identify the same parent work; otherwise report `ambiguous` and make no
cache change.

## Zotero design

### Supported access modes

1. **Local API (first implementation).** Zotero exposes a read-only API at
   `http://localhost:23119/api/`. It uses the local database and requires no
   authentication for reads. The Zotero desktop application must be running and
   local API access enabled.
2. **Web API (second implementation).** Private libraries require a read-only API
   key. The key is read from an environment variable or secret store. File
   attachments can be downloaded from `/items/<attachmentKey>/file`.

The supported APIs are preferable to reading `zotero.sqlite`: direct database
access couples the validator to private schema details, can see inconsistent
state, and complicates linked-file path resolution.

### Lookup algorithm

Zotero's API quick search does not provide reliable field-specific DOI search.
The provider should build a lightweight local index of top-level item JSON:

```text
normalized DOI -> Zotero parent item key(s)
PMID            -> Zotero parent item key(s)
PMCID           -> Zotero parent item key(s)
```

For the local API the index can be loaded once per process. For the Web API it
must be paginated and persisted using Zotero library versions and `since` so
later refreshes are incremental.

For a matched parent item:

1. Request `/items/<parentKey>/children`.
2. Select PDF attachments deterministically: primary attachment first, then the
   newest non-supplement attachment.
3. Prefer `/items/<attachmentKey>/fulltext`, because Zotero may already have
   indexed the PDF.
4. If indexed text is absent or too short, download `/items/<attachmentKey>/file`
   and use the existing PDF extractor.
5. Return provider `zotero`, access type `user_library`, and the attachment key.

### Observed local feasibility

On the development machine, `/Users/cjm/Zotero/zotero.sqlite` exists and contains
283 PDF attachments. The supported local API was not reachable during this
design pass because Zotero was not running. The sole reference in this checkout's
`references_cache` (`PMID:23456789`, DOI `10.1002/cncr.27976`) has no exact DOI
match in that local library. This confirms there is enough local test data for a
provider, but a different cached reference is needed for a real positive smoke
test.

## Paperpile design

No documented public Paperpile library API was found. The supported integration
should compose two official export/sync mechanisms:

- A continuously updated BibTeX export, available through a download link,
  Google Drive, or GitHub, supplies DOI and citation metadata.
- Google Drive sync supplies PDFs and supplementary files in the user's
  Paperpile folder.

Paperpile also offers a manual JSON export containing attachment metadata, but
the export excludes the PDF bytes and is not documented as a continuously
synced API. It is useful as an optional richer index, not as the primary
automation contract.

### Phased access modes

1. **Local synced folder.** Point the validator at a read-only local Paperpile
   Google Drive folder plus a synced BibTeX file. This needs no Google OAuth and
   is easy to test.
2. **Google Drive API.** Use OAuth read-only access to find and download files for
   environments without Drive for desktop. Match them against the synced BibTeX
   index. Tokens stay in the platform keychain/secret store, never YAML.
3. **Paperpile API only if officially documented.** Do not build on observed
   browser traffic or private endpoints.

### Paperpile matching

Build an index from BibTeX DOI/PMID/title/year fields. Associate PDF files using,
in order:

1. an attachment path present in an explicitly supplied Paperpile JSON export;
2. DOI found in the PDF metadata or first pages;
3. a deterministic Paperpile filename/title match, confirmed by year and author.

Only exact identifiers should auto-enrich in the first release. Metadata-based
matches appear in the dry-run report for user review.

## Browsing a cache as a library

Cache-to-Zotero export is a useful companion feature. The safest first version
should generate a standard CSL JSON or RIS file for manual import into a new
Zotero collection. Each cache entry can
export title, authors, year, DOI/PMID, content type, provider, and cache path.
Private PDFs and extracted full text should be excluded by default; the Zotero
provider already links an enriched entry back to its source attachment key.

A later `cache sync-zotero` command could create/update a dedicated collection
through Zotero's write API, but that mutates the user's library and needs explicit
authorization, stable cache-to-item identifiers, idempotency, and conflict tests.

## Cache and rights policy

Private source content must not be labeled with an OA status. Add these persisted
provenance fields:

| Field | Example | Purpose |
|---|---|---|
| `full_text_provider` | `zotero` | Existing provider provenance |
| `full_text_access_type` | `user_library` | Separates lawful private access from OA |
| `full_text_source_item_id` | Zotero attachment key | Auditable source identity |
| `full_text_source_checksum` | SHA-256 | Detects replacement without exposing credentials |

Because the Markdown cache contains extracted text, private content is stored in
a separate research cache at `~/.cache/linkml-reference-validator/private` by
default, with owner-only directory and file permissions. Users may explicitly
point it at a private repository. Validation never reads this cache. A private
provider result is also rejected by the ordinary provider chain, which then
continues to public providers.

## Future signed excerpt attestations

Private-backed validation, if enabled later, must be reproducible without giving
the manuscript or a signing credential to an agent or CI. A trusted offline job
would be the only writer of an artifact such as
`CACHEDIR/PMID_12345678/excerpts.yaml`. It would:

1. read the private research cache and the claims to validate;
2. select only the minimal supporting or contradicting excerpt;
3. record the reference ID, claim hash, normalized excerpt hash, source-file
   checksum, location, outcome, tool version, timestamp, and signing-key ID;
4. sign a canonical serialization with an offline Ed25519 private key; and
5. copy the attestation—not the PDF or full extracted text—into the public cache.

The repository contains only the public verification key. The validator accepts
an attestation only when its signature is valid and all bound identifiers and
hashes match the current claim. Editing or moving fields invalidates the
signature. Agents are forbidden from writing these artifacts directly and, more
importantly, cannot create a valid one because they never receive the private
key. Unsigned or invalid artifacts are ignored by default and become hard errors
when a future private-attestation mode is explicitly requested.

The exact excerpt length and redistribution policy need review before this mode
is implemented. Until then, signed attestations are design-only and all
validation evidence comes from the public cache.

## CLI shape

The first command is an inventory-first operation:

```bash
linkml-reference-validator cache enrich \
  --provider zotero \
  --cache-dir references_cache \
  --dry-run
```

Output is one row per cached reference:

```text
REFERENCE          RESULT      MATCH       ATTACHMENT
PMID:12345678      found       doi         zotero:ABCD1234
DOI:10.example/x   not_found   -           -
DOI:10.example/y   ambiguous   title/year  -
```

Without `--dry-run`, exact matches are written to the separate private research cache
through the same materialization path used by other providers. The public source
cache is never modified. The command exits nonzero only for
configuration/provider errors, not ordinary library misses.

## Security and operational rules

- Read-only by default; no library or Drive writes.
- Tokens only through environment variables or a credential provider.
- Redact authorization headers and signed URLs from logs and cache frontmatter.
- Never serialize a localhost/session URL as a durable source URL.
- Apply existing download size limits to local files as well as HTTP downloads.
- Verify `%PDF-` magic bytes and compute SHA-256 before extraction.
- Preserve provider errors as retryable; a normal library miss is definitive for
  that index version.
- Do not fall through to a lower-confidence private match automatically.

## Sources

- [Zotero Web API v3 and local API](https://www.zotero.org/support/dev/web_api/v3/basics)
- [Zotero attachment file download](https://www.zotero.org/support/dev/web_api/v3/file_upload)
- [Zotero full-text content API](https://www.zotero.org/support/dev/web_api/v3/fulltext_content)
- [Paperpile automatic BibTeX sync](https://paperpile.com/h/sync-bibtex-files/)
- [Paperpile library data export](https://paperpile.com/h/export-library-data/)
- [Paperpile Google Drive sync](https://paperpile.com/h/sync-google-drive/)
- [Zenodo REST API](https://developers.zenodo.org/)
