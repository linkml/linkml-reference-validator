# Quickstart

Get started with linkml-reference-validator in 5 minutes.

## Installation

```bash
pip install linkml-reference-validator
```

Or with uv:

```bash
uv pip install linkml-reference-validator
```

## Validate a Single Quote

The most common use case - verify that a quote appears in its cited reference:

```bash
linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting of c-Abl" \
  PMID:16888623
```

**Output:**
```
Validating text against PMID:16888623...
  Text: MUC1 oncoprotein blocks nuclear targeting of c-Abl

Result:
  Valid: True
  Message: Supporting text validated successfully in PMID:16888623
```

The reference is automatically fetched from PubMed and cached locally in `references_cache/`.

## Validate Data Files

For batch validation, create a LinkML schema and data file:

**schema.yaml:**
```yaml
id: https://example.org/my-schema
name: my-schema

prefixes:
  linkml: https://w3id.org/linkml/

classes:
  Statement:
    attributes:
      id:
        identifier: true
      supporting_text:
        slot_uri: linkml:excerpt
      reference:
        slot_uri: linkml:authoritative_reference
```

**data.yaml:**
```yaml
- id: stmt1
  supporting_text: MUC1 oncoprotein blocks nuclear targeting of c-Abl
  reference: PMID:16888623
```

**Validate:**
```bash
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml \
  --target-class Statement
```

## Validate Against a DOI

You can also validate text against DOIs using the Crossref API:

```bash
linkml-reference-validator validate text \
  "Nanometre-scale thermometry" \
  DOI:10.1038/nature12373
```

This works the same way as PMID validation - the reference is fetched and cached locally.

## Validate Against Local Files

You can also validate against local markdown, text, or HTML files:

```bash
linkml-reference-validator validate text \
  "JAK1 binds to the receptor complex" \
  file:./research/jak-notes.md
```

## Validate Against URLs

Web pages can also be used as references:

```bash
linkml-reference-validator validate text \
  "Climate change affects biodiversity" \
  url:https://example.org/climate-report.html
```

## Key Features

- **Automatic Caching**: References cached locally after first fetch
- **Editorial Notes**: Use `[...]` for clarifications: `"MUC1 [mucin 1] oncoprotein"`
- **Ellipsis**: Use `...` for omitted text: `"MUC1 ... nuclear targeting"`
- **Title Validation**: Verify reference titles with `dcterms:title`
- **Deterministic Matching**: Substring-based (not AI/fuzzy matching)
- **PubMed & PMC**: Fetches from NCBI automatically
- **DOI Support**: Fetches metadata from Crossref API
- **Local Files**: Validate against markdown, text, or HTML files
- **URL Support**: Validate against web pages

## Next Steps

- **[Tutorial 1: Getting Started](notebooks/01_getting_started.ipynb)** - CLI basics with real examples
- **[Tutorial 2: Advanced Usage](notebooks/02_advanced_usage.ipynb)** - Data validation with LinkML schemas
- **[Validating Reference Titles](how-to/validate-titles.md)** - Verify titles with `dcterms:title`
- **[Concepts](concepts/how-it-works.md)** - Understanding the validation process
- **[CLI Reference](reference/cli.md)** - Complete command documentation
