# Private Library Full-Text Integration — Implementation Plan

**Date:** 2026-08-05
**Design:** [Private Library Full-Text Integration](../specs/2026-08-05-private-library-full-text-design.md)

All implementation tasks follow test-driven development: add a failing test,
implement the smallest production change, then run the focused test and the full
`just test` suite. Network tests use realistic recorded/constructed API responses;
live tests remain opt-in.

## Phase 1: Zotero local API minimum viable workflow

### 1. Generalize full-text locations

Add tests for materializing a local PDF path, rejecting a path over the size cap,
rejecting a non-PDF file with a `.pdf` suffix, and passing ephemeral request
headers without persisting them.

Then:

- add `local_path`, `headers`, `access_type`, and `source_item_id` to
  `FullTextLocation`;
- teach `ReferenceFetcher._materialize()` to read a local file under the same size
  and format-sniffing rules as HTTP content;
- teach `ContentAcquirer` to accept per-location headers;
- add private provenance fields to `ReferenceContent` and cache round-tripping;
- ensure secrets and localhost URLs are not written to frontmatter.

### 2. Add a Zotero API client and exact identifier index

Add contract tests using representative Zotero v3 JSON for:

- local API availability detection;
- paginated top-level item loading;
- DOI normalization;
- PMID/PMCID extraction from structured fields and `extra`;
- incremental index refresh metadata;
- duplicate and ambiguous identifiers;
- child attachment selection;
- indexed-full-text success and PDF fallback.

Then implement a small read-only client rather than coupling HTTP and matching
logic directly inside the provider. The default base URL is
`http://localhost:23119/api`; web mode remains disabled in this phase.

### 3. Add `ZoteroFullTextProvider`

Add provider tests showing:

- no identifier returns `None`;
- an exact DOI/PMID hit returns Zotero indexed text when usable;
- short or absent indexed text returns the PDF file location;
- ambiguity returns no location and a diagnostic;
- connection errors remain retryable in the provider chain;
- provenance is `provider=zotero` and `access_type=user_library` with no OA claim.

Register `zotero` for the explicit `cache enrich` workflow. Ordinary validation
must reject its `user_library` locations even if it is accidentally included in
the configured provider chain.

### 4. Add `cache enrich`

Add CLI tests first for dry-run, apply, misses, ambiguity, provider-unavailable,
and stable tabular output. Implement:

```text
cache enrich --provider zotero --cache-dir PATH [--dry-run]
```

The command enumerates Markdown cache files, loads them through `ReferenceFetcher`,
and runs only the selected private provider even if `full_text_attempted` is
already true. Apply mode reuses the normal materialization path but writes an
owner-only private research cache outside the project by default.

### 5. Positive local smoke test

Run the dry-run command against a temporary cache entry whose DOI is known to
exist in the local Zotero library while Zotero is running. Verify:

- exact DOI match;
- at least 500 extracted characters;
- cache provenance and checksum;
- no credential or private URL leakage;
- the source Zotero library remains unchanged.

The checked-in test suite must not depend on the developer's personal library.

## Phase 2: Zotero Web API

### 6. Add authenticated read-only web mode

Test and implement user/group library configuration, pagination, `since`-based
index refresh, backoff/rate-limit headers, attachment download authentication,
and Zotero storage/WebDAV absence behavior.

Credentials come from `ZOTERO_API_KEY` or a credential callback. Add explicit
configuration for user/group library ID; never accept API keys in URLs.

### 7. Operational documentation

Document how to enable the local API, create a read-only Zotero key, scan before
applying, protect private caches, and keep private content out of validation.

## Phase 3: Paperpile local sync

### 8. Build a generic local library index

Extract identifier normalization and match reporting from the Zotero client into
a source-neutral index. Add BibTeX ingestion with tests for DOI, PMID, title,
year, author, duplicate keys, and malformed entries. Add a cacheable PDF probe
that reads metadata/first-page text only once per file and stores its checksum.

### 9. Add `PaperpileFullTextProvider` for local files

Test and implement configuration for:

- a local Paperpile/Google Drive PDF root;
- a Paperpile automatic BibTeX export file or HTTPS download link;
- an optional manual Paperpile JSON export.

Only exact DOI/PMID matches apply automatically. Title/year/author candidates are
reported by `cache enrich --dry-run` and require explicit user confirmation in a
future task.

### 10. Measure matching quality

Run dry-run evaluation on a representative private cache and record precision,
coverage, ambiguity, and unmatched reasons separately. Do not weaken matching
thresholds to improve coverage. Use findings to decide whether guarded metadata
matching should ever be enabled for apply mode.

## Phase 4: Paperpile via Google Drive

### 11. Add a read-only Drive adapter

Test with Google Drive API fixtures, then implement OAuth read-only listing and
download, incremental change tracking, native Google shortcut handling, and
streamed size limits. Reuse the Paperpile BibTeX identity index from Phase 3.

This phase must not mutate Drive or Paperpile. Tokens use the system credential
store and are excluded from logs and config serialization.

## Phase 5: Privacy hardening and signed attestations

### 12. Separate private content from shareable cache metadata

Completed in the first implementation: private content uses an owner-only
research cache outside the project by default. Validation reads only the public
cache, and its ordinary provider chain rejects explicitly non-open locations.

### 13. Specify and implement offline signed excerpt attestations

Define a canonical, versioned `excerpts.yaml` schema and bind each record to its
reference ID, claim hash, normalized excerpt hash, private source checksum,
location, result, generator version, timestamp, and key ID. A trusted offline
job reads the private cache and signs with Ed25519. Only the verification key is
checked in; agents and CI cannot write trusted attestations. Add tests for valid,
tampered, wrong-reference, wrong-claim, unknown-key, expired-key, and unsigned
artifacts before enabling this optional validation mode.

## Phase 6: Browse a cache in Zotero

### 14. Export cache metadata for Zotero import

Implemented `cache export --format csl-json` with deterministic DOI/PMID
deduplication and missing-full-text filtering. It exports an explicit
bibliographic metadata allowlist and always excludes cached text, excerpts,
provenance, PDFs, private-cache data, and local paths. The command refuses to
overwrite an output file without `--force`.

### 15. Consider an opt-in Zotero collection sync

Only after export is stable, design an idempotent write integration that creates
or updates a dedicated Zotero collection through the documented write API. It
must require explicit write authorization and a dry-run diff; it must never
alter unrelated Zotero items or attach private files implicitly.

## Definition of done for the minimal first task

- `cache enrich --provider zotero --dry-run` inventories an existing reference
  cache without modifying it.
- Exact DOI/PMID matches identify PDF attachments in the supported Zotero local
  API.
- Apply mode extracts usable text into the private research cache without changing the
  public source cache.
- Normal validation ignores the private research cache and rejects private
  provider results.
- Misses and ambiguities are visible and safe.
- No private API, direct SQLite dependency, secret persistence, or library write.
- Focused tests, doctests, mypy, Ruff, and the full `just test` suite pass.
