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

## Validate Against a URL

For online resources like book chapters, documentation, or educational content:

```bash
linkml-reference-validator validate text \
  "The cell is the basic structural and functional unit of all living organisms" \
  https://example.com/biology/cell-structure
```

Or with explicit URL prefix:

```bash
linkml-reference-validator validate text \
  "The cell is the basic unit of life" \
  URL:https://example.com/biology/cells
```

The validator will:
1. Fetch the web page content
2. Extract the title from the `<title>` tag
3. Convert HTML to plain text (removing scripts, styles, navigation)
4. Cache the content locally
5. Validate your text against the extracted content

**Note:** URL validation works best with static HTML pages and may not work well with JavaScript-heavy or dynamic content.

## Key Features

- **Automatic Caching**: References cached locally after first fetch
- **Editorial Notes**: Use `[...]` for clarifications: `"MUC1 [mucin 1] oncoprotein"`
- **Ellipsis**: Use `...` for omitted text: `"MUC1 ... nuclear targeting"`
- **Deterministic Matching**: Substring-based (not AI/fuzzy matching)
- **PubMed & PMC**: Fetches from NCBI automatically
- **DOI Support**: Fetches metadata from Crossref API
- **URL Support**: Validates against web content (books, docs, educational resources)

## Next Steps

- **[Tutorial 1: Getting Started](notebooks/01_getting_started.ipynb)** - CLI basics with real examples
- **[Tutorial 2: Advanced Usage](notebooks/02_advanced_usage.ipynb)** - Data validation with LinkML schemas
- **[Concepts](concepts/how-it-works.md)** - Understanding the validation process
- **[CLI Reference](reference/cli.md)** - Complete command documentation
