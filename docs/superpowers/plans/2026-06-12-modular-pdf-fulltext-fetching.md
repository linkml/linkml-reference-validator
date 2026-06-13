# Modular PDF & Full-Text Fetching Framework Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a modular, ordered full-text provider chain (PMC → Unpaywall → OpenAlex → custom) that downloads and text-extracts PDFs (and HTML/XML) into `ReferenceContent.content`, so supporting-text validation runs against full text.

**Architecture:** Keep the existing prefix-keyed `ReferenceSource` metadata layer untouched. Add three small new layers: (1) an ordered `FullTextProvider` chain that *locates* full text, (2) a `ContentAcquirer` that downloads bytes with a size cap, and (3) a format-keyed `Extractor` registry that turns bytes into text. `ReferenceFetcher` orchestrates: resolve metadata → if no full text, walk the provider chain → acquire → extract → assemble with provenance. Design spec: `docs/superpowers/specs/2026-06-12-modular-pdf-fulltext-fetching-design.md`.

**Tech Stack:** Python 3.10+, `pydantic` (config), dataclasses (models), `requests` (HTTP), `beautifulsoup4`/`lxml` (HTML/XML), `pypdf` (default PDF backend, BSD-licensed, pure-python), `jsonpath-ng` (declarative custom providers), `biopython`/Entrez (PMC). Tests: `pytest` with `unittest.mock.patch` over `requests.get` (the established pattern in this repo) + doctests.

**Conventions to follow (from repo CLAUDE.md):**
- TDD: write the failing test first, watch it fail, implement minimally, watch it pass, commit.
- Avoid `try/except` for deterministic code. The **one** legitimate boundary for `try/except` here is the orchestrator looping over *external* providers (network/corrupt-PDF failures must not abort the chain) — that is the "interfacing with external systems" exception. Individual providers/extractors stay clean and let genuine programming errors propagate.
- Docstrings + doctests on pure helpers.
- Run tests with `uv run pytest ...`; full gate is `just test` (pytest + mypy + ruff). Doctests via `just doctest`.

**Branch:** Work on `feature/modular-pdf-fulltext-fetching` (already created; the spec is committed there).

---

## File Structure

**New files:**
- `src/linkml_reference_validator/etl/identifiers.py` — `ReferenceIdentifiers` + crosswalk helper.
- `src/linkml_reference_validator/etl/acquire.py` — `ContentAcquirer` (streaming download + format resolution).
- `src/linkml_reference_validator/etl/extract/__init__.py` — `ExtractorRegistry` + imports.
- `src/linkml_reference_validator/etl/extract/base.py` — `Extractor` ABC.
- `src/linkml_reference_validator/etl/extract/pdf.py` — `PDFExtractor` + `PDFTextBackend` protocol + `PypdfBackend`.
- `src/linkml_reference_validator/etl/extract/html.py` — `HTMLExtractor`.
- `src/linkml_reference_validator/etl/extract/xml.py` — `XMLExtractor` (JATS).
- `src/linkml_reference_validator/etl/fulltext/__init__.py` — `FullTextProviderRegistry` + imports.
- `src/linkml_reference_validator/etl/fulltext/base.py` — `FullTextProvider` ABC.
- `src/linkml_reference_validator/etl/fulltext/pmc.py` — `PMCFullTextProvider`.
- `src/linkml_reference_validator/etl/fulltext/unpaywall.py` — `UnpaywallProvider`.
- `src/linkml_reference_validator/etl/fulltext/openalex.py` — `OpenAlexProvider`.
- `src/linkml_reference_validator/etl/fulltext/json_api.py` — declarative `JSONAPIFullTextProvider`.
- `src/linkml_reference_validator/etl/fulltext/loader.py` — load custom providers from YAML.
- Tests: `tests/test_extractors.py`, `tests/test_acquire.py`, `tests/test_fulltext_providers.py`, `tests/test_identifiers.py`, `tests/test_fulltext_loader.py`.

**Modified files:**
- `src/linkml_reference_validator/models.py` — new dataclasses + config fields + `ReferenceContent` provenance fields + `FullTextProviderConfig`.
- `src/linkml_reference_validator/etl/reference_fetcher.py` — orchestration + provenance frontmatter round-trip + PDF caching.
- `src/linkml_reference_validator/etl/sources/url.py` — generic URL→PDF.
- `src/linkml_reference_validator/etl/sources/pmid.py` — stop inlining PMC (return abstract; PMC now flows through the chain).
- `src/linkml_reference_validator/cli/validate.py` (+ `cli/shared.py`) — `--full-text/--no-full-text` flag.
- `pyproject.toml` — add `pypdf` dependency.
- `tests/test_pmc_fulltext.py` — adjust to the PMC-via-provider flow.

---

## Task 1: Data models — identifiers, location, provenance fields

**Files:**
- Modify: `src/linkml_reference_validator/models.py` (add after `SupplementaryFile`, before `ReferenceContent`; add fields to `ReferenceContent`)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_models.py`:

```python
def test_reference_identifiers_defaults():
    from linkml_reference_validator.models import ReferenceIdentifiers

    ids = ReferenceIdentifiers(doi="10.1/x")
    assert ids.doi == "10.1/x"
    assert ids.pmid is None
    assert ids.pmcid is None
    assert ids.url is None


def test_full_text_location_defaults():
    from linkml_reference_validator.models import FullTextLocation

    loc = FullTextLocation(url="https://x/y.pdf", format_hint="pdf", provider="unpaywall")
    assert loc.url == "https://x/y.pdf"
    assert loc.text is None
    assert loc.format_hint == "pdf"
    assert loc.provider == "unpaywall"


def test_reference_content_provenance_fields():
    from linkml_reference_validator.models import ReferenceContent

    ref = ReferenceContent(
        reference_id="DOI:10.1/x",
        content="full text",
        content_type="full_text_pdf",
        full_text_provider="unpaywall",
        full_text_url="https://x/y.pdf",
        oa_status="gold",
        license="cc-by",
        local_pdf_path="files/DOI_10.1_x.pdf",
    )
    assert ref.full_text_provider == "unpaywall"
    assert ref.oa_status == "gold"
    assert ref.local_pdf_path == "files/DOI_10.1_x.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py::test_reference_identifiers_defaults tests/test_models.py::test_full_text_location_defaults tests/test_models.py::test_reference_content_provenance_fields -v`
Expected: FAIL with `ImportError` / `TypeError: unexpected keyword argument`.

- [ ] **Step 3: Add the dataclasses and provenance fields**

In `src/linkml_reference_validator/models.py`, add immediately before the `ReferenceContent` definition:

```python
@dataclass
class ReferenceIdentifiers:
    """Cross-walked identifiers for a single reference.

    Used by full-text providers, several of which are keyed on DOI regardless of
    the original reference prefix.

    Examples:
        >>> ids = ReferenceIdentifiers(doi="10.1038/x", pmid="123")
        >>> ids.doi
        '10.1038/x'
        >>> ids.pmcid is None
        True
    """

    doi: Optional[str] = None
    pmid: Optional[str] = None
    pmcid: Optional[str] = None
    url: Optional[str] = None


@dataclass
class FullTextLocation:
    """A located full-text resource for a reference.

    A provider returns either a downloadable ``url`` (PDF/HTML/XML) or inline
    ``text`` it has already extracted.

    Examples:
        >>> loc = FullTextLocation(url="https://x/y.pdf", format_hint="pdf")
        >>> loc.format_hint
        'pdf'
        >>> loc.text is None
        True
    """

    url: Optional[str] = None
    text: Optional[str] = None
    format_hint: Optional[str] = None  # "pdf" | "html" | "xml" | "text"
    oa_status: Optional[str] = None    # "gold" | "green" | "bronze" | ...
    license: Optional[str] = None
    provider: str = ""
    version: Optional[str] = None      # "publishedVersion" | "acceptedVersion" | ...
```

Then add these fields to the end of the `ReferenceContent` dataclass field list (after `metadata`):

```python
    full_text_provider: Optional[str] = None
    full_text_url: Optional[str] = None
    oa_status: Optional[str] = None
    license: Optional[str] = None
    local_pdf_path: Optional[str] = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: PASS (including the three new tests).

- [ ] **Step 5: Run doctests for models**

Run: `uv run pytest --doctest-modules src/linkml_reference_validator/models.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/linkml_reference_validator/models.py tests/test_models.py
git commit -m "feat: add ReferenceIdentifiers, FullTextLocation, and ReferenceContent provenance fields"
```

---

## Task 2: Config fields for full-text fetching

**Files:**
- Modify: `src/linkml_reference_validator/models.py` (`ReferenceValidationConfig`, add fields after `max_supplementary_file_size`; add `get_files_cache_dir` next to `get_cache_dir`)
- Test: `tests/test_validation_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_validation_config.py`:

```python
def test_full_text_config_defaults():
    from linkml_reference_validator.models import ReferenceValidationConfig

    config = ReferenceValidationConfig()
    assert config.fetch_full_text is True
    assert config.full_text_providers == ["pmc", "unpaywall", "openalex"]
    assert config.pdf_backend == "pypdf"
    assert config.download_pdfs is True


def test_files_cache_dir(tmp_path):
    from linkml_reference_validator.models import ReferenceValidationConfig

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache")
    files_dir = config.get_files_cache_dir()
    assert files_dir == tmp_path / "cache" / "files"
    assert files_dir.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_validation_config.py::test_full_text_config_defaults tests/test_validation_config.py::test_files_cache_dir -v`
Expected: FAIL with `AttributeError` / `assert ... == ...`.

- [ ] **Step 3: Add config fields and helper**

In `src/linkml_reference_validator/models.py`, inside `ReferenceValidationConfig`, after the `max_supplementary_file_size` field:

```python
    fetch_full_text: bool = Field(
        default=True,
        description=(
            "If True, attempt to obtain full text via the full_text_providers chain "
            "when a metadata source does not already return full text."
        ),
    )
    full_text_providers: list[str] = Field(
        default_factory=lambda: ["pmc", "unpaywall", "openalex"],
        description=(
            "Ordered list of full-text provider names to try until one yields usable "
            "full text. Names map to built-in providers (pmc, unpaywall, openalex) or "
            "custom providers loaded from YAML."
        ),
    )
    pdf_backend: str = Field(
        default="pypdf",
        description="Name of the PDF text-extraction backend to use (e.g. 'pypdf').",
    )
    download_pdfs: bool = Field(
        default=True,
        description="If True, persist downloaded PDFs to the files cache directory.",
    )
