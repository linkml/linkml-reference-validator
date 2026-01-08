# How It Works

Understanding the validation process and design decisions.

## Overview

linkml-reference-validator validates that quoted text (supporting text) actually appears in cited references. It uses **deterministic substring matching** rather than fuzzy or AI-based approaches.

## The Validation Process

### 1. Text Normalization

Before matching, both the supporting text and reference content are normalized:

- **Lowercased**: `"MUC1"` → `"muc1"`
- **Punctuation removed**: `"c-Abl"` → `"c abl"`
- **Whitespace collapsed**: Multiple spaces become single space
- **Editorial notes removed**: `"[mucin 1]"` → `""`

**Example:**
```
Original: "MUC1 [mucin 1] oncoprotein blocks c-Abl!!!"
Normalized: "muc1 oncoprotein blocks c abl"
```

This allows matching despite formatting differences while maintaining exactness.

### 2. Substring Matching

After normalization, the validator checks if the supporting text appears as a substring in the reference content.

**Simple case:**
```python
supporting_text = "MUC1 oncoprotein"
reference_content = "...The MUC1 oncoprotein blocks nuclear..."
# Match: "muc1 oncoprotein" found in normalized reference
```

### 3. Ellipsis Handling

When supporting text contains `...`, each part is matched separately:

```
Supporting: "MUC1 oncoprotein ... nuclear targeting"
Parts: ["MUC1 oncoprotein", "nuclear targeting"]
# Both parts must exist in the reference
```

### 4. Title Validation

In addition to excerpt/quote validation, the validator can verify reference titles using **exact matching** (not substring). Titles are validated when:

- A slot implements `dcterms:title` or has `slot_uri: dcterms:title`
- A slot is named `title` (fallback)

**Example:**
```yaml
reference_title: "MUC1 oncoprotein blocks nuclear targeting of c-Abl"
```

Title matching uses the same normalization as excerpts (case, whitespace, punctuation, Greek letters) but requires the **entire title to match**, not just a substring.

```python
# These match after normalization:
expected = "Role of JAK1 in Cell-Signaling"
actual = "Role of JAK1 in Cell Signaling"
# Both normalize to: "role of jak1 in cell signaling"

# These do NOT match (partial title):
expected = "Role of JAK1"  # Missing "in Cell Signaling"
actual = "Role of JAK1 in Cell Signaling"
```

See [Validating Reference Titles](../how-to/validate-titles.md) for detailed usage.

## Why Deterministic Matching?

### Not Fuzzy Matching

We explicitly avoid fuzzy/similarity matching because:

1. **Accuracy**: No false positives from "close enough" matches
2. **Reproducibility**: Same input always gives same result
3. **Explainability**: Clear why something matched or didn't
4. **Trust**: Critical for scientific accuracy

### Not AI-Based

We don't use LLMs or semantic similarity because:

1. **Determinism**: Results must be reproducible
2. **Verifiability**: Humans can verify the match themselves
3. **No hallucinations**: The text either exists or doesn't
4. **Simplicity**: No model dependencies or API costs

## Reference Fetching

The validator uses a **plugin architecture** to support multiple reference sources. Each source type is handled by a dedicated plugin that knows how to fetch and parse content from that source.

### PubMed (PMID)

For `PMID:12345678`:

1. Queries NCBI E-utilities API
2. Fetches abstract and metadata
3. Parses XML response
4. Caches as markdown with YAML frontmatter

### PubMed Central (PMC)

For `PMC:12345`:

1. Queries PMC API for full-text XML
2. Extracts all sections (abstract, introduction, methods, results, discussion)
3. Provides more content than abstracts alone
4. Also cached as markdown

### DOI (Digital Object Identifier)

For `DOI:10.1234/example`:

1. Queries Crossref API
2. Fetches metadata and abstract (when available)
3. Caches as markdown

### Local Files

For `file:./path/to/document.md`:

1. Reads file from local filesystem
2. Extracts title from first markdown heading (or uses filename)
3. Content used as-is (no parsing for HTML files)
4. Caches to allow consistent validation

