# How to Repair Validation Errors

This guide explains how to use the `repair` command to automatically fix or flag supporting text validation errors.

## Overview

After validating your data files, you may find validation errors due to:

1. **Minor text differences** - Unicode/ASCII variations (CO2 vs CO₂)
2. **Missing ellipsis connectors** - Non-contiguous text without `...` separators
3. **Fabricated snippets** - Text that doesn't appear in the reference
4. **Missing abstracts** - References without available content

The `repair` command attempts to fix these issues automatically or flags them for manual review.

## Quick Start

### Repair a Single Quote

```bash
linkml-reference-validator repair text "CO2 levels were measured" PMID:12345678
```

Output:
```
✓ Repaired successfully
  Original: CO2 levels were measured
  Repaired: CO₂ levels were measured
  Action: CHARACTER_NORMALIZATION
  Confidence: HIGH
```

### Repair a Data File (Dry Run)

```bash
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml \
  --dry-run
```

### Apply Repairs

```bash
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml \
  --no-dry-run
```

## Understanding Confidence Levels

The repair command uses confidence thresholds to determine how to handle each error:

| Confidence | Score Range | Action |
|------------|-------------|--------|
| **HIGH** | 0.95-1.00 | Auto-fix safely |
| **MEDIUM** | 0.80-0.95 | Suggest fix, needs review |
| **LOW** | 0.50-0.80 | Flag for manual review |
| **VERY_LOW** | 0.00-0.50 | Recommend removal |

## Repair Strategies

### 1. Character Normalization (High Confidence)

Fixes common Unicode/ASCII differences automatically:

**Before:**
```yaml
supporting_text: "CO2 levels were measured"
```

**After:**
```yaml
supporting_text: "CO₂ levels were measured"
```

Common mappings:
- `CO2` → `CO₂`
- `H2O` → `H₂O`
- `O2` → `O₂`
- `+/-` → `±`
- `+-` → `±`

### 2. Ellipsis Insertion (Medium Confidence)

When text parts exist in the reference but aren't contiguous:

**Before:**
```yaml
supporting_text: "Disease X affects children. Treatment involves medication Y."
```

**After:**
```yaml
supporting_text: "Disease X affects children. ... Treatment involves medication Y."
```

This requires manual review because the context between parts may be important.

### 3. Fuzzy Match Correction (Variable Confidence)

Suggests the closest matching text from the reference:

```
Suggested fix (85%): "Haemophilus influenzae type b" → "H. influenzae type b"
```

Use with caution - verify the suggestion preserves the intended meaning.

### 4. Removal Recommendation (Very Low Confidence)

Flags text that appears fabricated or hallucinated:

```
RECOMMENDED REMOVALS:
  PMID:34567890 at evidence[2]:
    Similarity: 8%
    Snippet: 'This completely made up text...'
```

**Never auto-removed** - always requires manual review.

## Configuration File

Create `.linkml-reference-validator.yaml` for project-specific settings. You can
include both validation and repair settings:

```yaml
validation:
  reference_prefix_map:
    geo: GEO
    NCBIGeo: GEO

repair:
  # Confidence thresholds
  auto_fix_threshold: 0.95
  suggest_threshold: 0.80
  removal_threshold: 0.50

  # Character mappings
  character_mappings:
    "+/-": "±"
    "CO2": "CO₂"
    "H2O": "H₂O"
    "O2": "O₂"
    "N2": "N₂"

  # References to skip (known issues)
  skip_references:
    - "PMID:12345678"

  # References trusted despite low similarity
  trusted_low_similarity:
    - "PMID:98765432"
```

Use with:
```bash
linkml-reference-validator repair data file.yaml \
  --schema schema.yaml \
  --config .linkml-reference-validator.yaml
```

## Command Reference

### `repair text`

Repair a single supporting text quote.

```bash
linkml-reference-validator repair text <TEXT> <REFERENCE_ID> [OPTIONS]
```

**Options:**
- `--cache-dir PATH` - Directory for caching references
- `--verbose` - Show detailed output
- `--auto-fix-threshold FLOAT` - Minimum similarity for auto-fixes