```

Then add this method right after `get_cache_dir`:

```python
    def get_files_cache_dir(self) -> Path:
        """Create and return the binary-files cache directory (for downloaded PDFs).

        Examples:
            >>> import tempfile
            >>> from pathlib import Path
            >>> config = ReferenceValidationConfig(cache_dir=Path(tempfile.mkdtemp()))
            >>> d = config.get_files_cache_dir()
            >>> d.name
            'files'
            >>> d.exists()
            True
        """
        files_dir = self.cache_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)
        return files_dir
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_validation_config.py -v`
Expected: PASS.

- [ ] **Step 5: Run doctests**

Run: `uv run pytest --doctest-modules src/linkml_reference_validator/models.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/linkml_reference_validator/models.py tests/test_validation_config.py
git commit -m "feat: add full-text fetching config fields and files cache dir"
```

---

## Task 3: Extractor base class and registry

**Files:**
- Create: `src/linkml_reference_validator/etl/extract/base.py`
- Create: `src/linkml_reference_validator/etl/extract/__init__.py`
- Test: `tests/test_extractors.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_extractors.py`:

```python
"""Tests for content extractors."""

import pytest

from linkml_reference_validator.etl.extract import ExtractorRegistry
from linkml_reference_validator.etl.extract.base import Extractor


class _FakeExtractor(Extractor):
    @classmethod
    def formats(cls):
        return ["fake"]

    def extract(self, data, *, content_type=None):
        return data.decode("utf-8")


def test_registry_register_and_get():
    ExtractorRegistry.register(_FakeExtractor)
    extractor = ExtractorRegistry.get("fake")
    assert extractor is not None
    assert extractor.extract(b"hello", content_type="text/plain") == "hello"


def test_registry_get_unknown_returns_none():
    assert ExtractorRegistry.get("does-not-exist") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extractors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named '...etl.extract'`.

- [ ] **Step 3: Implement base and registry**

Create `src/linkml_reference_validator/etl/extract/base.py`:

```python
"""Base class and registry for content extractors.

An extractor turns raw downloaded bytes (PDF/HTML/XML/text) into plain text.

Examples:
    >>> from linkml_reference_validator.etl.extract.base import Extractor
    >>> issubclass(Extractor, object)
    True
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

logger = logging.getLogger(__name__)


class Extractor(ABC):
    """Abstract base class for content extractors.

    Subclasses declare the formats they handle and implement ``extract``.
    """

    @classmethod
    @abstractmethod
    def formats(cls) -> list[str]:
        """Return the format keys this extractor handles (e.g. ['pdf'])."""
        ...

    @abstractmethod
    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        """Extract plain text from ``data``; return None if nothing usable."""
        ...


class ExtractorRegistry:
    """Registry mapping format keys to extractor instances.

    Examples:
        >>> from linkml_reference_validator.etl.extract.base import ExtractorRegistry
        >>> ExtractorRegistry.get("nope") is None
        True
    """

    _by_format: dict[str, Extractor] = {}

    @classmethod
    def register(cls, extractor_class: type[Extractor]) -> type[Extractor]:
        """Register an extractor class (usable as a decorator)."""
        instance = extractor_class()
        for fmt in extractor_class.formats():
            cls._by_format[fmt] = instance
            logger.debug(f"Registered extractor for format: {fmt}")
        return extractor_class

    @classmethod
    def get(cls, fmt: str) -> Optional[Extractor]:
        """Return the extractor for ``fmt``, or None if none registered."""
        return cls._by_format.get(fmt)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered extractors (for testing)."""
        cls._by_format = {}
```

Create `src/linkml_reference_validator/etl/extract/__init__.py`:

```python
"""Content extractors (PDF, HTML, XML)."""

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

