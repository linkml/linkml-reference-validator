# Validating Text Against DOIs

This guide shows how to validate supporting text against publications using Digital Object Identifiers (DOIs).

## Overview

DOIs are persistent identifiers for digital objects, commonly used for journal articles. The validator fetches publication metadata from the [Crossref API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) when you provide a DOI reference.

## Basic Usage

### Validate a Single Quote

```bash
linkml-reference-validator validate text \
  "Nanometre-scale thermometry" \
  DOI:10.1038/nature12373
```

**Output:**
```
Validating text against DOI:10.1038/nature12373...
  Text: Nanometre-scale thermometry

Result:
  Valid: True
  Message: Supporting text validated successfully in DOI:10.1038/nature12373
```

### DOI Format

DOIs should be prefixed with `DOI:`:

```
DOI:10.1038/nature12373
DOI:10.1126/science.1234567
DOI:10.1016/j.cell.2023.01.001
```

The DOI itself follows the standard format: `10.prefix/suffix`

## Pre-caching DOIs

For offline validation or to speed up repeated validations:

```bash
linkml-reference-validator cache reference DOI:10.1038/nature12373
```

**Output:**
```
Fetching DOI:10.1038/nature12373...
Successfully cached DOI:10.1038/nature12373
  Title: Nanometre-scale thermometry in a living cell
  Authors: G. Kucsko, P. C. Maurer, N. Y. Yao
  Content type: abstract_only
  Content length: 1234 characters
```

Cached references are stored in `references_cache/` as markdown files with YAML frontmatter.

## Using DOIs in Data Files

DOIs work the same as PMIDs in LinkML data files:

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
  supporting_text: Nanometre-scale thermometry
  reference: DOI:10.1038/nature12373
- id: stmt2
  supporting_text: MUC1 oncoprotein blocks nuclear targeting
  reference: PMID:16888623
```

**Validate:**
```bash
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml \
  --target-class Statement
```

You can mix DOIs and PMIDs in the same data file.

## Repairing DOI References

The repair command also works with DOIs:

```bash
linkml-reference-validator repair text \
  "Nanometre scale thermometry" \
  DOI:10.1038/nature12373
```

## DOI vs PMID: When to Use Each

| Feature | PMID | DOI |
|---------|------|-----|
| Source | NCBI PubMed | Crossref |
| Coverage | Biomedical literature | All scholarly content |
| Full text | Via PMC when available | Metadata only |
| Abstract | Usually available | Depends on publisher |

**Use PMID when:**
- Working with biomedical/life science literature
- Full text access is important
- The article is indexed in PubMed

**Use DOI when:**
- The article is not in PubMed
- Working with non-biomedical journals
- The DOI is more readily available

## Content Availability

Unlike PMIDs which often provide abstracts, DOI metadata from Crossref may have limited content:

- **Title**: Always available
- **Authors**: Usually available
- **Abstract**: Depends on publisher policy
- **Full text**: Not available via Crossref

If the abstract is not available, validation will be limited to matching against the title and other metadata.

## Troubleshooting

### "Content type: unavailable"

This means Crossref returned metadata but no abstract. The DOI was fetched successfully, but validation may fail if your text doesn't match the title.

**Solution:** Consider using the PMID if the article is in PubMed.

### "Failed to fetch DOI"

The DOI may be invalid or the Crossref API may be temporarily unavailable.

**Check:**
1. Verify the DOI format (should be `10.prefix/suffix`)
2. Test the DOI at https://doi.org/YOUR_DOI
3. Try again later if Crossref is rate-limiting

### Rate Limiting

The validator automatically respects Crossref rate limits. For bulk operations, consider:

1. Pre-caching references before validation
2. Using a polite pool (add your email in config for higher limits)

## See Also

- [Quickstart](../quickstart.md) - Getting started with validation
- [CLI Reference](../reference/cli.md) - Complete command documentation
- [Validating OBO Files](validate-obo-files.md) - Working with ontology files
