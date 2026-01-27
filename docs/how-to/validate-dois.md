# Validating Text Against DOIs

This guide shows how to validate supporting text against publications using Digital Object Identifiers (DOIs).

## Overview

DOIs are persistent identifiers for digital objects, commonly used for journal articles and data repositories. The validator fetches publication metadata from:

1. **Crossref API** - Primary source for journal articles
2. **DataCite API** - Fallback for repository DOIs (Zenodo, Figshare, Dryad, OSTI)

This dual-source approach ensures broad coverage across both scholarly publications and data repositories.

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

## Supported Repository DOIs

The validator supports DOIs from data repositories via the DataCite API:

| Repository | DOI Prefix | Example |
|------------|------------|---------|
| Zenodo | `10.5281/zenodo.*` | `DOI:10.5281/zenodo.7961621` |
| Figshare | `10.6084/m9.figshare.*` | `DOI:10.6084/m9.figshare.123456` |
| Dryad | `10.5061/dryad.*` | `DOI:10.5061/dryad.abc123` |
| OSTI | `10.2172/*` | `DOI:10.2172/1234567` |

### Looking Up Repository DOIs

```bash
linkml-reference-validator lookup DOI:10.5281/zenodo.7961621
```

For Zenodo DOIs, the output includes supplementary file metadata:

```
Reference: DOI:10.5281/zenodo.7961621
Title: Gene Ontology Curators AI Workshop
Authors: Dickinson R, Carbon S, Mungall CJ
...
Content type: abstract_only

--- Supplementary Files (3) ---
  - Dickinson_Varenna2022.pdf (1,975,995 bytes)
  - workshop_slides.pptx (2,345,678 bytes)
  - data_analysis.xlsx (123,456 bytes)
```

### Downloading Supplementary Files

By default, only metadata about supplementary files is captured. To download the actual files:

```bash
linkml-reference-validator lookup -D DOI:10.5281/zenodo.7961621
```

Downloaded files are stored in:
```
references_cache/
  files/
    DOI_10.5281_zenodo.7961621/
      Dickinson_Varenna2022.pdf
      workshop_slides.pptx
      data_analysis.xlsx
```

### Publisher DOIs vs Repository DOIs

**Important:** Supplementary file support only works for **repository DOIs** (Zenodo, Figshare, Dryad), not for publisher DOIs (Elsevier, Springer, Nature, etc.).

| DOI Type | Example | Supplementary Files |
|----------|---------|---------------------|
| **Repository** (Zenodo) | `10.5281/zenodo.7961621` | ✅ File metadata + download |
| **Repository** (Figshare) | `10.6084/m9.figshare.123456` | ✅ File metadata + download |
| **Publisher** (Elsevier) | `10.1016/j.neuron.2011.05.021` | ❌ Not available |
| **Publisher** (Nature) | `10.1038/nature12373` | ❌ Not available |

**Why the difference?**

- **Repository APIs** (Zenodo, Figshare) are designed for data sharing and provide open, documented file APIs
- **Publisher APIs** (Elsevier, Springer) require paid institutional access or text-mining agreements
- Even when articles are in PMC, supplementary files are often not available via the OA API

**Workarounds for publisher supplementary files:**

1. **Manual download**: Download supplementary files from the publisher website and use `file:` references
2. **Data repository**: Check if the authors deposited data separately in Zenodo/Figshare/Dryad
3. **PubMed Central**: For some OA articles, supplementary files may be available via PMC

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
| Source | NCBI PubMed | Crossref + DataCite |
| Coverage | Biomedical literature | All scholarly content + data repos |
| Full text | Via PMC when available | Metadata only |
| Abstract | Usually available | Depends on publisher/repo |
| Keywords | MeSH terms | Subjects (if available) |
| Supplementary files | No | Yes (Zenodo, etc.) |

**Use PMID when:**
- Working with biomedical/life science literature
- Full text access is important
- The article is indexed in PubMed
- You need MeSH term keywords

**Use DOI when:**
- The article is not in PubMed
- Working with non-biomedical journals
- Working with data repositories (Zenodo, Figshare, Dryad)
- You need supplementary file metadata

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

The DOI may be invalid or both APIs (Crossref and DataCite) may have failed.

**How DOI resolution works:**
1. First, the validator tries Crossref API
2. If Crossref returns 404, it falls back to DataCite API
3. If both fail, the error is reported

**Check:**
1. Verify the DOI format (should be `10.prefix/suffix`)
2. Test the DOI at https://doi.org/YOUR_DOI
3. Try again later if APIs are rate-limiting
4. For repository DOIs (Zenodo, etc.), ensure the record is public

### Rate Limiting

The validator automatically respects Crossref rate limits. For bulk operations, consider:

1. Pre-caching references before validation
2. Using a polite pool (add your email in config for higher limits)

## See Also

- [Quickstart](../quickstart.md) - Getting started with validation
- [CLI Reference](../reference/cli.md) - Complete command documentation
- [Validating OBO Files](validate-obo-files.md) - Working with ontology files