__all__ = ["Extractor", "ExtractorRegistry"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_extractors.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/linkml_reference_validator/etl/extract tests/test_extractors.py
git commit -m "feat: add Extractor base class and ExtractorRegistry"
```

---

## Task 4: HTML and XML extractors

**Files:**
- Create: `src/linkml_reference_validator/etl/extract/html.py`
- Create: `src/linkml_reference_validator/etl/extract/xml.py`
- Modify: `src/linkml_reference_validator/etl/extract/__init__.py` (import to register)
- Test: `tests/test_extractors.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_extractors.py`:

```python
def test_html_extractor():
    from linkml_reference_validator.etl.extract.html import HTMLExtractor

    html = b"<html><head><title>T</title></head><body><p>Hello</p><p>World</p></body></html>"
    text = HTMLExtractor().extract(html, content_type="text/html")
    assert "Hello" in text
    assert "World" in text


def test_xml_extractor_jats_body():
    from linkml_reference_validator.etl.extract.xml import XMLExtractor

    xml = b"""<article><body><sec><p>First paragraph.</p><p>Second paragraph.</p></sec></body></article>"""
    text = XMLExtractor().extract(xml, content_type="application/xml")
    assert "First paragraph." in text
    assert "Second paragraph." in text


def test_xml_extractor_no_body_returns_none():
    from linkml_reference_validator.etl.extract.xml import XMLExtractor

    xml = b"<article><front><title>x</title></front></article>"
    assert XMLExtractor().extract(xml, content_type="application/xml") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_extractors.py::test_html_extractor tests/test_extractors.py::test_xml_extractor_jats_body -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement HTML and XML extractors**

Create `src/linkml_reference_validator/etl/extract/html.py`:

```python
"""HTML content extractor."""

import logging
from typing import Optional

from bs4 import BeautifulSoup  # type: ignore

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)


@ExtractorRegistry.register
class HTMLExtractor(Extractor):
    """Extract readable text from HTML bytes.

    Prefers an ``<article>`` or main content region; falls back to all paragraph
    text, then to the whole document text.

    Examples:
        >>> html = b"<html><body><p>Hi</p></body></html>"
        >>> HTMLExtractor().extract(html)
        'Hi'
    """

    @classmethod
    def formats(cls) -> list[str]:
        return ["html"]

    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        soup = BeautifulSoup(data, "html.parser")

        for tag in soup(["script", "style"]):
            tag.decompose()

        region = soup.find("article") or soup.find("main")
        scope = region if region is not None else soup

        paragraphs = scope.find_all("p")
        if paragraphs:
            text = "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
            if text.strip():
                return text

        text = scope.get_text(separator="\n", strip=True)
        return text if text.strip() else None
```

Create `src/linkml_reference_validator/etl/extract/xml.py`:

```python
"""JATS/PMC XML content extractor."""

import logging
from typing import Optional

from bs4 import BeautifulSoup  # type: ignore

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)


@ExtractorRegistry.register
class XMLExtractor(Extractor):
    """Extract body text from JATS/PMC article XML.

    Returns the concatenated text of paragraphs within the article ``<body>``.
    Returns None when there is no body content (e.g. restricted articles).

    Examples:
        >>> xml = b"<article><body><p>Hello body.</p></body></article>"
        >>> XMLExtractor().extract(xml)
        'Hello body.'
    """

    @classmethod
    def formats(cls) -> list[str]:
        return ["xml"]

    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        text_data = data.decode("utf-8") if isinstance(data, bytes) else data

        if "cannot be obtained" in text_data.lower() or "restricted" in text_data.lower():
            return None

        soup = BeautifulSoup(text_data, "xml")
        body = soup.find("body")
        if not body:
            return None

        paragraphs = body.find_all("p")
        if not paragraphs:
            return None

        text = "\n\n".join(p.get_text() for p in paragraphs if p.get_text().strip())
        return text if text.strip() else None
```

Update `src/linkml_reference_validator/etl/extract/__init__.py`:

```python
"""Content extractors (PDF, HTML, XML)."""

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

# Import extractors to register them
from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.extract.xml import XMLExtractor

__all__ = ["Extractor", "ExtractorRegistry", "HTMLExtractor", "XMLExtractor"]
```

- [ ] **Step 4: Run tests + doctests to verify they pass**

Run: `uv run pytest tests/test_extractors.py -v && uv run pytest --doctest-modules src/linkml_reference_validator/etl/extract/html.py src/linkml_reference_validator/etl/extract/xml.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/linkml_reference_validator/etl/extract tests/test_extractors.py
git commit -m "feat: add HTML and JATS/XML extractors"
```

---

## Task 5: PDF extractor with pluggable backend

**Files:**
- Modify: `pyproject.toml` (add `pypdf`)
- Create: `src/linkml_reference_validator/etl/extract/pdf.py`
- Modify: `src/linkml_reference_validator/etl/extract/__init__.py`
- Test: `tests/test_extractors.py`

- [ ] **Step 1: Add the dependency**

Run: `uv add "pypdf>=4.0.0"`
Expected: `pypdf` added to `[project].dependencies` in `pyproject.toml` and `uv.lock` updated.

- [ ] **Step 2: Write the failing test**

Add to `tests/test_extractors.py` (top-level helper + tests). This builds a minimal valid PDF with zero extra dependencies:

```python
def _build_minimal_pdf(text: str = "Hello PDF") -> bytes:
    """Build a minimal single-page PDF containing ``text`` (no external deps)."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = b"BT /F1 24 Tf 72 720 Td (" + text.encode("latin-1") + b") Tj ET"
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objs) + 1
    out += b"xref\n0 " + str(n).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    )
    return bytes(out)


def test_pdf_extractor_default_backend():
    from linkml_reference_validator.etl.extract.pdf import PDFExtractor

    pdf_bytes = _build_minimal_pdf("Hello PDF")
    text = PDFExtractor().extract(pdf_bytes, content_type="application/pdf")
    assert text is not None
    assert "Hello" in text


def test_pdf_extractor_named_backend():
    from linkml_reference_validator.etl.extract.pdf import PDFExtractor

    pdf_bytes = _build_minimal_pdf("Backend Test")
    text = PDFExtractor(backend="pypdf").extract(pdf_bytes)
    assert "Backend" in text


def test_pdf_extractor_unknown_backend_raises():
    from linkml_reference_validator.etl.extract.pdf import PDFExtractor

    with pytest.raises(ValueError):
        PDFExtractor(backend="not-a-backend")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_extractors.py::test_pdf_extractor_default_backend -v`
Expected: FAIL with `ModuleNotFoundError: ...extract.pdf`.

- [ ] **Step 4: Implement the PDF extractor + backend protocol**

Create `src/linkml_reference_validator/etl/extract/pdf.py`:

```python
"""PDF content extractor with a pluggable text backend.

The concrete text-extraction backend is selectable so heavier/structure-aware
backends (docling, grobid) can be swapped in later without touching callers.
"""

import io
import logging
from typing import Optional, Protocol

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

logger = logging.getLogger(__name__)


class PDFTextBackend(Protocol):
    """Protocol for a PDF-to-text backend."""

    def extract_text(self, data: bytes) -> str:
        """Return extracted plain text for the given PDF bytes."""
        ...


class PypdfBackend:
    """Default PDF backend using ``pypdf`` (BSD-licensed, pure-python).

    Examples:
        >>> isinstance(PypdfBackend(), object)
        True
    """

    def extract_text(self, data: bytes) -> str:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join(page.extract_text() or "" for page in reader.pages)


_BACKENDS: dict[str, type] = {
    "pypdf": PypdfBackend,
}


@ExtractorRegistry.register
class PDFExtractor(Extractor):
    """Extract text from PDF bytes via a named backend.

    Examples:
        >>> PDFExtractor.formats()
        ['pdf']
    """

    def __init__(self, backend: str = "pypdf"):
        backend_class = _BACKENDS.get(backend)
        if backend_class is None:
            raise ValueError(
                f"Unknown pdf_backend '{backend}'. Available: {sorted(_BACKENDS)}"
            )
        self._backend = backend_class()

    @classmethod
    def formats(cls) -> list[str]:
        return ["pdf"]

    def extract(self, data: bytes, *, content_type: Optional[str] = None) -> Optional[str]:
        text = self._backend.extract_text(data)
        return text if text and text.strip() else None
```

Update `src/linkml_reference_validator/etl/extract/__init__.py`:

```python
"""Content extractors (PDF, HTML, XML)."""

from linkml_reference_validator.etl.extract.base import Extractor, ExtractorRegistry

# Import extractors to register them
from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.extract.xml import XMLExtractor
from linkml_reference_validator.etl.extract.pdf import PDFExtractor

__all__ = [
    "Extractor",
    "ExtractorRegistry",
    "HTMLExtractor",
    "XMLExtractor",
    "PDFExtractor",
]
```

> Note: the registry registers `PDFExtractor()` with the default backend. The orchestrator (Task 13) instantiates `PDFExtractor(backend=config.pdf_backend)` directly for non-default backends.

- [ ] **Step 5: Run tests + doctests to verify they pass**

Run: `uv run pytest tests/test_extractors.py -v && uv run pytest --doctest-modules src/linkml_reference_validator/etl/extract/pdf.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/linkml_reference_validator/etl/extract tests/test_extractors.py
git commit -m "feat: add pluggable PDF extractor with pypdf default backend"
```

---

## Task 6: ContentAcquirer (download + format resolution)

**Files:**
- Create: `src/linkml_reference_validator/etl/acquire.py`
- Test: `tests/test_acquire.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_acquire.py`:

```python
"""Tests for the content acquirer."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.etl.acquire import ContentAcquirer, resolve_format


def test_resolve_format_by_content_type():
    assert resolve_format("application/pdf", "https://x/y", None) == "pdf"
    assert resolve_format("text/html; charset=utf-8", "https://x/y", None) == "html"
    assert resolve_format("application/xml", "https://x/y", None) == "xml"


def test_resolve_format_by_url_suffix():
    assert resolve_format(None, "https://x/y.pdf", None) == "pdf"
    assert resolve_format(None, "https://x/y.html", None) == "html"


def test_resolve_format_by_hint():
    assert resolve_format(None, "https://x/y", "pdf") == "pdf"


def test_resolve_format_precedence_content_type_wins():
    assert resolve_format("application/pdf", "https://x/y.html", "html") == "pdf"


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_returns_content_and_type(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/pdf", "content-length": "5"}
    mock_response.iter_content.return_value = [b"%PDF-"]
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    data, ctype = ContentAcquirer().fetch_bytes("https://x/y.pdf", config)
    assert data == b"%PDF-"
    assert ctype == "application/pdf"


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_enforces_size_cap(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/pdf"}
    mock_response.iter_content.return_value = [b"x" * 10, b"x" * 10]
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        max_supplementary_file_size=15,
    )
    data, ctype = ContentAcquirer().fetch_bytes("https://x/y.pdf", config)
    assert data is None  # exceeded cap → not returned


@patch("linkml_reference_validator.etl.acquire.requests.get")
def test_fetch_bytes_non_200_returns_none(mock_get, tmp_path):
    mock_response = MagicMock()
    mock_response.status_code = 404
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    data, ctype = ContentAcquirer().fetch_bytes("https://x/missing.pdf", config)
    assert data is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_acquire.py -v`
Expected: FAIL with `ModuleNotFoundError: ...etl.acquire`.

- [ ] **Step 3: Implement the acquirer**

Create `src/linkml_reference_validator/etl/acquire.py`:

```python
"""Download bytes from a URL with a size cap, and resolve the content format."""

import logging
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import ReferenceValidationConfig

logger = logging.getLogger(__name__)

_CONTENT_TYPE_FORMATS = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/plain": "text",
}

_SUFFIX_FORMATS = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".txt": "text",
}


def resolve_format(
    content_type: Optional[str], url: Optional[str], format_hint: Optional[str]
) -> Optional[str]:
    """Resolve a format key from content-type, then URL suffix, then provider hint.

    Examples:
        >>> resolve_format("application/pdf", "https://x/y", None)
        'pdf'
        >>> resolve_format(None, "https://x/paper.html", None)
        'html'
        >>> resolve_format(None, "https://x/y", "pdf")
        'pdf'
        >>> resolve_format(None, "https://x/y", None) is None
        True
    """
    if content_type:
        base = content_type.split(";")[0].strip().lower()
        if base in _CONTENT_TYPE_FORMATS:
            return _CONTENT_TYPE_FORMATS[base]

    if url:
        lowered = url.lower().split("?")[0]
        for suffix, fmt in _SUFFIX_FORMATS.items():
            if lowered.endswith(suffix):
                return fmt

    return format_hint


class ContentAcquirer:
    """Stream-download a URL, enforcing the configured size cap.

    Examples:
        >>> isinstance(ContentAcquirer(), object)
        True
    """

    def fetch_bytes(
        self, url: str, config: ReferenceValidationConfig
    ) -> tuple[Optional[bytes], Optional[str]]:
        """Download ``url`` and return ``(bytes, content_type)``.

        Returns ``(None, content_type)`` on non-200 responses or when the size cap
        is exceeded.
        """
        time.sleep(config.rate_limit_delay)

        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
        }
        response = requests.get(url, headers=headers, timeout=60, stream=True)
        if response.status_code != 200:
            logger.warning(f"Download failed for {url} - status {response.status_code}")
            return None, None

        content_type = response.headers.get("content-type")
        max_size = config.max_supplementary_file_size

        chunks = bytearray()
        for chunk in response.iter_content(chunk_size=8192):
            if not chunk:
                continue
            chunks.extend(chunk)
            if max_size and len(chunks) > max_size:
                logger.warning(
                    f"Download for {url} exceeded size cap ({max_size} bytes); skipping"
                )
                return None, content_type

        return bytes(chunks), content_type
```

- [ ] **Step 4: Run tests + doctests to verify they pass**

Run: `uv run pytest tests/test_acquire.py -v && uv run pytest --doctest-modules src/linkml_reference_validator/etl/acquire.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/linkml_reference_validator/etl/acquire.py tests/test_acquire.py
git commit -m "feat: add ContentAcquirer with size cap and format resolution"
```

---

## Task 7: FullTextProvider base class and registry

**Files:**
- Create: `src/linkml_reference_validator/etl/fulltext/base.py`
- Create: `src/linkml_reference_validator/etl/fulltext/__init__.py`
- Test: `tests/test_fulltext_providers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fulltext_providers.py`:

```python
"""Tests for full-text providers and their registry."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ReferenceIdentifiers,
    FullTextLocation,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)


class _FakeProvider(FullTextProvider):
    @classmethod
    def name(cls):
        return "fake"

    def locate(self, ids, config):
        return FullTextLocation(text="some text", format_hint="text", provider="fake")


def test_registry_register_and_get():
    FullTextProviderRegistry.register(_FakeProvider)
    provider = FullTextProviderRegistry.get("fake")
    assert provider is not None
    loc = provider.locate(ReferenceIdentifiers(), ReferenceValidationConfig())
    assert loc.text == "some text"


def test_registry_get_unknown_returns_none():
    assert FullTextProviderRegistry.get("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fulltext_providers.py::test_registry_register_and_get -v`
Expected: FAIL with `ModuleNotFoundError: ...etl.fulltext`.

- [ ] **Step 3: Implement base and registry**

Create `src/linkml_reference_validator/etl/fulltext/base.py`:

```python
"""Base class and registry for full-text providers.

A provider, given cross-walked identifiers, returns a FullTextLocation that points
to (or directly contains) the full text of a reference. Providers are tried in a
configured order until one yields usable text.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)

logger = logging.getLogger(__name__)


class FullTextProvider(ABC):
    """Abstract base class for full-text providers."""

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """Return the provider name used in the configured chain (e.g. 'unpaywall')."""
        ...

    @abstractmethod
    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        """Return a FullTextLocation, or None if this provider cannot supply one."""
        ...


class FullTextProviderRegistry:
    """Registry mapping provider names to provider instances.

    Examples:
        >>> from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
        >>> FullTextProviderRegistry.get("nope") is None
        True
    """

    _by_name: dict[str, FullTextProvider] = {}

    @classmethod
    def register(cls, provider_class: type[FullTextProvider]) -> type[FullTextProvider]:
        """Register a provider class (usable as a decorator)."""
        cls._by_name[provider_class.name()] = provider_class()
        logger.debug(f"Registered full-text provider: {provider_class.name()}")
        return provider_class

    @classmethod
    def register_instance(cls, name: str, provider: FullTextProvider) -> None:
        """Register a pre-built provider instance under ``name`` (for custom providers)."""
        cls._by_name[name] = provider
        logger.debug(f"Registered full-text provider instance: {name}")

    @classmethod
    def get(cls, name: str) -> Optional[FullTextProvider]:
        """Return the provider registered under ``name``, or None."""
        return cls._by_name.get(name)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered providers (for testing)."""
        cls._by_name = {}
```

Create `src/linkml_reference_validator/etl/fulltext/__init__.py`:

```python
"""Full-text providers (PMC, Unpaywall, OpenAlex, custom)."""

from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)

__all__ = ["FullTextProvider", "FullTextProviderRegistry"]
```

- [ ] **Step 4: Run tests + doctests to verify they pass**

Run: `uv run pytest tests/test_fulltext_providers.py -v && uv run pytest --doctest-modules src/linkml_reference_validator/etl/fulltext/base.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/linkml_reference_validator/etl/fulltext tests/test_fulltext_providers.py
git commit -m "feat: add FullTextProvider base class and registry"
```

---

## Task 8: UnpaywallProvider

**Files:**
- Create: `src/linkml_reference_validator/etl/fulltext/unpaywall.py`
- Modify: `src/linkml_reference_validator/etl/fulltext/__init__.py`
- Test: `tests/test_fulltext_providers.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fulltext_providers.py`:

```python
class TestUnpaywallProvider:
    @pytest.fixture
    def config(self, tmp_path):
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
        )

    @patch("linkml_reference_validator.etl.fulltext.unpaywall.requests.get")
    def test_locate_returns_pdf_location(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "is_oa": True,
            "oa_status": "gold",
            "best_oa_location": {
                "url_for_pdf": "https://oa.example.org/paper.pdf",
                "url": "https://oa.example.org/paper",
                "license": "cc-by",
                "version": "publishedVersion",
            },
        }
        mock_get.return_value = mock_response

        loc = UnpaywallProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)
        assert loc is not None
        assert loc.url == "https://oa.example.org/paper.pdf"
        assert loc.format_hint == "pdf"
        assert loc.oa_status == "gold"
        assert loc.license == "cc-by"
        assert loc.provider == "unpaywall"

    @patch("linkml_reference_validator.etl.fulltext.unpaywall.requests.get")
    def test_locate_not_oa_returns_none(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"is_oa": False, "best_oa_location": None}
        mock_get.return_value = mock_response

        assert UnpaywallProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config) is None

    def test_locate_without_doi_returns_none(self, config):
        from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

        assert UnpaywallProvider().locate(ReferenceIdentifiers(pmid="123"), config) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fulltext_providers.py::TestUnpaywallProvider -v`
Expected: FAIL with `ModuleNotFoundError: ...fulltext.unpaywall`.

- [ ] **Step 3: Implement the provider**

Create `src/linkml_reference_validator/etl/fulltext/unpaywall.py`:

```python
"""Unpaywall full-text provider.

Looks up the best open-access location for a DOI via the Unpaywall v2 API.
"""

import logging
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)

logger = logging.getLogger(__name__)


@FullTextProviderRegistry.register
class UnpaywallProvider(FullTextProvider):
    """Locate an open-access PDF/landing page for a DOI via Unpaywall.

    Examples:
        >>> UnpaywallProvider.name()
        'unpaywall'
    """

    @classmethod
    def name(cls) -> str:
        return "unpaywall"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        if not ids.doi:
            return None

        time.sleep(config.rate_limit_delay)
        url = f"https://api.unpaywall.org/v2/{ids.doi}"
        response = requests.get(url, params={"email": config.email}, timeout=30)
        if response.status_code != 200:
            logger.debug(f"Unpaywall returned {response.status_code} for DOI:{ids.doi}")
            return None

        data = response.json()
        best = data.get("best_oa_location")
        if not data.get("is_oa") or not best:
            return None

        pdf_url = best.get("url_for_pdf")
        landing = best.get("url")
        target = pdf_url or landing
        if not target:
            return None

        return FullTextLocation(
            url=target,
            format_hint="pdf" if pdf_url else "html",
            oa_status=data.get("oa_status"),
            license=best.get("license"),
            version=best.get("version"),
            provider="unpaywall",
        )
```

Update `src/linkml_reference_validator/etl/fulltext/__init__.py`:

```python
"""Full-text providers (PMC, Unpaywall, OpenAlex, custom)."""

from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)

# Import providers to register them
from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

__all__ = [
    "FullTextProvider",
    "FullTextProviderRegistry",
    "UnpaywallProvider",
]
```

- [ ] **Step 4: Run tests + doctests to verify they pass**

Run: `uv run pytest tests/test_fulltext_providers.py -v && uv run pytest --doctest-modules src/linkml_reference_validator/etl/fulltext/unpaywall.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/linkml_reference_validator/etl/fulltext tests/test_fulltext_providers.py
git commit -m "feat: add UnpaywallProvider"
```

---

## Task 9: OpenAlexProvider

**Files:**
- Create: `src/linkml_reference_validator/etl/fulltext/openalex.py`
- Modify: `src/linkml_reference_validator/etl/fulltext/__init__.py`
- Test: `tests/test_fulltext_providers.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fulltext_providers.py`:

```python
class TestOpenAlexProvider:
    @pytest.fixture
    def config(self, tmp_path):
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
        )

    @patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
    def test_locate_returns_pdf_location(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "open_access": {"is_oa": True, "oa_status": "green", "oa_url": "https://oa/paper"},
            "best_oa_location": {
                "pdf_url": "https://oa.example.org/openalex.pdf",
                "license": "cc-by",
                "version": "acceptedVersion",
            },
        }
        mock_get.return_value = mock_response

        loc = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)
        assert loc is not None
        assert loc.url == "https://oa.example.org/openalex.pdf"
        assert loc.format_hint == "pdf"
        assert loc.oa_status == "green"
        assert loc.provider == "openalex"

    @patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
    def test_locate_falls_back_to_oa_url(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "open_access": {"is_oa": True, "oa_status": "bronze", "oa_url": "https://oa/landing"},
            "best_oa_location": {"pdf_url": None},
        }
        mock_get.return_value = mock_response

        loc = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)
        assert loc.url == "https://oa/landing"
        assert loc.format_hint == "html"

    @patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
    def test_locate_not_oa_returns_none(self, mock_get, config):
        from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"open_access": {"is_oa": False}, "best_oa_location": None}
        mock_get.return_value = mock_response

        assert OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fulltext_providers.py::TestOpenAlexProvider -v`
Expected: FAIL with `ModuleNotFoundError: ...fulltext.openalex`.

- [ ] **Step 3: Implement the provider**

Create `src/linkml_reference_validator/etl/fulltext/openalex.py`:

```python
"""OpenAlex full-text provider.

Looks up open-access locations for a DOI via the OpenAlex works API.
"""

import logging
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)

logger = logging.getLogger(__name__)


@FullTextProviderRegistry.register
class OpenAlexProvider(FullTextProvider):
    """Locate an open-access PDF/landing page for a DOI via OpenAlex.

    Examples:
        >>> OpenAlexProvider.name()
        'openalex'
    """

    @classmethod
    def name(cls) -> str:
        return "openalex"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        if not ids.doi:
            return None

        time.sleep(config.rate_limit_delay)
        url = f"https://api.openalex.org/works/doi:{ids.doi}"
        response = requests.get(url, params={"mailto": config.email}, timeout=30)
        if response.status_code != 200:
            logger.debug(f"OpenAlex returned {response.status_code} for DOI:{ids.doi}")
            return None

        data = response.json()
        open_access = data.get("open_access") or {}
        if not open_access.get("is_oa"):
            return None

        best = data.get("best_oa_location") or {}
        pdf_url = best.get("pdf_url")
        oa_url = open_access.get("oa_url")
        target = pdf_url or oa_url
        if not target:
            return None

        return FullTextLocation(
            url=target,
            format_hint="pdf" if pdf_url else "html",
            oa_status=open_access.get("oa_status"),
            license=best.get("license"),
            version=best.get("version"),
            provider="openalex",
        )
```

Update `src/linkml_reference_validator/etl/fulltext/__init__.py` to import and export `OpenAlexProvider` (add the import line and list entry alongside `UnpaywallProvider`):

```python
from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider
```

and add `"OpenAlexProvider"` to `__all__`.

- [ ] **Step 4: Run tests + doctests to verify they pass**

Run: `uv run pytest tests/test_fulltext_providers.py -v && uv run pytest --doctest-modules src/linkml_reference_validator/etl/fulltext/openalex.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/linkml_reference_validator/etl/fulltext tests/test_fulltext_providers.py
git commit -m "feat: add OpenAlexProvider"
```

---

## Task 10: PMCFullTextProvider + refactor PMIDSource

**Files:**
- Create: `src/linkml_reference_validator/etl/fulltext/pmc.py`
- Modify: `src/linkml_reference_validator/etl/fulltext/__init__.py`
- Modify: `src/linkml_reference_validator/etl/sources/pmid.py` (stop inlining PMC full text)
- Test: `tests/test_fulltext_providers.py`, `tests/test_pmc_fulltext.py`

**Context:** Today `PMIDSource.fetch` calls `_fetch_pmc_fulltext` and merges abstract + full text. After this task, `PMIDSource` returns metadata + abstract only (`content_type="abstract_only"`/`"summary"`/`"unavailable"`), and PMC full text is obtained through the provider chain via `PMCFullTextProvider`, which reuses the existing `_get_pmcid`/`_fetch_pmc_xml`/`_fetch_pmc_html` logic. The PMC provider extracts XML via the `XMLExtractor` (Task 4) to stay DRY.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_fulltext_providers.py`:

```python
class TestPMCProvider:
    @pytest.fixture
    def config(self, tmp_path):
        return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)

    def test_name(self):
        from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

        assert PMCFullTextProvider.name() == "pmc"

    def test_locate_without_pmid_or_pmcid_returns_none(self, config):
        from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

        assert PMCFullTextProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config) is None

    def test_locate_returns_text_from_xml(self, config):
        from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

        provider = PMCFullTextProvider()
        long_body = "<body>" + "".join(f"<p>Sentence {i} of the body.</p>" for i in range(40)) + "</body>"
        xml = f"<article>{long_body}</article>".encode("utf-8")

        with patch.object(provider, "_resolve_pmcid", return_value="999"), \
             patch.object(provider, "_fetch_pmc_xml_bytes", return_value=xml):
            loc = provider.locate(ReferenceIdentifiers(pmid="123", pmcid="999"), config)

        assert loc is not None
        assert loc.format_hint == "xml"
        assert loc.provider == "pmc"
        assert "Sentence 0 of the body." in loc.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fulltext_providers.py::TestPMCProvider -v`
Expected: FAIL with `ModuleNotFoundError: ...fulltext.pmc`.

- [ ] **Step 3: Implement the PMC provider**

Create `src/linkml_reference_validator/etl/fulltext/pmc.py`:

```python
"""PMC full-text provider.

Resolves a PMC ID (from a PMID if needed) and returns the article body text,
fetched from the PMC XML API (with an HTML fallback) and extracted via XMLExtractor.
"""