**Examples:**
```bash
# Basic repair
linkml-reference-validator repair text "CO2 levels" PMID:12345678

# With verbose output
linkml-reference-validator repair text "protein functions" PMID:12345678 --verbose

# Custom threshold
linkml-reference-validator repair text "text" PMID:123 --auto-fix-threshold 0.98
```

### `repair data`

Repair supporting text in a data file.

```bash
linkml-reference-validator repair data <DATA_FILE> --schema <SCHEMA> [OPTIONS]
```

**Options:**
- `--schema PATH` - Path to LinkML schema (required)
- `--target-class CLASS` - Target class to validate
- `--dry-run / --no-dry-run` - Show changes without applying (default: dry-run)
- `--auto-fix-threshold FLOAT` - Minimum similarity for auto-fixes (default: 0.95)
- `--output PATH` - Output file path (default: overwrite with backup)
- `--config PATH` - Path to repair configuration file
- `--cache-dir PATH` - Directory for caching references
- `--verbose` - Show detailed output

**Examples:**

```bash
# Dry run (default)
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml

# Apply fixes
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml \
  --no-dry-run

# Output to new file
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml \
  --no-dry-run \
  --output repaired.yaml

# With custom config
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml \
  --config .linkml-reference-validator.yaml
```

## Best Practices

### 1. Always Start with Dry Run

```bash
# First, see what would be changed
linkml-reference-validator repair data file.yaml --schema schema.yaml --dry-run

# Review the report carefully, then apply
linkml-reference-validator repair data file.yaml --schema schema.yaml --no-dry-run
```

### 2. Review Suggested Fixes

High-confidence fixes (character normalization) are safe to auto-apply. But always review:
- Ellipsis insertions (may lose important context)
- Fuzzy corrections (may change meaning)

### 3. Handle Removals Manually

Items flagged for removal are **never automatically deleted**. Review each one:
- Verify the text isn't actually in the reference
- Check if you have the wrong PMID
- Consider finding an alternative reference

### 4. Use Skip Lists for Known Issues

If a reference is known to have issues (no abstract, behind paywall), add it to skip list:

```yaml
repair:
  skip_references:
    - "PMID:12345678"  # No abstract available
```

### 5. Trust List for Verified References

If you've manually verified a low-similarity match is correct:

```yaml
repair:
  trusted_low_similarity:
    - "PMID:98765432"  # Verified manually
```

## Troubleshooting

### "No evidence items found to repair"

Your data file doesn't match the expected evidence structure. Ensure your schema has:
- A field named `supporting_text` or `snippet`
- A field named `reference` or `reference_id`

### "Flagged for removal - text not found"

The supporting text wasn't found in the reference. Possible causes:
- Text is paraphrased, not quoted
- Text is in figures/tables (not extracted)
- Wrong PMID
- AI-generated/hallucinated quote

### "Reference content not available"

The reference exists but has no retrievable content:
- Abstract-only paper with no PMC access
- Very old paper
- Retracted article

Add to skip list to ignore during repair:
```yaml
repair:
  skip_references:
    - "PMID:NOABSTRACT001"
```

## Python API

For programmatic access:

```python
from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    RepairConfig,
)
from linkml_reference_validator.validation.repairer import SupportingTextRepairer

# Configure
val_config = ReferenceValidationConfig(cache_dir="cache")
repair_config = RepairConfig(
    auto_fix_threshold=0.95,
    character_mappings={"CO2": "CO₂"},
)

# Create repairer
repairer = SupportingTextRepairer(val_config, repair_config)

# Repair single item
result = repairer.repair_single(
    supporting_text="CO2 levels were measured",
    reference_id="PMID:12345678",
)

print(f"Repaired: {result.is_repaired}")
print(f"New text: {result.repaired_text}")

# Batch repair
items = [
    ("text1", "PMID:1", "path1"),
    ("text2", "PMID:2", "path2"),
]
report = repairer.repair_batch(items)
print(repairer.format_report(report))
```
