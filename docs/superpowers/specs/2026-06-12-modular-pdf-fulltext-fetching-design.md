# Modular PDF & Full-Text Fetching Framework — Design

**Date:** 2026-06-12
**Status:** Approved (design phase)
**Approach:** A — two-layer (prefix-keyed metadata sources + ordered full-text provider chain + extractor registry)

## Problem

Today the fetcher dispatches **one source per identifier prefix** (`PMID`, `DOI`, `file`, `url`) with first-match-wins, and each source bakes in its own ad-hoc fallback (`DOISource`: Crossref→DataCite; `PMIDSource`: abstract→PMC-XML→PMC-HTML). Two gaps:

1. **No PDF handling.** `ReferenceContent.content` is always text/abstract. `SupplementaryFile` records `application/pdf` metadata but nothing downloads or text-extracts a PDF.
2. **No general, shared fallback chain.** Falling back to Unpaywall, OpenAlex, or custom endpoints to locate open-access full text would mean copy-pasting fallback logic into each source.

We want to (a) download a PDF and extract its text into `content` so supporting-text validation runs against full text, and (b) provide a modular, ordered, configurable provider chain for locating full text.

## Goals

- Locate full text for a reference via an **ordered, configurable chain** of providers, trying each until one yields usable text.
- **Download + extract** PDFs (and HTML/XML) into `content`, keeping the downloaded PDF cached.
- Built-in providers: **PMC, Unpaywall, OpenAlex**; **custom endpoints** declarable in YAML (mirroring the existing `JSONAPISourceConfig` pattern).
- **Pluggable PDF extraction backend** behind one interface (default chosen at implementation; swappable to docling/grobid later).
- Handle **generic URL→PDF**: a bare URL pointing at a PDF is detected and text-extracted.
- Default-on for DOIs; reuse the existing `email` and `max_file_size` config.

## Non-goals

- Replacing the existing prefix-keyed metadata sources or their tests (additive change).
- Unifying metadata and full-text resolution into a single provider interface (rejected Approach B — YAGNI).
- Paywall circumvention. Only open-access / legitimately reachable locations are fetched.
- Parsing supplementary data files (spreadsheets, etc.) — out of scope.

## Architecture

A reference flows through four stages; the fallback chain is stage 3.

```
reference_id
  └─► 1. Metadata resolution   (existing prefix-keyed ReferenceSource — unchanged)
        → ReferenceContent (metadata + native full text, if any)
  └─► 2. Identifier crosswalk   (build {doi, pmid, pmcid, url})
  └─► 3. Full-text provider chain (ordered, try-until-success)
        pmc → unpaywall → openalex → custom…  → FullTextLocation (url+format | inline text)
  └─► 4. Acquire + extract       (download w/ size cap → format-keyed Extractor → text)
        → assemble: content, content_type, provenance, cached PDF
```

Stage 3+4 run only when the metadata stage did **not** already yield full text
(`content_type` in `{abstract_only, unavailable, no_pmc, pmc_restricted, summary}`)
**and** `fetch_full_text` is enabled.

### Stage 1 — Metadata resolution (unchanged)

Existing `ReferenceSource` / `ReferenceSourceRegistry` dispatch is untouched. Sources
still return a `ReferenceContent` with metadata and whatever full text they natively
obtain. `PMIDSource`'s PMC logic is **refactored out** into a `PMCFullTextProvider`
(stage 3) so PMID full text flows through the same chain; `PMIDSource` keeps producing
metadata + abstract.

### Stage 2 — Identifier crosswalk

```python
@dataclass
class ReferenceIdentifiers:
    doi: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    url: Optional[str] = None
```

Built primarily from data already on hand: PubMed esummary returns the DOI;
`_get_pmcid` (elink) already resolves PMCID. Gaps are filled **lazily** — the NCBI ID
Converter is only called if a DOI-keyed provider needs a DOI we don't yet have — so the
happy path costs no extra API calls.

### Stage 3 — Full-text provider chain

```python
class FullTextProvider(ABC):
    @classmethod
    @abstractmethod
    def name(cls) -> str: ...

    @abstractmethod
    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional["FullTextLocation"]:
        """Return a downloadable location (or inline text), or None if unavailable."""
```

