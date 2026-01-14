# Skipping Unsupported Reference Types

When validating data that contains references from multiple sources, you may encounter reference types that aren't yet supported by the validator. Rather than failing validation entirely, you can configure the validator to skip or downgrade the severity for these references.

## Quick Start

Create a `.linkml-reference-validator.yaml` file in your project root:

```yaml
skip_prefixes:
  - SRA
  - MGNIFY
  - BIOPROJECT

unknown_prefix_severity: WARNING
```

Now references with these prefixes will be skipped, and any other unfetchable references will produce warnings instead of errors.

## Configuration Options

### skip_prefixes

A list of reference prefixes to skip entirely during validation. References with these prefixes will:

- Return `is_valid=True`
- Have severity `INFO`
- Not block validation

```yaml
skip_prefixes:
  - SRA        # NCBI Sequence Read Archive
  - MGNIFY     # EBI Metagenomics
  - BIOPROJECT # NCBI BioProject
```

Prefix matching is **case-insensitive**, so `sra`, `SRA`, and `Sra` all match.

**When to use**: When you have legitimate references that the validator doesn't yet support, but you want to keep them in your data.

### unknown_prefix_severity

Controls the severity level for references that cannot be fetched (unsupported prefix, network error, API failure). Does **not** apply to prefixes listed in `skip_prefixes`.

Options:
- `ERROR` (default) - Validation fails, exit code 1
- `WARNING` - Issue reported but validation passes
- `INFO` - Minimal reporting, validation passes

```yaml
unknown_prefix_severity: WARNING
```

**When to use**: When you want validation to continue even if some references can't be fetched, but still want to see which ones failed.

## Configuration File Locations

The validator looks for configuration in these locations (in order):

1. Path specified via `--config` CLI option
2. `.linkml-reference-validator.yaml` in current directory
3. `.linkml-reference-validator.yml` in current directory

## Examples

### Example 1: Skip Known Unsupported Types

You have a knowledge base with datasets from GEO (supported) and SRA (not yet supported):

```yaml
# data.yaml
datasets:
  - accession: geo:GSE12345
    title: Gene expression in disease X
  - accession: sra:PRJNA123456
    title: Metagenome sequencing study
```

Without configuration, validation fails on the SRA reference. Add:

```yaml
# .linkml-reference-validator.yaml
skip_prefixes:
  - SRA
```

Now validation passes, skipping the SRA reference:

```
$ linkml-reference-validator validate data data.yaml --schema schema.yaml

Validation Summary:
  Total checks: 1
  All validations passed!
```

### Example 2: Downgrade All Fetch Failures to Warnings

For a permissive validation that reports issues without failing:

```yaml
# .linkml-reference-validator.yaml
unknown_prefix_severity: WARNING
```

Output:
```
Validation Issues (1):
  [WARNING] Could not fetch reference: sra:PRJNA123456
    Location: datasets[1].title

Validation Summary:
  Total checks: 1
  All validations passed!
```

### Example 3: Combined Configuration

Skip known unsupported types, warn on unexpected failures:

```yaml
# .linkml-reference-validator.yaml
cache_dir: references_cache

skip_prefixes:
  - SRA
  - MGNIFY
  - BIOPROJECT

unknown_prefix_severity: WARNING
```

This is useful when:
- You know certain prefixes aren't supported yet (`skip_prefixes`)
- You want to catch unexpected issues without blocking CI (`unknown_prefix_severity: WARNING`)

## Adding Support for New Reference Types

Instead of skipping a reference type permanently, consider adding support for it:

1. **YAML configuration** (no code): See [Adding a Custom Reference Source](add-reference-source.md)
2. **Python plugin** (complex sources): See the same guide for the advanced approach

For example, to add MGnify support via YAML:

```yaml
# .linkml-reference-validator-sources.yaml
sources:
  MGNIFY:
    url_template: "https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}"
    fields:
      title: "$.data.attributes.study-name"
      content: "$.data.attributes.study-abstract"
```

## Relationship to Custom Sources

| Approach | Use Case |
|----------|----------|
| `skip_prefixes` | Temporarily ignore references you can't validate yet |
| `unknown_prefix_severity: WARNING` | Continue validation despite fetch failures |
| Custom source (YAML) | Add support for a new API-backed reference type |
| Custom source (Python) | Add support for complex reference types |

## See Also

- [Adding a Custom Reference Source](add-reference-source.md) - Define new reference types
- [CLI Reference](../reference/cli.md) - Command-line options
- [Validating Titles](validate-titles.md) - Title validation with `dcterms:title`
