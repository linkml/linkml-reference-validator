# Validating Entrez Accessions

This guide shows how to validate supporting text against NCBI Entrez records for GEO, BioProject, and BioSample.

## Overview

These sources use the NCBI Entrez E-utilities `esummary` endpoint:

- **GEO** (GSE/GDS): summaries from the `gds` database
- **BioProject** (PRJNA/PRJEB/PRJDB): summaries from the `bioproject` database
- **BioSample** (SAMN/SAME/SAMD): summaries from the `biosample` database

The validator uses the returned summary/description fields as the content for matching.

## Basic Usage

### GEO (GSE or GDS)

```bash
linkml-reference-validator validate text \
  "RNA-seq analysis of cardiac tissue" \
  GEO:GSE12345
```

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

## See Also

- [Adding a New Reference Source](add-reference-source.md)
- [Quickstart](../quickstart.md)
- [CLI Reference](../reference/cli.md)
