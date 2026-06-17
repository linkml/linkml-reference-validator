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
pmc → unpaywall → openalex
```

- **`pmc`** — PubMed Central open-access subset (XML/HTML full text for many
  biomedical articles).
- **`unpaywall`** — Unpaywall open-access lookup by DOI (often a publisher or
  repository PDF).
- **`openalex`** — OpenAlex open-access location (PDF/HTML).

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
| `full_text_providers` | `[pmc, unpaywall, openalex]` | Ordered list of provider names to try until one yields usable full text. |
| `pdf_backend` | `pypdf` | Name of the PDF text-extraction backend. |
| `download_pdfs` | `true` | If true, persist downloaded PDFs to the files cache directory. |
| `full_text_providers_file` | `null` | Optional path to a YAML file defining custom full-text providers. |

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
  - unpaywall
  - openalex
pdf_backend: pypdf
download_pdfs: true
```

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
| `full_text_provider` | Name of the provider that supplied the full text (e.g. `pmc`, `unpaywall`, or a custom name). |
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