import logging
import time
from typing import Optional

from Bio import Entrez  # type: ignore
from bs4 import BeautifulSoup  # type: ignore
import requests  # type: ignore

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)
from linkml_reference_validator.etl.extract.xml import XMLExtractor

logger = logging.getLogger(__name__)

_MIN_PMC_FULLTEXT_CHARS = 1000


@FullTextProviderRegistry.register
class PMCFullTextProvider(FullTextProvider):
    """Provide PMC full text for a reference identified by PMID/PMCID.

    Examples:
        >>> PMCFullTextProvider.name()
        'pmc'
    """

    @classmethod
    def name(cls) -> str:
        return "pmc"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        if not ids.pmcid and not ids.pmid:
            return None

        pmcid = ids.pmcid or self._resolve_pmcid(ids.pmid, config)
        if not pmcid:
            return None

        Entrez.email = config.email  # type: ignore

        xml_bytes = self._fetch_pmc_xml_bytes(pmcid, config)
        if xml_bytes:
            text = XMLExtractor().extract(xml_bytes, content_type="application/xml")
            if text and len(text) > _MIN_PMC_FULLTEXT_CHARS:
                return FullTextLocation(
                    text=text, format_hint="xml", oa_status="green", provider="pmc"
                )

        html_text = self._fetch_pmc_html(pmcid, config)
        if html_text and len(html_text) > _MIN_PMC_FULLTEXT_CHARS:
            return FullTextLocation(
                text=html_text, format_hint="html", oa_status="green", provider="pmc"
            )

        return None

    def _resolve_pmcid(self, pmid: Optional[str], config: ReferenceValidationConfig) -> Optional[str]:
        """Resolve a PMC ID from a PMID via Entrez elink."""
        if not pmid:
            return None
        Entrez.email = config.email  # type: ignore
        time.sleep(config.rate_limit_delay)

        try:
            handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid, linkname="pubmed_pmc")
            result = Entrez.read(handle)
            handle.close()
        except Exception as exc:  # external system boundary
            logger.warning("Failed to link PMID:%s to PMC: %s", pmid, exc)
            return None

        if isinstance(result, list) and result and isinstance(result[0], dict):
            link_set_db = result[0].get("LinkSetDb", [])
            if isinstance(link_set_db, list) and link_set_db:
                links = link_set_db[0].get("Link", [])
                if isinstance(links, list) and links:
                    first_link = links[0]
                    if isinstance(first_link, dict) and "Id" in first_link:
                        return str(first_link["Id"])
        return None

    def _fetch_pmc_xml_bytes(self, pmcid: str, config: ReferenceValidationConfig) -> Optional[bytes]:
        """Fetch raw PMC XML bytes for a PMC ID."""
        time.sleep(config.rate_limit_delay)
        handle = Entrez.efetch(db="pmc", id=pmcid, rettype="xml", retmode="xml")
        xml_content = handle.read()
        handle.close()
        if isinstance(xml_content, str):
            xml_content = xml_content.encode("utf-8")
        return xml_content

    def _fetch_pmc_html(self, pmcid: str, config: ReferenceValidationConfig) -> Optional[str]:
        """Fetch full text from the PMC HTML page as a fallback."""
        time.sleep(config.rate_limit_delay)
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, "html.parser")
        article_body = soup.find("div", class_="article-body") or soup.find("div", class_="tsec")
        if article_body:
            paragraphs = article_body.find_all("p")
            if paragraphs:
                return "\n\n".join(p.get_text() for p in paragraphs)
        return None