Path resolution:
- Absolute paths work directly
- Relative paths use `reference_base_dir` config if set, otherwise current directory

### URLs

For `url:https://example.com/page`:

1. Fetches page via HTTP GET
2. Extracts title from `<title>` tag (for HTML)
3. Content preserved as-is
4. Cached like other sources

## Caching

References are cached in `references_cache/` as markdown files:

```
references_cache/
  PMID_16888623.md
  PMC_3458566.md
```

**Cache file format:**
```markdown
---
reference_id: PMID:16888623
title: MUC1 oncoprotein blocks nuclear targeting...
authors:
  - Raina D
  - Ahmad R
journal: Molecular Cell
year: '2006'
doi: 10.1016/j.molcel.2006.04.017
content_type: abstract_only
---

# MUC1 oncoprotein blocks nuclear targeting...

**Authors:** Raina D, Ahmad R, ...
**Journal:** Molecular Cell (2006)

## Content

The MUC1 oncoprotein blocks nuclear targeting...
```

### Cache Benefits

- **Offline usage**: Work without network after initial fetch
- **Performance**: Instant validation after first fetch
- **Reproducibility**: Same reference version for all validations
- **Inspection**: Human-readable cache files

## LinkML Integration

The validator is a LinkML plugin that uses special slot URIs:

```yaml
classes:
  Statement:
    attributes:
      supporting_text:
        slot_uri: linkml:excerpt  # Marks as quoted text
      reference:
        slot_uri: linkml:authoritative_reference  # Marks as reference ID
      reference_title:
        slot_uri: dcterms:title  # Marks as reference title (optional)
```

When LinkML validates data, it calls our plugin for fields marked with these URIs.

The plugin discovers fields via:
- `implements` attribute (e.g., `implements: [dcterms:title]`)
- `slot_uri` attribute (e.g., `slot_uri: dcterms:title`)
- Fallback slot names (`reference`, `supporting_text`, `title`)

## Editorial Conventions

### Square Brackets `[...]`

Used for editorial clarifications inserted into quotes:

```
Original reference: "MUC1 oncoprotein blocks nuclear targeting"
Your quote: "MUC1 [mucin 1] oncoprotein blocks nuclear targeting"
```

The `[mucin 1]` is removed before matching.

### Ellipsis `...`

Used to indicate omitted text between parts:

```
Original: "MUC1 oncoprotein blocks nuclear targeting of c-Abl"
Your quote: "MUC1 oncoprotein ... c-Abl"
```

Both parts must exist in the reference.

## Design Principles

### 1. Conservative by Default

- Only exact substring matches count
- No approximations or suggestions
- Fail fast on mismatches

### 2. Progressive Disclosure

- Simple cases require minimal syntax
- Advanced features (editorial notes, ellipsis) available when needed
- Sensible defaults (cache location, etc.)

### 3. CLI-First

- Command-line is the primary interface
- Python API available for integration
- No GUI required

### 4. Standards-Based

- Uses LinkML schemas
- NCBI standard identifiers (PMID, PMC)
- Markdown for cache files

## Limitations

### What This Tool Does NOT Do

- **Semantic matching**: Won't match paraphrases
- **Citation formatting**: Not a bibliography manager
- **Fact checking**: Only verifies text existence
- **Plagiarism detection**: Not designed for that purpose

### Known Limitations

- **Abstracts only for most PMIDs**: Full text requires PMC
- **Network required**: For initial reference fetch
- **English-focused**: Normalization optimized for English text
- **No OCR**: Can't extract text from images/PDFs in papers

## When to Use This Tool

### Good Use Cases ✅

- Validating gene function claims in databases
- Checking supporting text in knowledge graphs
- Verifying quotes in scientific documentation
- Batch validation of curated annotations

### Not Recommended ❌

- Checking if ideas are supported (use human review)
- Finding similar papers (use search engines)
- Generating citations (use citation managers)
- Paraphrase detection (use plagiarism tools)
