# Validating ClinicalTrials.gov References

This guide shows how to validate supporting text against clinical trial records from ClinicalTrials.gov.

## Overview

The ClinicalTrials.gov source fetches trial data from the [ClinicalTrials.gov API v2](https://clinicaltrials.gov/data-api/api). It extracts:

- **Title**: Official title (falls back to brief title)
- **Content**: Brief summary (falls back to detailed description)
- **Metadata**: Trial status and lead sponsor

The source uses the [bioregistry standard prefix](https://bioregistry.io/registry/clinicaltrials) `clinicaltrials` with identifiers following the pattern `NCT` followed by 8 digits (e.g., `NCT00000001`).

## Basic Usage

Validate text against a clinical trial using its NCT identifier:

```bash
linkml-reference-validator validate text \
  "A randomized controlled trial investigating..." \
  clinicaltrials:NCT00000001
```

## Accepted Identifier Formats

You can use the bioregistry standard prefix or bare NCT identifiers:

```
clinicaltrials:NCT00000001
clinicaltrials:NCT12345678
NCT00000001
NCT12345678
```

The prefix is case-insensitive:

```
clinicaltrials:NCT00000001
CLINICALTRIALS:NCT00000001
```

## Prefix Aliases and Normalization

If your data uses alternate prefix styles (e.g., the legacy `NCT:` prefix), configure normalization in `.linkml-reference-validator.yaml`:

```yaml
validation:
  reference_prefix_map:
    NCT: clinicaltrials
    nct: clinicaltrials
    ct: clinicaltrials
    ClinicalTrials: clinicaltrials
```

Or programmatically:

```python
from linkml_reference_validator.models import ReferenceValidationConfig

config = ReferenceValidationConfig(
    reference_prefix_map={
        "NCT": "clinicaltrials",
        "ct": "clinicaltrials",
    }
)
```

## Pre-caching Clinical Trial Records

To cache trial data for offline validation or faster repeated access:

```bash
linkml-reference-validator cache reference clinicaltrials:NCT00000001
```

Cached references are stored in `references_cache/` as markdown files with YAML frontmatter containing metadata like trial status and sponsor.

## Rate Limiting

The ClinicalTrials.gov API has rate limits. The default `rate_limit_delay` of 0.5 seconds between requests should be sufficient for most use cases:

```python
from linkml_reference_validator.models import ReferenceValidationConfig

config = ReferenceValidationConfig(
    rate_limit_delay=0.5,  # default
)
```

## Content Availability

Not all trials have detailed descriptions. If only a brief summary is available, that will be used for validation. Trials without any description will return `content_type: unavailable`.

## Example: Validating Trial Descriptions

```python
from linkml_reference_validator.etl.sources import ClinicalTrialsSource
from linkml_reference_validator.models import ReferenceValidationConfig

config = ReferenceValidationConfig()
source = ClinicalTrialsSource()

# Fetch trial content
content = source.fetch("NCT00000001", config)

if content:
    print(f"Reference ID: {content.reference_id}")  # clinicaltrials:NCT00000001
    print(f"Title: {content.title}")
    print(f"Summary: {content.content}")
    print(f"Status: {content.metadata.get('status')}")
    print(f"Sponsor: {content.metadata.get('sponsor')}")
```

## Bioregistry Standard

This source follows the [bioregistry standard](https://bioregistry.io/registry/clinicaltrials) for ClinicalTrials.gov identifiers:

- **Prefix**: `clinicaltrials`
- **Pattern**: `^NCT\d{8}$`
- **Example CURIE**: `clinicaltrials:NCT00222573`

Alternative prefixes recognized by bioregistry include `clinicaltrial`, `NCT`, and `ctgov`. Use the `reference_prefix_map` configuration to normalize these to the standard prefix.

## See Also

- [Validating Entrez Accessions](validate-entrez.md) - Similar pattern for NCBI databases
- [Adding a New Reference Source](add-reference-source.md) - How the plugin system works
- [Quickstart](../quickstart.md) - Getting started guide
- [CLI Reference](../reference/cli.md) - Complete command documentation