```

Update `src/linkml_reference_validator/etl/fulltext/__init__.py` to import and export `PMCFullTextProvider` (add the import and `__all__` entry).

- [ ] **Step 4: Run the new provider tests**

Run: `uv run pytest tests/test_fulltext_providers.py::TestPMCProvider -v`
Expected: PASS.

- [ ] **Step 5: Refactor PMIDSource to stop inlining PMC**

In `src/linkml_reference_validator/etl/sources/pmid.py`, in `fetch`, replace the full-text block:

```python
        abstract = self._fetch_abstract(pmid, config)
        full_text, content_type = self._fetch_pmc_fulltext(pmid, config)
        keywords = self._fetch_mesh_terms(pmid, config)

        if full_text:
            content: Optional[str] = f"{abstract}\n\n{full_text}" if abstract else full_text
        else:
            content = abstract
            content_type = "abstract_only" if abstract else "unavailable"
```

with:

```python
        abstract = self._fetch_abstract(pmid, config)
        keywords = self._fetch_mesh_terms(pmid, config)

        content: Optional[str] = abstract
        content_type = "abstract_only" if abstract else "unavailable"
```

Leave `_fetch_pmc_fulltext`, `_get_pmcid`, `_fetch_pmc_xml`, and `_fetch_pmc_html` in place for now (still covered by their unit tests); they are simply no longer called from `fetch`. (A later cleanup may remove them once the provider fully supersedes them.)

- [ ] **Step 6: Update the PMC full-text test expectations**

`tests/test_pmc_fulltext.py` currently asserts that `PMIDSource.fetch` returns merged abstract+full text. Update the high-level fetch-flow tests so that, with PMC inlining removed, `PMIDSource.fetch` returns `content_type` in `{"abstract_only", "summary", "unavailable"}` and `content` equal to the abstract. Keep any direct unit tests of `_fetch_pmc_xml`/`_fetch_pmc_html` (they still pass). Run the file to see which assertions need changing:

Run: `uv run pytest tests/test_pmc_fulltext.py -v`
Expected: identify failures tied to merged-content assertions; update those specific assertions to the abstract-only expectation. Re-run until PASS.

- [ ] **Step 7: Run the broader suite for regressions**

Run: `uv run pytest tests/test_pmc_fulltext.py tests/test_sources.py tests/test_fulltext_providers.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/linkml_reference_validator/etl/fulltext src/linkml_reference_validator/etl/sources/pmid.py tests/test_fulltext_providers.py tests/test_pmc_fulltext.py
git commit -m "feat: add PMCFullTextProvider; route PMID full text through the chain"
```

---

## Task 11: Identifier crosswalk

**Files:**
- Create: `src/linkml_reference_validator/etl/identifiers.py`
- Test: `tests/test_identifiers.py`

**Context:** Build a `ReferenceIdentifiers` from an already-fetched `ReferenceContent` plus its `reference_id`. The DOI is often already on the content (PMID esummary returns it; DOISource sets it). PMID is recoverable from the reference id. PMCID is filled **lazily** by the PMC provider itself (Task 10 already resolves it), so the crosswalk does not need to call elink here.

- [ ] **Step 1: Write the failing test**

Create `tests/test_identifiers.py`:

```python
"""Tests for identifier crosswalk."""

from linkml_reference_validator.models import ReferenceContent
from linkml_reference_validator.etl.identifiers import build_identifiers


def test_build_from_doi_reference():
    content = ReferenceContent(reference_id="DOI:10.1038/x", doi="10.1038/x")
    ids = build_identifiers(content)
    assert ids.doi == "10.1038/x"
    assert ids.pmid is None


def test_build_from_pmid_reference_with_doi_metadata():
    content = ReferenceContent(reference_id="PMID:123", doi="10.1/y")
    ids = build_identifiers(content)
    assert ids.pmid == "123"
    assert ids.doi == "10.1/y"


def test_build_from_pmid_reference_without_doi():
    content = ReferenceContent(reference_id="PMID:123")
    ids = build_identifiers(content)
    assert ids.pmid == "123"
    assert ids.doi is None


def test_build_from_url_reference():
    content = ReferenceContent(reference_id="url:https://x/y.pdf")
    ids = build_identifiers(content)
    assert ids.url == "https://x/y.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_identifiers.py -v`
Expected: FAIL with `ModuleNotFoundError: ...etl.identifiers`.

- [ ] **Step 3: Implement the crosswalk**

Create `src/linkml_reference_validator/etl/identifiers.py`:

```python
"""Build cross-walked identifiers for a reference.

Most identifier data is already present on the fetched ReferenceContent (the DOI is
returned by PubMed esummary and set by the DOI source). PMC ID resolution is done
lazily inside the PMC provider, so it is not performed here.
"""

import logging
import re
from typing import Optional

from linkml_reference_validator.models import ReferenceContent, ReferenceIdentifiers

logger = logging.getLogger(__name__)


def _split_reference_id(reference_id: str) -> tuple[Optional[str], Optional[str]]:
    """Split a reference id into (prefix, identifier).

    Examples:
        >>> _split_reference_id("PMID:123")
        ('PMID', '123')
        >>> _split_reference_id("url:https://x/y")
        ('url', 'https://x/y')
        >>> _split_reference_id("nope")
        (None, None)
    """
    match = re.match(r"^([A-Za-z_]+):(.+)$", reference_id.strip())
    if match:
        return match.group(1), match.group(2)
    return None, None


def build_identifiers(content: ReferenceContent) -> ReferenceIdentifiers:
    """Build ReferenceIdentifiers from a fetched ReferenceContent.

    Examples:
        >>> from linkml_reference_validator.models import ReferenceContent
        >>> ids = build_identifiers(ReferenceContent(reference_id="PMID:9", doi="10.1/z"))
        >>> ids.pmid, ids.doi
        ('9', '10.1/z')
    """
    prefix, identifier = _split_reference_id(content.reference_id)

    ids = ReferenceIdentifiers(doi=content.doi or None)

    if prefix and identifier:
        upper = prefix.upper()
        if upper == "PMID":
            ids.pmid = identifier
        elif upper == "PMCID":
            ids.pmcid = identifier
        elif upper == "DOI" and not ids.doi:
            ids.doi = identifier
        elif prefix.lower() == "url":
            ids.url = identifier

    return ids
```

- [ ] **Step 4: Run tests + doctests to verify they pass**

Run: `uv run pytest tests/test_identifiers.py -v && uv run pytest --doctest-modules src/linkml_reference_validator/etl/identifiers.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/linkml_reference_validator/etl/identifiers.py tests/test_identifiers.py
git commit -m "feat: add identifier crosswalk for full-text providers"
```

---

## Task 12: Orchestration — wire the full-text chain into ReferenceFetcher

**Files:**
- Modify: `src/linkml_reference_validator/etl/reference_fetcher.py`
- Test: `tests/test_reference_fetcher.py`

**Context:** After the metadata source returns content, if `config.fetch_full_text` and the content lacks full text, walk `config.full_text_providers` in order. The first provider whose location yields usable text wins. Provider/acquire/extract failures must not abort the chain — this is the legitimate `try/except` boundary for external systems.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reference_fetcher.py`:

```python
def test_enrich_with_full_text_uses_first_successful_provider(tmp_path):
    from linkml_reference_validator.models import (
        ReferenceContent,
        ReferenceValidationConfig,
        ReferenceIdentifiers,
        FullTextLocation,
    )
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.etl.fulltext.base import FullTextProvider, FullTextProviderRegistry

    class _TextProvider(FullTextProvider):
        @classmethod
        def name(cls):
            return "fake_text"

        def locate(self, ids, config):
            return FullTextLocation(text="X" * 600, format_hint="xml", provider="fake_text", oa_status="green")

    FullTextProviderRegistry.register(_TextProvider)

    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        full_text_providers=["fake_text"],
    )
    fetcher = ReferenceFetcher(config)

    content = ReferenceContent(
        reference_id="DOI:10.1/x", doi="10.1/x", content="abstract here", content_type="abstract_only"
    )
    enriched = fetcher._enrich_with_full_text(content)
    assert enriched.content_type == "full_text_xml"
    assert "X" * 600 in enriched.content
    assert enriched.full_text_provider == "fake_text"
    assert enriched.oa_status == "green"


def test_enrich_skips_when_already_full_text(tmp_path):
    from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    fetcher = ReferenceFetcher(config)
    content = ReferenceContent(
        reference_id="PMID:1", content="lots of full text", content_type="full_text_xml"
    )
    assert fetcher._needs_full_text(content) is False