```python
@dataclass
class FullTextLocation:
    url: Optional[str] = None          # downloadable URL (PDF/HTML/XML)
    text: Optional[str] = None         # inline text, if the provider returns it directly
    format_hint: Optional[str] = None  # "pdf" | "html" | "xml" | "text"
    oa_status: Optional[str] = None    # "gold" | "green" | "bronze" | ...
    license: Optional[str] = None
    provider: str = ""                 # producing provider name
    version: Optional[str] = None      # "publishedVersion" | "acceptedVersion" | ...
```

A `FullTextProviderRegistry` resolves an ordered list of provider **names** (from config)
to provider instances. The orchestrator calls `locate()` on each in order, stopping at
the first that returns a location yielding usable text.

Built-in providers:

| Name        | Needs   | Endpoint / source                                            | Reads                                              |
|-------------|---------|--------------------------------------------------------------|----------------------------------------------------|
| `pmc`       | pmcid   | Entrez efetch (PMC XML) → PMC HTML fallback                   | JATS body → text (refactored from `pmid.py`)       |
| `unpaywall` | doi+email | `https://api.unpaywall.org/v2/{doi}?email={email}`         | `best_oa_location.url_for_pdf` / `.url`, oa status |
| `openalex`  | doi (email polite) | `https://api.openalex.org/works/doi:{doi}`        | `best_oa_location.pdf_url`, `open_access`          |

Custom providers are declarative, mirroring `JSONAPISourceConfig`:

```python
@dataclass
class FullTextProviderConfig:
    name: str
    url_template: str               # e.g. "https://api.example.org/fulltext/{doi}"
    location_field: str             # JSONPath to the PDF/text URL
    format_hint: Optional[str] = None
    text_field: Optional[str] = None  # JSONPath to inline text (alt. to a URL)
    headers: dict[str, str] = field(default_factory=dict)  # ${VAR} interpolation
```

Loaded from YAML via a new `full_text_providers:` section / files, mirroring
`load_custom_sources` (user-level dir, project-level file, and the main config).

### Stage 4 — Acquire + extract

```python
class ContentAcquirer:
    def fetch_bytes(
        self, url: str, config: ReferenceValidationConfig
    ) -> tuple[bytes, Optional[str]]:
        """Stream-download with the configured size cap; return (bytes, content_type)."""
```

Streaming download honoring the existing `max_file_size` (50MB default) cap; aborts if
the cap is exceeded. Format is resolved by HTTP `Content-Type` → URL suffix →
provider `format_hint`.

```python
class Extractor(ABC):
    @classmethod
    @abstractmethod
    def formats(cls) -> list[str]: ...  # e.g. ["pdf"], ["html"], ["xml"]

    @abstractmethod
    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]: ...
```

An `ExtractorRegistry` maps format → extractor. Built-ins:

- `PDFExtractor` — delegates to a pluggable `PDFTextBackend` protocol. One default backend
  ships (selected at implementation); selectable via `pdf_backend` config. Swappable to
  docling / grobid later without touching callers.
- `HTMLExtractor` — BeautifulSoup (already a dependency); strips boilerplate, returns
  article text.
- `XMLExtractor` — JATS/PMC body extraction, refactored from `pmid.py`.

**Generic URL→PDF:** `URLSource` / the acquirer sniffs `Content-Type`; PDF bytes are routed
through `PDFExtractor` rather than returned as raw text. A `url:` reference *is* its own
location, so it skips the DOI provider chain.

## Orchestration (extended `ReferenceFetcher.fetch`)

1. Normalize id → metadata dispatch (existing) → `ReferenceContent`.
2. If `fetch_full_text` and the content lacks full text (`content_type` in the set above):
   a. Build `ReferenceIdentifiers` from the content (+ lazy crosswalk).
   b. For each provider in `full_text_providers` order, call `locate()`.
   c. First non-`None` location: if `text` present use it directly; else
      `acquirer.fetch_bytes(url)` → `ExtractorRegistry.get(format).extract(...)`.
   d. If extracted text passes a length threshold, **stop**; record provenance and set
      `content_type` to `full_text_pdf` / `full_text_html` / `full_text_xml`.
