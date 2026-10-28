# Fetching Full Text and PDFs

This guide explains how the validator obtains the **full text** of a reference
(not just its abstract or metadata) by trying a chain of full-text providers,
optionally downloading and extracting text from PDFs.

## Overview

When a metadata source (Crossref, PubMed, DataCite, etc.) returns only an
abstract or title, the validator can fall through to a **full-text provider
chain**. Each provider attempts to *locate* an open-access copy of the
reference. The first provider that yields usable full text wins; the located
resource is downloaded and, if it is a PDF, the text is extracted and cached
alongside the reference.

This behaviour is **on by default**.

## The provider chain

The validator tries providers in order until one returns usable full text.
The default order is:

```
pmc → bookshelf → epmc_preprint → unpaywall → openalex
```

- **`pmc`** — PubMed Central open-access subset (XML/HTML full text for many
  biomedical articles).
- **`bookshelf`** — NCBI Bookshelf chapters, such as GeneReviews, read from a
  local copy of NCBI's archive (see [NCBI Bookshelf](#ncbi-bookshelf-genereviews)
  below). Does nothing until `bookshelf_archive_dir` is set.
- **`epmc_preprint`** — Europe PMC preprint body text via the `fulltextRepo`
  PDF route (see [Preprints](#preprints) below).
- **`unpaywall`** — Unpaywall open-access lookup by DOI (often a publisher or
  repository PDF).
- **`openalex`** — OpenAlex open-access location (PDF/HTML).

Two more built-in providers are available but not in the default chain; add
them to `full_text_providers` to use them:

- **`bioc`** — PMC Open Access articles as BioC passages, from NCBI's BioNLP
  BioC API, by PMID. The reference list and the competing-interest,
  author-contribution and funding statements are left out, so a snippet quoting
  a cited paper cannot validate against the paper citing it.
- **`epmc`** — Europe PMC's `fullTextXML` for open-access articles, by PMID.
  This is the same JATS that `pmc` reads, served by Europe PMC rather than
  NCBI, so after `pmc` it rarely finds anything new. It is useful as a second
  route when NCBI is down or rate-limiting, or in place of `pmc` to avoid
  depending on Entrez. Not to be confused with `epmc_preprint`, which handles
  preprints only.

Providers are skipped silently if they have nothing for a given reference, so
the chain degrades gracefully: a miss in `pmc` simply moves on to `unpaywall`,
and so on. If no provider yields full text, the reference keeps whatever
metadata-only content it already had.

## Configuration

Full-text fetching is controlled by the following configuration keys (set in
your config YAML or on the `ReferenceValidationConfig` object):

| Key | Default | Description |
|-----|---------|-------------|
| `fetch_full_text` | `true` | Attempt to obtain full text via the provider chain when a metadata source does not already return full text. |
| `full_text_providers` | `[pmc, bookshelf, epmc_preprint, unpaywall, openalex]` | Ordered list of provider names to try until one yields usable full text. `bioc` and `epmc` are also built in but must be added explicitly. |
| `bookshelf_archive_dir` | `null` | Directory of unpacked NCBI Bookshelf books, read by the `bookshelf` provider. |
| `private_cache_dir` | `~/.cache/linkml-reference-validator/private` | Separate research cache for closed/user-library full text; never read by validation. |
| `pdf_backend` | `pypdf` | Name of the PDF text-extraction backend. |
| `download_pdfs` | `true` | If true, persist downloaded PDFs to the files cache directory. |
| `full_text_providers_file` | `null` | Optional path to a YAML file defining custom full-text providers. |
| `zotero_base_url` | `http://localhost:23119/api/users/0` | Read-only Zotero local API library used by the opt-in `zotero` provider. |

Two existing keys are also reused by the full-text machinery:

| Key | Description |
|-----|-------------|
| `email` | Used for "polite pool" access to providers such as Unpaywall and OpenAlex (and for Crossref/Entrez). Set this for more reliable access. |
| `max_supplementary_file_size` | Upper bound (in bytes) on individual file downloads; a downloaded full-text PDF larger than this limit is not persisted. |

Example config YAML:

```yaml
email: you@example.org
fetch_full_text: true
full_text_providers:
  - pmc
  - bookshelf
  - epmc_preprint
  - unpaywall
  - openalex
pdf_backend: pypdf
download_pdfs: true
```

## NCBI Bookshelf (GeneReviews)

A PMID can point to a chapter on NCBI Bookshelf rather than a journal article.
Every [GeneReviews](https://www.ncbi.nlm.nih.gov/books/NBK1116/) entry is one
of these. Such a chapter has no PMC copy, so without help the reference keeps
only its PubMed summary, and a quote from the chapter body fails as
abstract-only.

The archive described below is for **caching** a chapter, not for validating
against it. Validate quotes against the cached document. Once a chapter has
been fetched, its full text is in the reference cache (`PMID_31536184.md`),
and every later validation reads that file. There's no archive and no network
call. So the large download is a one-time step on the machine that builds the
cache, not something every run or every collaborator needs. See
[Validate against the cache, not the archive](#validate-against-the-cache-not-the-archive).

Bookshelf's web pages can't be fetched by a script: NCBI answers with a
reCAPTCHA page. Instead, the `bookshelf` provider reads chapters from NCBI's
[litarch archive](https://ftp.ncbi.nlm.nih.gov/pub/litarch/), which you
download once per book:

```bash
linkml-reference-validator cache bookshelf-download NBK1116 --archive-dir bookshelf
```

GeneReviews (`NBK1116`) is a 640 MB download. Only the chapter XML is kept,
about 200 MB. Then point the config at the same directory:

```yaml
bookshelf_archive_dir: bookshelf
```

The PubMed record names the chapter, so no extra lookup is needed:
`PMID:31536184` is `gene/glutaric-a1`, read from
`bookshelf/gene_NBK1116/glutaric-a1.nxml`. The cached entry records
`full_text_provider: bookshelf`, and `full_text_url` holds the chapter's
Bookshelf page.

A chapter is used only when its own `<license>` is `open-access`. GeneReviews
allows copying for noncommercial research with credit and no modification. A
cache holds a verbatim copy, and its `full_text_url` links back to the
chapter, so the text goes into the public cache like PMC full text does.

To refresh a book, run the download again: it replaces the book's folder. Do
this to pick up new or revised chapters.

**References cached before the archive was set up** keep their abstract. The
chain recorded that it couldn't read the chapter (`full_text_declined`, or
`full_text_attempted` on a cache from an older version), and it doesn't retry
on its own. Re-fetch them:

```bash
linkml-reference-validator cache reference PMID:31536184 --force
```

### Validate against the cache, not the archive

The archive is only read when a chapter is **fetched**. That happens the first
time a reference is seen, and on an explicit `--force`. Validation reads the
cached document like any other cached reference. In practice:

1. On one machine, download the book, set `bookshelf_archive_dir`, and cache
   the chapters you cite (`cache reference PMID:...`, or a validation run).
2. Commit the reference cache: the `PMID_*.md` files, which hold the chapter
   text. Don't commit the archive.
3. Everywhere else, including CI and collaborators, validate as usual. No
   archive is needed, `bookshelf_archive_dir` can stay unset, and nothing is
   downloaded from NCBI.

What happens when the archive is missing:

- **A cached chapter is never lost to a refresh that can't reach it.** If a
  newer version of this tool marks the entry stale and re-fetches it, the
  refresh gets only the abstract. The cached chapter is then kept and still
  used, with a warning, and the entry stays stale until a run with the
  archive refreshes it. For a committed cache you'd rather not re-fetch at
  all, set `trust_cached_entries: true`.
- **`--force` is the exception.** It replaces the entry with whatever the
  fetch returns, so forcing a Bookshelf reference without the archive swaps
  the chapter for its abstract (it warns as it does). Only force these
  references where the archive is available.
- **A reference that was never cached** still needs the archive once.
  Without it, the reference is cached with its abstract only.
  `full_text_declined: bookshelf_archive_not_configured` records why.

## Private manuscripts in Zotero

The opt-in **`zotero`** provider can find non-open manuscripts that are already
in your personal Zotero library. It matches exact DOI, PMID, or PMCID identifiers;
it does not automatically accept fuzzy title matches.

Zotero must be running, and its local API must be enabled in Zotero's advanced
settings. Inventory the reference cache before changing it:

```bash
linkml-reference-validator cache enrich \
  --provider zotero \
  --cache-dir references_cache \
  --dry-run
```

The report distinguishes `found`, `not_found`, `already_full_text`, and `error`.
Dry-run is the default and never changes cache files. After reviewing exact
matches, apply usable text with:

```bash
linkml-reference-validator cache enrich \
  --provider zotero \
  --cache-dir references_cache \
  --apply
```

Apply mode does **not** modify `references_cache`. It writes the enriched entry
to a separate research cache at `~/.cache/linkml-reference-validator/private`
by default. Agents may inspect that cache for background context, but ordinary
validation never reads it and never cites it as evidence. Validation therefore
has the same inputs locally, in CI, and on another contributor's machine.

To keep the research cache in a private repository or another secured location:

```bash
linkml-reference-validator cache enrich \
  --provider zotero \
  --cache-dir references_cache \
  --private-cache-dir /path/to/private-reference-cache \
  --apply
```

The same location can be configured for all commands:

```yaml
cache_dir: references_cache
private_cache_dir: /path/to/private-reference-cache
```

Zotero-indexed text is preferred. If Zotero has not indexed an attachment, the
provider downloads it from Zotero's local PDF endpoint and sends it through the
normal PDF extractor. The source attachment key and `user_library` access type
are persisted, but the ephemeral localhost URL is not.

!!! warning "Keep research caches private"

    Private cache entries contain extracted manuscript text and may contain a
    copied PDF. Do not place this cache in a public repository or share it
    unless you have permission to redistribute that content.

Do not add `zotero` to `full_text_providers`. Even if it is configured there,
ordinary validation rejects its `user_library` result and continues to public
providers. Use `cache enrich` when you want to search Zotero.

Support for reproducible validation backed by private manuscripts is a future,
separate feature. The proposed design is a trusted offline job that emits a
minimal signed excerpt attestation into the public cache. The validator would
verify the signature using a checked-in public key; neither agents nor CI would
have the signing key or permission to generate those files directly.

## Export a cache to a Zotero collection

Export references that still need full text as metadata-only CSL JSON:

```bash
linkml-reference-validator cache export \
  --cache-dir references_cache \
  --format csl-json \
  --needs-full-text \
  --output project-zotero.json
```

The default `--needs-full-text` mode excludes cache entries that already contain
full text. It also excludes non-publication identifiers, deduplicates by
normalized DOI and then PMID, and exports only an explicit metadata allowlist:
title, authors, journal, year, DOI, PMID, and PubMed URL. Cached article text,
excerpts, provenance, PDFs, and local paths are never exported. Use `--all` only
when you deliberately want eligible records that already have full text.

The exporter refuses to replace an existing output file unless `--force` is
given. Review the reported counts, then in Zotero choose **File → Import → A
file**, select the JSON file, and place the imported items in a project-specific
collection. Zotero supports CSL JSON as a standard import format. After import,
select the collection and run **Find Full Text**, then rerun `cache enrich`.

See [Zotero's standardized-format import instructions](https://www.zotero.org/support/kb/importing_standardized_formats).
For the complete workflow with screenshots, see
[Export a Reference Cache to Zotero](export-cache-to-zotero.md).

## Preprints

Preprints are first-class references. They are increasingly cited for early
mechanistic findings, but they sit in two distinct universes that need
different handling:

- **NIH Preprint Pilot** — a subset of preprints carry real PMIDs, so they
  resolve through the normal `PMID:` path with no special handling.
- **Europe PMC `SRC:PPR`** — the much larger preprint firehose is DOI-only
  (no PMIDs). These resolve by DOI through Crossref, or directly by their
  Europe PMC preprint id using the `PPR:` prefix (e.g. `PPR:PPR123456`).

### Full-text retrieval

Preprint bodies are **not** served by the PMC `fullTextXML` endpoint — even the
~7% with a PMCID expose only abstract/title/supplementary in PMC, and direct
`biorxiv.org/...full.pdf` links sit behind a bot challenge. The route that
works for automated clients is the Europe PMC `fulltextRepo` PDF, used by the
`epmc_preprint` provider: it resolves a preprint by DOI (or `SRC:PPR` id),
finds the open `fulltextRepo` PDF URL, and downloads it. The PDF's `%PDF-`
magic bytes are validated before extraction, so a stale-filename error blob is
rejected rather than fed to the PDF parser, and the chain falls through
gracefully.

Coverage note: the `epmc_preprint` route covers the Europe-PMC-ingested
preprint subset. The newest openRxiv DOIs (prefix `10.64898`) are not yet in
Europe PMC, so very recent preprints may resolve to metadata only until they
are ingested.

### Preprint / peer-review status

When a reference is detected as a preprint — via the Crossref `posted-content`
type or a Europe PMC `SRC:PPR` record — the cached reference records it:

| Field | Description |
|-------|-------------|
| `is_preprint` | `true` for a preprint, `false` when the source authoritatively classifies it as not a preprint (e.g. a Crossref `journal-article`), and unset when the type is unknown. |
| `peer_review_status` | `preprint` for preprints; left unset otherwise. |

Downstream knowledge bases can use these fields to apply policies such as "a
preprint may not be the sole support for a claim". A non-preprint is not
positively asserted as `peer_reviewed`; `peer_review_status` stays unset.

## CLI flag

Every `validate` subcommand accepts a `--full-text/--no-full-text` flag that
toggles `fetch_full_text` for that run (default: on):

```bash
# Default: full-text chain is tried
linkml-reference-validator validate data data.yaml \
  --schema schema.yaml --target-class Statement

# Disable full-text fetching (metadata only)
linkml-reference-validator validate data data.yaml \
  --schema schema.yaml --target-class Statement --no-full-text
```

## Custom providers

You can declare your own JSON-API-backed provider in a YAML file and point
`full_text_providers_file` at it. Each entry under `full_text_providers` is
keyed by the provider name and must supply a `url_template`. The template may
reference `{doi}`, `{pmid}`, or `{pmcid}`. `location_field` is a JSONPath into
the response that holds the URL of the full-text resource; `format_hint` tells
the validator how to treat it; and `headers` are sent with the request, with
`${ENV_VAR}` placeholders interpolated from the environment.

```yaml
full_text_providers:
  myrepo:
    url_template: https://api.example.org/fulltext/{doi}
    location_field: $.links.pdf
    format_hint: pdf
    headers:
      Authorization: Bearer ${MYREPO_TOKEN}
```

To actually use a custom provider, add its name to the `full_text_providers`
chain (it is not enabled merely by being defined), for example:

```yaml
full_text_providers_file: providers.yaml
full_text_providers:
  - myrepo
  - pmc
  - unpaywall
  - openalex
```

## Provenance fields

When a reference is enriched with full text, the cached reference records where
the text came from. These provenance fields are written alongside the content:

| Field | Description |
|-------|-------------|
| `full_text_provider` | Name of the provider that supplied the full text (e.g. `pmc`, `bioc`, `epmc`, `epmc_preprint`, `unpaywall`, or a custom name). |
| `oa_status` | Open-access status reported by the provider (e.g. `gold`, `green`, `bronze`). |
| `license` | License of the open-access copy, when known. |
| `local_pdf_path` | Path (relative to the cache directory) to the downloaded PDF, when one was persisted. |

When full text from a PDF is obtained, the reference's `content_type` becomes
`full_text_pdf` and the extracted text replaces the abstract-only content. The
downloaded PDF lives under the cache directory and can be located at
`cache_dir / local_pdf_path`.

## See Also

- [Validating DOIs](validate-dois.md) — DOI metadata sources and supplementary files
- [Validating Entrez Accessions](validate-entrez.md) — PubMed/PMC references
- [CLI Reference](../reference/cli.md) — complete command documentation

## HTML article checks and cache recovery

An OpenAlex or Unpaywall URL may lead to a repository item record containing
only an abstract and metadata. HTML full-text acquisition now requires an
identifiable research body: publisher body markup or narrative research sections
with paragraphs, after removing abstracts and navigation. Length and additional
metadata text alone do not establish full text. This also applies when a URL
advertised as a PDF actually returns HTML. Genuine HTML research bodies remain
eligible, including short bodies above the existing 500-character minimum.

Ambiguous layouts are rejected and the next configured provider is tried. The
fetcher does not crawl repository download links. If every provider completes
without usable text or an error, the reference retains its original abstract
and records `full_text_attempted: true`.

New `full_text_html` cache entries carry `html_full_text_version: 2`. Entries
with an older stamp, or none, are refreshed on their next validation read.
Version 2 keeps all of an article region's text rather than only its `<p>`
text, so lists, tables, headings and bare `<div>` text can be quoted. This migration covers all providers because cached plain text
cannot establish which HTML body structure was present. It does not invalidate
current PDF, XML, or abstract caches.

If refreshing an entry stamped `html_full_text_version: 1` fails, validation
falls back to it with a warning, as for other content types: it is a checked
article body, though it may lack list and table text. If refreshing an entry with
no stamp fails, validation does **not** fall back to that
entry: its text may be repository metadata rather than article evidence. The
file remains untouched for inventory/export, and the next validation run retries
recovery. Once the source is available, normal fetching replaces it with a
verified article or the available metadata/abstract. Other content types retain
the existing stale-cache fallback. Legacy `.txt` caches remain a separate,
read-only compatibility path and are not migrated by this HTML stamp.

Research headings establish body presence; they do not filter the accepted
article's other sections. For example, `Main`, `Case presentation`, and
`Limitations` remain in an accepted article. A separately marked body is also
preserved when an abstract heading uses a higher heading level. Without that
structural boundary, an unmarked structured abstract remains ambiguous and is
rejected conservatively.

A provider's `FullTextLocation.text` (including a custom API `text_field`) is a
trusted **already-extracted article body** contract. Configure it only for APIs
that return article text, not arbitrary page text or metadata. Plain extracted
text cannot be structurally rechecked; raw HTML supplied with an HTML hint still
passes the body classifier. The acceptance stamp records that either the HTML
check or this trusted provider contract was used.