def test_enrich_downloads_and_extracts_pdf(tmp_path):
    from linkml_reference_validator.models import (
        ReferenceContent,
        ReferenceValidationConfig,
        FullTextLocation,
    )
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.etl.fulltext.base import FullTextProvider, FullTextProviderRegistry
    from unittest.mock import patch

    class _PdfProvider(FullTextProvider):
        @classmethod
        def name(cls):
            return "fake_pdf"

        def locate(self, ids, config):
            return FullTextLocation(url="https://x/y.pdf", format_hint="pdf", provider="fake_pdf")

    FullTextProviderRegistry.register(_PdfProvider)

    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        full_text_providers=["fake_pdf"],
    )
    fetcher = ReferenceFetcher(config)
    content = ReferenceContent(
        reference_id="DOI:10.1/x", doi="10.1/x", content="abstract", content_type="abstract_only"
    )

    with patch.object(fetcher._acquirer, "fetch_bytes", return_value=(b"%PDF-fake", "application/pdf")), \
         patch("linkml_reference_validator.etl.reference_fetcher.PDFExtractor") as MockPDF:
        MockPDF.return_value.extract.return_value = "extracted pdf text " * 50
        enriched = fetcher._enrich_with_full_text(content)

    assert enriched.content_type == "full_text_pdf"
    assert "extracted pdf text" in enriched.content
    assert enriched.full_text_provider == "fake_pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reference_fetcher.py::test_enrich_with_full_text_uses_first_successful_provider -v`
Expected: FAIL with `AttributeError: 'ReferenceFetcher' object has no attribute '_enrich_with_full_text'`.

- [ ] **Step 3: Implement orchestration**

In `src/linkml_reference_validator/etl/reference_fetcher.py`, update the imports near the top:

```python
from linkml_reference_validator.etl.sources import ReferenceSourceRegistry
from linkml_reference_validator.etl.acquire import ContentAcquirer, resolve_format
from linkml_reference_validator.etl.identifiers import build_identifiers
from linkml_reference_validator.etl.extract import ExtractorRegistry  # noqa: F401  (registers extractors)
from linkml_reference_validator.etl.extract.pdf import PDFExtractor
import linkml_reference_validator.etl.fulltext  # noqa: F401  (registers providers)
from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
```

Add module-level constants below the imports:

```python
NEEDS_FULL_TEXT_TYPES = {
    "abstract_only",
    "unavailable",
    "no_pmc",
    "pmc_restricted",
    "summary",
}

MIN_FULL_TEXT_CHARS = 500

_FORMAT_TO_CONTENT_TYPE = {
    "pdf": "full_text_pdf",
    "html": "full_text_html",
    "xml": "full_text_xml",
    "text": "full_text",
}
```

In `__init__`, add the acquirer:

```python
        self.config = config
        self._cache: dict[str, ReferenceContent] = {}
        self._acquirer = ContentAcquirer()
```

In `fetch`, after the existing block that obtains `content` from the source and before `if content:` saves to disk, insert enrichment:

```python
        source = source_class()
        content = source.fetch(identifier, self.config)

        if content and self.config.fetch_full_text and self._needs_full_text(content):
            content = self._enrich_with_full_text(content)

        if content:
            self._cache[normalized_reference_id] = content
            self._save_to_disk(content)

        return content
```

Add these methods to the class:

```python
    def _needs_full_text(self, content: ReferenceContent) -> bool:
        """Return True if the content lacks full text and the chain should run.

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> from linkml_reference_validator.models import ReferenceContent
            >>> fetcher._needs_full_text(
            ...     ReferenceContent(reference_id="DOI:1", content_type="abstract_only")
            ... )
            True
            >>> fetcher._needs_full_text(
            ...     ReferenceContent(reference_id="DOI:1", content_type="full_text_xml")
            ... )
            False
        """
        return content.content_type in NEEDS_FULL_TEXT_TYPES

    def _enrich_with_full_text(self, content: ReferenceContent) -> ReferenceContent:
        """Walk the provider chain; merge the first usable full text into content."""
        ids = build_identifiers(content)
        abstract = content.content

        for provider_name in self.config.full_text_providers:
            provider = FullTextProviderRegistry.get(provider_name)
            if provider is None:
                logger.debug(f"Full-text provider not registered: {provider_name}")
                continue

            try:  # external system boundary: a provider failure must not abort the chain
                location = provider.locate(ids, self.config)
            except Exception as exc:
                logger.warning(f"Provider '{provider_name}' failed for {content.reference_id}: {exc}")
                continue

            if location is None:
                continue

            text, fmt, pdf_bytes = self._materialize(location)
            if not text or len(text.strip()) < MIN_FULL_TEXT_CHARS:
                continue

            content.content = f"{abstract}\n\n{text}" if abstract else text
            content.content_type = _FORMAT_TO_CONTENT_TYPE.get(fmt or "text", "full_text")
            content.full_text_provider = location.provider or provider_name
            content.full_text_url = location.url
            content.oa_status = location.oa_status
            content.license = location.license
            if pdf_bytes is not None and self.config.download_pdfs:
                content.local_pdf_path = self._save_pdf(content.reference_id, pdf_bytes)
            return content

        return content

    def _materialize(self, location) -> tuple[Optional[str], Optional[str], Optional[bytes]]:
        """Turn a FullTextLocation into (text, format, pdf_bytes_if_any)."""
        if location.text:
            return location.text, location.format_hint or "text", None

        if not location.url:
            return None, None, None

        try:  # external system boundary
            data, content_type = self._acquirer.fetch_bytes(location.url, self.config)
        except Exception as exc:
            logger.warning(f"Download failed for {location.url}: {exc}")
            return None, None, None

        if data is None:
            return None, None, None

        fmt = resolve_format(content_type, location.url, location.format_hint)
        if fmt is None:
            return None, None, None

        if fmt == "pdf":
            extractor = PDFExtractor(backend=self.config.pdf_backend)
        else:
            extractor = ExtractorRegistry.get(fmt)
        if extractor is None:
            return None, fmt, None

        try:  # external system boundary: parsing arbitrary downloaded bytes
            text = extractor.extract(data, content_type=content_type)
        except Exception as exc:
            logger.warning(f"Extraction failed for {location.url}: {exc}")
            return None, fmt, None

        pdf_bytes = data if fmt == "pdf" else None
        return text, fmt, pdf_bytes

    def _save_pdf(self, reference_id: str, data: bytes) -> str:
        """Persist a downloaded PDF and return its path relative to the cache dir."""
        safe_id = (
            reference_id.replace(":", "_").replace("/", "_").replace("?", "_").replace("=", "_")
        )
        files_dir = self.config.get_files_cache_dir()
        pdf_path = files_dir / f"{safe_id}.pdf"
        pdf_path.write_bytes(data)
        return str(pdf_path.relative_to(self.config.cache_dir))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_reference_fetcher.py -v`
Expected: PASS (new enrichment tests + existing tests).

- [ ] **Step 5: Run doctests**

Run: `uv run pytest --doctest-modules src/linkml_reference_validator/etl/reference_fetcher.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/linkml_reference_validator/etl/reference_fetcher.py tests/test_reference_fetcher.py
git commit -m "feat: wire full-text provider chain into ReferenceFetcher with PDF download+extract"
```

---

## Task 13: Round-trip provenance fields through the disk cache

**Files:**
- Modify: `src/linkml_reference_validator/etl/reference_fetcher.py` (`_save_to_disk`, `_load_markdown_format`)
- Test: `tests/test_reference_fetcher.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_reference_fetcher.py`:

```python
def test_provenance_round_trips_through_cache(tmp_path):
    from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    fetcher = ReferenceFetcher(config)

    content = ReferenceContent(
        reference_id="DOI:10.1/x",
        title="Paper",
        content="full body text",
        content_type="full_text_pdf",
        full_text_provider="unpaywall",
        full_text_url="https://oa/x.pdf",
        oa_status="gold",
        license="cc-by",
        local_pdf_path="files/DOI_10.1_x.pdf",
    )
    fetcher._save_to_disk(content)
    loaded = fetcher._load_from_disk("DOI:10.1/x")

    assert loaded.content_type == "full_text_pdf"
    assert loaded.full_text_provider == "unpaywall"
    assert loaded.full_text_url == "https://oa/x.pdf"
    assert loaded.oa_status == "gold"
    assert loaded.license == "cc-by"
    assert loaded.local_pdf_path == "files/DOI_10.1_x.pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reference_fetcher.py::test_provenance_round_trips_through_cache -v`
Expected: FAIL (loaded provenance fields are None).

- [ ] **Step 3: Write provenance to frontmatter**

In `_save_to_disk`, after the `content_type` line is appended (after the block that writes `content_type: {reference.content_type}`), add:

```python
        if reference.full_text_provider:
            lines.append(f"full_text_provider: {reference.full_text_provider}")
        if reference.full_text_url:
            lines.append(f"full_text_url: {self._quote_yaml_value(reference.full_text_url)}")
        if reference.oa_status:
            lines.append(f"oa_status: {reference.oa_status}")
        if reference.license:
            lines.append(f"license: {self._quote_yaml_value(reference.license)}")
        if reference.local_pdf_path:
            lines.append(f"local_pdf_path: {self._quote_yaml_value(reference.local_pdf_path)}")
```

- [ ] **Step 4: Read provenance from frontmatter**

In `_load_markdown_format`, add these keyword arguments to the `ReferenceContent(...)` constructor call:

```python
            full_text_provider=frontmatter.get("full_text_provider"),
            full_text_url=frontmatter.get("full_text_url"),
            oa_status=frontmatter.get("oa_status"),
            license=frontmatter.get("license"),
            local_pdf_path=frontmatter.get("local_pdf_path"),
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_reference_fetcher.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/linkml_reference_validator/etl/reference_fetcher.py tests/test_reference_fetcher.py
git commit -m "feat: persist full-text provenance fields in the disk cache"
```

---

## Task 14: Generic URL→PDF in URLSource

**Files:**
- Modify: `src/linkml_reference_validator/etl/sources/url.py`
- Test: `tests/test_sources.py`

**Context:** When a `url:` reference points at a PDF, fetch the bytes and extract text instead of returning raw bytes as `content`. Detect by content-type header or a `%PDF` magic-number prefix.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_sources.py` (within the URL source test area; mirror the existing `@patch("...sources.url.requests.get")` style):

```python
@patch("linkml_reference_validator.etl.sources.url.requests.get")
def test_fetch_url_pdf_extracts_text(mock_get, tmp_path):
    from linkml_reference_validator.models import ReferenceValidationConfig
    from linkml_reference_validator.etl.sources.url import URLSource
    from unittest.mock import patch as _patch

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.headers = {"content-type": "application/pdf"}
    mock_response.content = b"%PDF-1.4 fake bytes"
    mock_get.return_value = mock_response

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    source = URLSource()

    with _patch("linkml_reference_validator.etl.sources.url.PDFExtractor") as MockPDF:
        MockPDF.return_value.extract.return_value = "extracted pdf text"
        result = source.fetch("https://x/y.pdf", config)

    assert result is not None
    assert result.content == "extracted pdf text"
    assert result.content_type == "full_text_pdf"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_sources.py::test_fetch_url_pdf_extracts_text -v`
Expected: FAIL (content would be raw text / `ImportError` for PDFExtractor).

- [ ] **Step 3: Implement URL→PDF handling**

In `src/linkml_reference_validator/etl/sources/url.py`, add an import:

```python
from linkml_reference_validator.etl.extract.pdf import PDFExtractor
```

Then in `fetch`, replace the block after the status check:

```python
        content = response.text
        title = self._extract_title(content, url)

        return ReferenceContent(
            reference_id=f"url:{url}",
            title=title,
            content=content,
            content_type="url",
        )
