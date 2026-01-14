# Validating Entrez Accessions

This guide shows how to validate supporting text against NCBI Entrez records for GEO, BioProject, and BioSample.

## Overview

These sources use the NCBI Entrez E-utilities:

- **GEO** (GSE/GDS): Uses `esearch` to convert accessions to UIDs, then `esummary` from the `gds` database
- **BioProject** (PRJNA/PRJEB/PRJDB): Uses `esummary` from the `bioproject` database
- **BioSample** (SAMN/SAME/SAMD): Uses `esummary` from the `biosample` database

The validator uses the returned summary/description fields as the content for matching.

## Basic Usage

### GEO (GSE or GDS)

```bash
linkml-reference-validator validate text \
  "RNA-seq analysis of cardiac tissue" \
  GEO:GSE12345
```

### Validating with Title Check

You can also validate that the reference title matches your expected title:

```bash
# This will validate both the excerpt AND the title
linkml-reference-validator validate text \
  "Airway epithelial brushings" \
  GEO:GSE67472 \
  --title "Airway epithelial gene expression in asthma versus healthy controls"
```

If the title doesn't match, validation will fail with a "title mismatch" error.

### BioProject

```bash
linkml-reference-validator validate text \
  "Whole genome sequencing project for strain X" \
  BioProject:PRJNA12345
```

### BioSample

```bash
linkml-reference-validator validate text \
  "Human liver biopsy sample description" \
  BioSample:SAMN12345678
```

## Accepted Identifier Formats

You can use either prefixed or bare accessions:

```
GEO:GSE12345
GDS12345
BioProject:PRJNA12345
PRJEB12345
BioSample:SAMN12345678
SAME1234567
```

## Prefix Aliases and Normalization

Prefixes are case-insensitive and can be normalized with a configuration map. This
is useful when data uses alternate prefix styles such as `geo:` or `NCBIGeo:`.

Create `.linkml-reference-validator.yaml` with a `validation` section:

```yaml
validation:
  reference_prefix_map:
    geo: GEO
    NCBIGeo: GEO
    NCBIBioProject: BIOPROJECT
    NCBIBioSample: BIOSAMPLE
```

You can also configure this programmatically:

```python
from linkml_reference_validator.models import ReferenceValidationConfig

config = ReferenceValidationConfig(
    reference_prefix_map={"geo": "GEO", "NCBIGeo": "GEO"}
)
```

Pass the config file to CLI commands with `--config .linkml-reference-validator.yaml`.

## Pre-caching Entrez Records

For offline validation or to speed up repeated validations:

```bash
linkml-reference-validator cache reference GEO:GSE12345
linkml-reference-validator cache reference BioProject:PRJNA12345
linkml-reference-validator cache reference BioSample:SAMN12345678
```

Cached references are stored in `references_cache/` as markdown files with YAML frontmatter.

## Rate Limiting and Email

NCBI requires a valid contact email for Entrez API usage. Configure it in your settings:

```python
from linkml_reference_validator.models import ReferenceValidationConfig

config = ReferenceValidationConfig(
    email="you@example.org",
    rate_limit_delay=0.5,
)
```

## Content Availability

Entrez summaries vary by record. If a summary field is missing, the validator will return
`content_type: unavailable` and matching may fail.

## Validation Failure Scenarios

The validator catches several types of errors:

### Excerpt Not Found

When the quoted text is not in the reference content:

```bash
$ linkml-reference-validator validate text \
    "text that is not in the dataset" \
    GEO:GSE67472

Result:
  Valid: False
  Message: Text part not found as substring: 'text that is not in the dataset'
```

### Title Mismatch

When the expected title doesn't match the actual reference title:

```bash
$ linkml-reference-validator validate text \
    "Airway epithelial brushings" \
    GEO:GSE67472 \
    --title "Wrong Title Here"

Result:
  Valid: False
  Message: Title mismatch for GEO:GSE67472
    Expected: "Wrong Title Here"
    Actual: "Airway epithelial gene expression in asthma versus healthy controls"
```

### Reference Not Found

When the accession doesn't exist:

```bash
$ linkml-reference-validator validate text \
    "Some text" \
    GEO:GSE99999999999

Result:
  Valid: False
  Message: Could not fetch reference GEO:GSE99999999999
```

## Configuration File

Create `.linkml-reference-validator.yaml` in your project root for persistent configuration:

```yaml
validation:
  # NCBI requires a valid email for Entrez API usage
  email: you@example.org

  # Rate limiting (seconds between API calls)
  rate_limit_delay: 0.5

  # Cache directory for offline use
  cache_dir: references_cache

  # Map alternate prefixes to canonical forms
  reference_prefix_map:
    geo: GEO
    NCBIGeo: GEO
    NCBIBioProject: BIOPROJECT
    NCBIBioSample: BIOSAMPLE
```

Pass the config to CLI commands:

```bash
linkml-reference-validator validate text \
  "Some text" \
  GEO:GSE67472 \
  --config .linkml-reference-validator.yaml
```

## How GEO Accession-to-UID Conversion Works

The GDS Entrez database requires numeric UIDs, not accession numbers like GSE67472.
The GEOSource automatically handles this conversion:

1. **esearch**: Searches for the accession and returns the numeric UID
   ```
   esearch(db="gds", term="GSE67472[Accession]") → "200067472"
   ```

2. **esummary**: Uses the UID to fetch the dataset metadata
   ```
   esummary(db="gds", id="200067472") → {title, summary, ...}
   ```

This conversion happens transparently - you just use the GSE/GDS accession.

## See Also

- [Adding a New Reference Source](add-reference-source.md)
- [Validating Titles](validate-titles.md)
- [Quickstart](../quickstart.md)
- [CLI Reference](../reference/cli.md)