3. Cache: extracted text → existing markdown cache (format unchanged); downloaded PDF →
   `references_cache/files/<safe_id>.pdf`, path recorded in `local_pdf_path`.

## Data-model changes

`ReferenceContent` gains a minimal provenance set (explicit fields → clean frontmatter
serialization rather than burying in `metadata`):

```python
full_text_provider: Optional[str] = None
full_text_url: Optional[str] = None
oa_status: Optional[str] = None
license: Optional[str] = None
local_pdf_path: Optional[str] = None
```

New `content_type` values: `full_text_pdf`, `full_text_html` (`full_text_xml` already used).
New dataclasses: `ReferenceIdentifiers`, `FullTextLocation`, `FullTextProviderConfig`.

The cache writer (`_save_to_disk`) and reader (`_load_markdown_format`) are extended to
round-trip the new frontmatter fields.

## Config additions (`ReferenceValidationConfig`)

| Field                  | Default                              | Purpose                                     |
|------------------------|--------------------------------------|---------------------------------------------|
| `fetch_full_text`      | `True`                               | Master switch for stages 3–4.               |
| `full_text_providers`  | `["pmc", "unpaywall", "openalex"]`   | Ordered provider chain (default-on for DOIs).|
| `pdf_backend`          | (impl default)                       | Selects the `PDFTextBackend`.               |
| `download_pdfs`        | `True`                               | Whether to persist the downloaded PDF.      |
| `files_cache_dir`      | `references_cache/files`             | Binary cache location for PDFs.             |

Reuses existing `email` (Unpaywall/OpenAlex polite pool) and `max_file_size` (download cap).

## Module layout

```
etl/
  reference_fetcher.py     # orchestration (extended)
  identifiers.py           # ReferenceIdentifiers + crosswalk (new)
  acquire.py               # ContentAcquirer (new)
  fulltext/
    __init__.py            # FullTextProviderRegistry
    base.py                # FullTextProvider ABC, FullTextLocation
    pmc.py                 # PMCFullTextProvider (refactored from pmid.py)
    unpaywall.py           # UnpaywallProvider (new)
    openalex.py            # OpenAlexProvider (new)
    json_api.py            # declarative custom provider (new)
    loader.py              # load custom providers from YAML (new)
  extract/
    __init__.py            # ExtractorRegistry
    base.py                # Extractor ABC
    pdf.py                 # PDFExtractor + PDFTextBackend protocol
    html.py                # HTMLExtractor
    xml.py                 # XMLExtractor (refactored JATS logic)
```

## Testing strategy (TDD, per repo rules)

- **Providers:** unit tests against **recorded real** API responses (Unpaywall/OpenAlex
  JSON fixtures) — no fake-logic mocks; parsing of `FullTextLocation` fields verified.
- **Extractors:** tiny real PDF/HTML/XML fixtures; assert extracted text content.
- **Acquirer:** size-cap enforcement; content-type/format resolution precedence.
- **Orchestration:** chain ordering, fall-through when earlier providers miss, disabled
  switch, metadata-only → provider-supplied text, and the URL→PDF path.
- **Crosswalk:** lazy fill-in; no extra calls on the happy path.
- **Doctests** on pure helpers (crosswalk parsing, format detection, location parsing).
- **CLI:** flag to force/skip full text and surface provenance; CLI tests included.

## Risks & mitigations

- **PDF backend dependency weight** → hidden behind `PDFTextBackend`; default is
  lightweight, heavier backends opt-in.
- **Rogue/huge downloads** → existing `max_file_size` cap enforced during streaming.
- **Provider rate limits / etiquette** → reuse `rate_limit_delay` and send `email` for
  Unpaywall/OpenAlex polite pools.
- **Extraction quality varies by PDF** → length threshold gates acceptance; chain
  continues to the next provider if extraction is too thin.

## Open implementation-time decisions

- Concrete default `PDFTextBackend` (e.g. pymupdf) — pick during implementation.
- Usable-text length threshold value.
- Exact JSONPath defaults for the declarative custom-provider config.