```

with:

```python
        content_type_header = (response.headers.get("content-type") or "").lower()
        is_pdf = "application/pdf" in content_type_header or response.content[:5] == b"%PDF-"

        if is_pdf:
            text = PDFExtractor(backend=config.pdf_backend).extract(
                response.content, content_type="application/pdf"
            )
            return ReferenceContent(
                reference_id=f"url:{url}",
                title=url,
                content=text,
                content_type="full_text_pdf" if text else "unavailable",
                full_text_url=url,
            )

        content = response.text
        title = self._extract_title(content, url)

        return ReferenceContent(
            reference_id=f"url:{url}",
            title=title,
            content=content,
            content_type="url",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_sources.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/linkml_reference_validator/etl/sources/url.py tests/test_sources.py
git commit -m "feat: extract text from PDFs served at a url: reference"
```

---

## Task 15: Declarative custom full-text providers (JSON API + loader)

**Files:**
- Modify: `src/linkml_reference_validator/models.py` (add `FullTextProviderConfig`)
- Create: `src/linkml_reference_validator/etl/fulltext/json_api.py`
- Create: `src/linkml_reference_validator/etl/fulltext/loader.py`
- Test: `tests/test_fulltext_loader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_fulltext_loader.py`:

```python
"""Tests for declarative custom full-text providers."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import (
    FullTextProviderConfig,
    ReferenceValidationConfig,
    ReferenceIdentifiers,
)
from linkml_reference_validator.etl.fulltext.json_api import JSONAPIFullTextProvider
from linkml_reference_validator.etl.fulltext.loader import (
    load_custom_full_text_providers,
    register_custom_full_text_providers,
)
from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry


def test_config_dataclass():
    cfg = FullTextProviderConfig(
        name="myrepo",
        url_template="https://api.example.org/ft/{doi}",
        location_field="$.pdf_url",
        format_hint="pdf",
    )
    assert cfg.name == "myrepo"
    assert cfg.location_field == "$.pdf_url"


@patch("linkml_reference_validator.etl.fulltext.json_api.requests.get")
def test_json_api_provider_locates_url(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"pdf_url": "https://api.example.org/x.pdf"}
    mock_get.return_value = mock_response

    cfg = FullTextProviderConfig(
        name="myrepo",
        url_template="https://api.example.org/ft/{doi}",
        location_field="$.pdf_url",
        format_hint="pdf",
    )
    provider = JSONAPIFullTextProvider(cfg)
    loc = provider.locate(ReferenceIdentifiers(doi="10.1/x"), ReferenceValidationConfig())
    assert loc.url == "https://api.example.org/x.pdf"
    assert loc.format_hint == "pdf"
    assert loc.provider == "myrepo"


def test_loader_reads_yaml_file(tmp_path):
    yaml_file = tmp_path / "providers.yaml"
    yaml_file.write_text(
        "full_text_providers:\n"
        "  myrepo:\n"
        "    url_template: https://api.example.org/ft/{doi}\n"
        "    location_field: $.pdf_url\n"
        "    format_hint: pdf\n"
    )
    configs = load_custom_full_text_providers(providers_file=yaml_file)
    assert len(configs) == 1
    assert configs[0].name == "myrepo"


def test_register_custom_provider(tmp_path):
    yaml_file = tmp_path / "providers.yaml"
    yaml_file.write_text(
        "full_text_providers:\n"
        "  myrepo2:\n"
        "    url_template: https://api.example.org/ft/{doi}\n"
        "    location_field: $.pdf_url\n"
    )
    count = register_custom_full_text_providers(providers_file=yaml_file)
    assert count == 1
    assert FullTextProviderRegistry.get("myrepo2") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fulltext_loader.py -v`
Expected: FAIL with `ImportError` for `FullTextProviderConfig` / module not found.

- [ ] **Step 3: Add the config dataclass**

In `src/linkml_reference_validator/models.py`, after `JSONAPISourceConfig`:

```python
@dataclass
class FullTextProviderConfig:
    """Configuration for a declarative custom full-text provider.

    Mirrors JSONAPISourceConfig but resolves a downloadable full-text location
    (or inline text) rather than metadata.

    Examples:
        >>> cfg = FullTextProviderConfig(
        ...     name="myrepo",
        ...     url_template="https://api.example.org/ft/{doi}",
        ...     location_field="$.pdf_url",
        ...     format_hint="pdf",
        ... )
        >>> cfg.name
        'myrepo'
    """

    name: str
    url_template: str               # supports {doi} / {pmid} / {pmcid} placeholders
    location_field: Optional[str] = None  # JSONPath to a downloadable URL
    text_field: Optional[str] = None      # JSONPath to inline text (alternative to a URL)
    format_hint: Optional[str] = None
    headers: dict[str, str] = field(default_factory=dict)  # ${VAR} interpolation
```

- [ ] **Step 4: Implement the declarative provider**

Create `src/linkml_reference_validator/etl/fulltext/json_api.py`:

```python
"""Declarative custom full-text provider driven by FullTextProviderConfig."""

import logging
import os
import re
import time
from typing import Optional

import requests  # type: ignore
from jsonpath_ng import parse as jsonpath_parse
from jsonpath_ng.exceptions import JsonPathParserError

from linkml_reference_validator.models import (
    FullTextLocation,
    FullTextProviderConfig,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.fulltext.base import FullTextProvider

logger = logging.getLogger(__name__)


class JSONAPIFullTextProvider(FullTextProvider):
    """A full-text provider whose behavior is defined by configuration.

    The ``url_template`` may reference ``{doi}``, ``{pmid}``, or ``{pmcid}``.
    """

    def __init__(self, provider_config: FullTextProviderConfig):
        self._config = provider_config

    @classmethod
    def name(cls) -> str:
        return ""  # instances carry the real name; see _name

    @property
    def _name(self) -> str:
        return self._config.name

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        url = self._build_url(ids)
        if url is None:
            return None

        time.sleep(config.rate_limit_delay)
        headers = self._interpolate_headers(self._config.headers)
        headers.setdefault("Accept", "application/json")
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.debug(f"Custom provider '{self._name}' returned {response.status_code}")
            return None

        data = response.json()

        if self._config.text_field:
            text = self._jsonpath(data, self._config.text_field)
            if text:
                return FullTextLocation(
                    text=text, format_hint=self._config.format_hint or "text", provider=self._name
                )

        if self._config.location_field:
            location_url = self._jsonpath(data, self._config.location_field)
            if location_url:
                return FullTextLocation(
                    url=location_url, format_hint=self._config.format_hint, provider=self._name
                )

        return None

    def _build_url(self, ids: ReferenceIdentifiers) -> Optional[str]:
        template = self._config.url_template
        values = {"doi": ids.doi, "pmid": ids.pmid, "pmcid": ids.pmcid}
        for key, value in values.items():
            placeholder = "{" + key + "}"
            if placeholder in template:
                if not value:
                    return None
                template = template.replace(placeholder, value)
        return template

    def _jsonpath(self, data: dict, expression: str) -> Optional[str]:
        try:
            parsed = jsonpath_parse(expression)
        except JsonPathParserError as exc:
            logger.warning(f"Invalid JSONPath '{expression}': {exc}")
            return None
        matches = parsed.find(data)
        if matches and matches[0].value is not None:
            value = matches[0].value
            return value if isinstance(value, str) else str(value)
        return None

    def _interpolate_headers(self, headers: dict[str, str]) -> dict[str, str]:
        pattern = re.compile(r"\$\{([^}]+)\}")
        result = {}
        for key, value in headers.items():
            result[key] = pattern.sub(lambda m: os.environ.get(m.group(1), ""), value)
        return result
```

- [ ] **Step 5: Implement the loader**

Create `src/linkml_reference_validator/etl/fulltext/loader.py`:

```python
"""Load and register declarative custom full-text providers from YAML.

Search order mirrors sources/loader.py:
1. Explicit providers_file
2. Project-level: .linkml-reference-validator-fulltext.yaml
3. User-level: ~/.config/linkml-reference-validator/fulltext/*.yaml
"""

import logging
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML

from linkml_reference_validator.models import FullTextProviderConfig
from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
from linkml_reference_validator.etl.fulltext.json_api import JSONAPIFullTextProvider

logger = logging.getLogger(__name__)


def load_custom_full_text_providers(
    providers_file: Optional[Path] = None,
) -> list[FullTextProviderConfig]:
    """Load custom provider configs from the standard locations."""
    configs: list[FullTextProviderConfig] = []

    if providers_file and providers_file.exists():
        configs.extend(_load_from_file(providers_file))

    project_file = Path(".linkml-reference-validator-fulltext.yaml")
    if project_file.exists():
        configs.extend(_load_from_file(project_file))

    user_dir = Path.home() / ".config" / "linkml-reference-validator" / "fulltext"
    if user_dir.exists():
        for yaml_file in sorted(user_dir.glob("*.yaml")):
            configs.extend(_load_from_file(yaml_file))

    deduped: dict[str, FullTextProviderConfig] = {}
    for cfg in configs:
        deduped[cfg.name] = cfg
    return list(deduped.values())


def _load_from_file(file_path: Path) -> list[FullTextProviderConfig]:
    yaml = YAML(typ="safe")
    data = yaml.load(file_path)
    if not isinstance(data, dict):
        logger.warning(f"Invalid full-text providers file: {file_path}")
        return []

    providers_data = data.get("full_text_providers", data)
    if not isinstance(providers_data, dict):
        return []

    configs: list[FullTextProviderConfig] = []
    for name, body in providers_data.items():
        if not isinstance(body, dict) or "url_template" not in body:
            continue
        configs.append(
            FullTextProviderConfig(
                name=name,
                url_template=body["url_template"],
                location_field=body.get("location_field"),
                text_field=body.get("text_field"),
                format_hint=body.get("format_hint"),
                headers=body.get("headers", {}) if isinstance(body.get("headers"), dict) else {},
            )
        )
    return configs


def register_custom_full_text_providers(
    providers_file: Optional[Path] = None,
) -> int:
    """Load and register custom providers; return the number registered."""
    configs = load_custom_full_text_providers(providers_file)
    for cfg in configs:
        FullTextProviderRegistry.register_instance(cfg.name, JSONAPIFullTextProvider(cfg))
        logger.info(f"Registered custom full-text provider: {cfg.name}")
    return len(configs)
```

- [ ] **Step 6: Run tests + doctests to verify they pass**

Run: `uv run pytest tests/test_fulltext_loader.py -v && uv run pytest --doctest-modules src/linkml_reference_validator/etl/fulltext/json_api.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/linkml_reference_validator/models.py src/linkml_reference_validator/etl/fulltext tests/test_fulltext_loader.py
git commit -m "feat: add declarative custom full-text providers and YAML loader"
```

---

## Task 16: Register custom providers at fetcher init + CLI flag

**Files:**
- Modify: `src/linkml_reference_validator/etl/reference_fetcher.py` (register custom providers in `__init__`)
- Modify: `src/linkml_reference_validator/cli/shared.py` (add a `FullTextOption`)
- Modify: `src/linkml_reference_validator/cli/validate.py` (wire the flag into config)
- Test: `tests/test_reference_fetcher.py`, `tests/test_cli.py`

- [ ] **Step 1: Write the failing test (fetcher registers custom providers)**

Add to `tests/test_reference_fetcher.py`:

```python
def test_fetcher_registers_custom_full_text_providers(tmp_path):
    from linkml_reference_validator.models import ReferenceValidationConfig
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry

    yaml_file = tmp_path / ".linkml-reference-validator-fulltext.yaml"
    yaml_file.write_text(
        "full_text_providers:\n"
        "  custom_at_init:\n"
        "    url_template: https://api.example.org/ft/{doi}\n"
        "    location_field: $.pdf_url\n"
    )
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", rate_limit_delay=0.0, full_text_providers_file=yaml_file
    )
    ReferenceFetcher(config)
    assert FullTextProviderRegistry.get("custom_at_init") is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_reference_fetcher.py::test_fetcher_registers_custom_full_text_providers -v`
Expected: FAIL (`full_text_providers_file` not a config field).

- [ ] **Step 3: Add the config field and registration**

In `src/linkml_reference_validator/models.py`, add to `ReferenceValidationConfig` (after `download_pdfs`):

```python
    full_text_providers_file: Optional[Path] = Field(
        default=None,
        description="Optional path to a YAML file defining custom full-text providers.",
    )
```

In `src/linkml_reference_validator/etl/reference_fetcher.py`, import the loader and call it in `__init__`:

```python
from linkml_reference_validator.etl.fulltext.loader import register_custom_full_text_providers
```

```python
        self.config = config
        self._cache: dict[str, ReferenceContent] = {}
        self._acquirer = ContentAcquirer()
        register_custom_full_text_providers(config.full_text_providers_file)
```

- [ ] **Step 4: Run the fetcher test**

Run: `uv run pytest tests/test_reference_fetcher.py::test_fetcher_registers_custom_full_text_providers -v`
Expected: PASS.

- [ ] **Step 5: Write the failing CLI test**

Inspect an existing validate-command test in `tests/test_cli.py` to copy its invocation style (the `typer.testing.CliRunner` usage). Then add a test asserting `--no-full-text` sets `fetch_full_text=False`. Use the same patching approach the existing CLI tests use to capture the constructed config (e.g. patch `ReferenceFetcher` or the validator and inspect the `config` passed). Concretely:

```python
def test_validate_no_full_text_flag(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from linkml_reference_validator.cli import app  # adjust import to match existing CLI tests

    captured = {}

    import linkml_reference_validator.cli.validate as validate_mod

    real_config_cls = validate_mod.ReferenceValidationConfig

    def _capture(**kwargs):
        cfg = real_config_cls(**kwargs)
        captured["fetch_full_text"] = cfg.fetch_full_text
        return cfg

    monkeypatch.setattr(validate_mod, "ReferenceValidationConfig", _capture)

    sample = tmp_path / "data.yaml"
    sample.write_text("id: x\n")

    runner = CliRunner()
    runner.invoke(app, ["validate", str(sample), "--no-full-text"])
    assert captured.get("fetch_full_text") is False
```

> Adjust the import of `app` and the command arguments to match the existing tests in `tests/test_cli.py`. If the validate command does not currently build `ReferenceValidationConfig` directly in `validate.py`, capture at whatever call site constructs it.

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_validate_no_full_text_flag -v`
Expected: FAIL (flag unknown / `fetch_full_text` not toggled).

- [ ] **Step 7: Add the CLI option**

In `src/linkml_reference_validator/cli/shared.py`, add:

```python
FullTextOption = Annotated[
    bool,
    typer.Option(
        "--full-text/--no-full-text",
        help="Fetch full text (PDF/HTML/XML) via the provider chain (default: on)",
    ),
]
```

In `src/linkml_reference_validator/cli/validate.py`, add a `full_text: FullTextOption = True` parameter to the validate command signature and pass `fetch_full_text=full_text` into the `ReferenceValidationConfig(...)` construction.

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py tests/test_reference_fetcher.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/linkml_reference_validator/models.py src/linkml_reference_validator/etl/reference_fetcher.py src/linkml_reference_validator/cli/shared.py src/linkml_reference_validator/cli/validate.py tests/test_cli.py tests/test_reference_fetcher.py
git commit -m "feat: register custom full-text providers at init and add --no-full-text CLI flag"
```

---

## Task 17: End-to-end integration test + full quality gate

**Files:**
- Test: `tests/test_e2e_integration.py` (add a chain-level test)

- [ ] **Step 1: Write the integration test**

Add to `tests/test_e2e_integration.py` a test that exercises metadata → chain fall-through → PDF extraction with all HTTP mocked. It registers a metadata-only stub source for a `TESTDOI` prefix is unnecessary; instead drive `_enrich_with_full_text` directly through `fetch` by mocking the DOI source and the chain:

```python
def test_full_chain_doi_falls_through_to_pdf(tmp_path):
    from unittest.mock import patch
    from linkml_reference_validator.models import (
        ReferenceValidationConfig,
        ReferenceContent,
        FullTextLocation,
    )
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.etl.fulltext.base import FullTextProvider, FullTextProviderRegistry

    class _MissProvider(FullTextProvider):
        @classmethod
        def name(cls):
            return "miss"

        def locate(self, ids, config):
            return None

    class _PdfProvider(FullTextProvider):
        @classmethod
        def name(cls):
            return "hit_pdf"

        def locate(self, ids, config):
            return FullTextLocation(url="https://oa/x.pdf", format_hint="pdf", provider="hit_pdf", oa_status="gold")

    FullTextProviderRegistry.register(_MissProvider)
    FullTextProviderRegistry.register(_PdfProvider)

    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        full_text_providers=["miss", "hit_pdf"],
    )
    fetcher = ReferenceFetcher(config)

    metadata = ReferenceContent(
        reference_id="DOI:10.1/x", doi="10.1/x", title="P", content="abstract", content_type="abstract_only"
    )

    with patch.object(fetcher, "_load_from_disk", return_value=None), \
         patch("linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source") as mock_get_source, \
         patch.object(fetcher._acquirer, "fetch_bytes", return_value=(b"%PDF-bytes", "application/pdf")), \
         patch("linkml_reference_validator.etl.reference_fetcher.PDFExtractor") as MockPDF:
        mock_source_class = mock_get_source.return_value
        mock_source_class.return_value.fetch.return_value = metadata
        MockPDF.return_value.extract.return_value = "full text body " * 60

        result = fetcher.fetch("DOI:10.1/x")

    assert result.content_type == "full_text_pdf"
    assert result.full_text_provider == "hit_pdf"
    assert result.oa_status == "gold"
    assert "full text body" in result.content
    # cached PDF written
    assert result.local_pdf_path is not None
    assert (config.cache_dir / result.local_pdf_path).exists()
```

- [ ] **Step 2: Run the integration test**

Run: `uv run pytest tests/test_e2e_integration.py::test_full_chain_doi_falls_through_to_pdf -v`
Expected: PASS.

- [ ] **Step 3: Run the full quality gate**

Run: `just test`
Expected: pytest (all tests), mypy, and ruff all PASS. Fix any type/lint issues (e.g. add `# type: ignore` on third-party imports consistent with the existing code, or annotate the `extractor` variable in `_materialize` as `Optional[Extractor]`).

- [ ] **Step 4: Run doctests**

Run: `just doctest`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e_integration.py
git commit -m "test: end-to-end full-text chain integration (metadata -> chain -> PDF)"
```

---

## Task 18: Documentation

**Files:**
- Create: `docs/how-to/fetch-full-text-and-pdfs.md`
- Modify: `docs/index.md` or the nav in `mkdocs.yml` (add a link, following existing nav structure)

- [ ] **Step 1: Write the how-to doc**

Create `docs/how-to/fetch-full-text-and-pdfs.md` documenting:
- What the provider chain is and the default order (`pmc → unpaywall → openalex`).
- Config keys: `fetch_full_text`, `full_text_providers`, `pdf_backend`, `download_pdfs`, `full_text_providers_file`, and reuse of `email` / `max_supplementary_file_size`.
- The `--full-text/--no-full-text` CLI flag.
- A YAML example for a custom provider:

```yaml
full_text_providers:
  myrepo:
    url_template: https://api.example.org/fulltext/{doi}
    location_field: $.links.pdf
    format_hint: pdf
    headers:
      Authorization: Bearer ${MYREPO_TOKEN}
```

- Provenance fields written to cached references (`full_text_provider`, `oa_status`, `license`, `local_pdf_path`).

- [ ] **Step 2: Add to nav**

Add a nav entry in `mkdocs.yml` under the existing how-to section pointing at `how-to/fetch-full-text-and-pdfs.md` (match the existing nav indentation/structure).

- [ ] **Step 3: Verify docs build**

Run: `uv run mkdocs build -q`
Expected: builds without errors/warnings about the new page.

- [ ] **Step 4: Commit**

```bash
git add docs/how-to/fetch-full-text-and-pdfs.md mkdocs.yml
git commit -m "docs: how-to for full-text and PDF fetching"
```

---

## Self-Review Notes (for the implementer)

- **Spec coverage:** download+extract PDF (Tasks 5, 12, 14), pluggable extractor (Task 5), default-on OA chain for DOIs (Tasks 8, 9, 12, 16), generic URL→PDF (Task 14), custom endpoints (Task 15), identifier crosswalk (Task 11), PMC-as-provider (Task 10), provenance + caching (Tasks 1, 12, 13), config (Tasks 2, 16), CLI (Task 16), docs (Task 18). All spec sections map to a task.
- **`try/except` policy:** the only `try/except` blocks are the external-system boundaries — Entrez/elink (pre-existing pattern, reused in PMC provider) and the orchestrator's per-provider / download / extract guards (so one bad provider or corrupt PDF falls through to the next). Pure helpers stay clean.
- **Type consistency:** `FullTextLocation` fields (`url/text/format_hint/oa_status/license/provider/version`), `ReferenceIdentifiers` (`doi/pmid/pmcid/url`), provider `name()`/`locate()`, extractor `formats()`/`extract()`, and `resolve_format`'s `(content_type, url, format_hint)` ordering are used identically across tasks.
- **Open implementation-time choices (carried from the spec):** default `pdf_backend` is `pypdf`; `MIN_FULL_TEXT_CHARS = 500` (PMC keeps its own `>1000` threshold); both are single-point constants and easy to tune.
