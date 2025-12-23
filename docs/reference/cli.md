# CLI Reference

Complete command-line interface documentation.

## Main Command

```bash
linkml-reference-validator [OPTIONS] COMMAND [ARGS]...
```

### Options

- `--help` - Show help message and exit

### Commands

- `validate` - Validate supporting text against references
- `repair` - Repair supporting text validation errors
- `cache` - Manage reference cache

## validate

Validate supporting text against references.

```bash
linkml-reference-validator validate COMMAND [ARGS]...
```

### Subcommands

- `text` - Validate a single text quote
- `data` - Validate supporting text in data files

---

## validate text

Validate a single supporting text quote against a reference.

### Usage

```bash
linkml-reference-validator validate text [OPTIONS] TEXT REFERENCE_ID
```

### Arguments

- **TEXT** (required) - The supporting text to validate
- **REFERENCE_ID** (required) - Reference ID (e.g., PMID:12345678 or DOI:10.1234/example)

### Options

- `--cache-dir PATH` - Directory for caching references (default: `references_cache`)
- `--config PATH` - Path to validation configuration file (.yaml)
- `--verbose, -v` - Verbose output with detailed logging
- `--help` - Show help message

### Examples

**Basic validation:**
```bash
linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting" \
  PMID:16888623
```

**With custom cache directory:**
```bash
linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting" \
  PMID:16888623 \
  --cache-dir /path/to/cache
```

**With verbose output:**
```bash
linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting" \
  PMID:16888623 \
  --verbose
```

**With editorial notes:**
```bash
linkml-reference-validator validate text \
  'MUC1 [mucin 1] oncoprotein blocks nuclear targeting' \
  PMID:16888623
```

**With ellipsis:**
```bash
linkml-reference-validator validate text \
  "MUC1 oncoprotein ... nuclear targeting" \
  PMID:16888623
```

**With DOI:**
```bash
linkml-reference-validator validate text \
  "Nanometre-scale thermometry" \
  DOI:10.1038/nature12373
```

### Exit Codes

- `0` - Validation successful
- `1` - Validation failed

### Output Format

```
Validating text against PMID:16888623...
  Text: MUC1 oncoprotein blocks nuclear targeting

Result:
  Valid: True
  Message: Supporting text validated successfully in PMID:16888623
  Matched text: MUC1 oncoprotein blocks nuclear targeting...
```

---

## validate data

Validate supporting text in data files against their cited references.

### Usage

```bash
linkml-reference-validator validate data [OPTIONS] DATA_FILE
```

### Arguments

- **DATA_FILE** (required) - Path to data file (YAML/JSON)

### Options

- `--schema PATH, -s PATH` (required) - Path to LinkML schema file
- `--target-class TEXT, -t TEXT` - Target class to validate (optional)
- `--cache-dir PATH, -c PATH` - Directory for caching references (default: `references_cache`)
- `--config PATH` - Path to validation configuration file (.yaml)
- `--verbose, -v` - Verbose output with detailed logging
- `--help` - Show help message

### Examples

**Basic validation:**
```bash
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml
```

**With target class:**
```bash
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml \
  --target-class Statement
```

**With custom cache:**
```bash
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml \
  --cache-dir /path/to/cache
```

**With verbose output:**
```bash
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml \
  --verbose
```

### Exit Codes

- `0` - All validations passed
- `1` - One or more validations failed

### Output Format

**Success:**
```
Validating data.yaml against schema schema.yaml
Cache directory: references_cache

Validation Summary:
  Total checks: 3
  All validations passed!
```

**Failure:**
```
Validating data.yaml against schema schema.yaml
Cache directory: references_cache

Validation Issues (2):
  [ERROR] Text part not found as substring: 'MUC1 activates JAK-STAT'
    Location: Statement

Validation Summary:
  Total checks: 3
  Issues found: 2
```

---

## repair

Repair supporting text validation errors.

```bash
linkml-reference-validator repair COMMAND [ARGS]...
```

### Subcommands

- `text` - Repair a single text quote
- `data` - Repair supporting text in data files

---

## repair text

Attempt to repair a single supporting text quote.

### Usage

```bash
linkml-reference-validator repair text [OPTIONS] TEXT REFERENCE_ID
```

### Arguments

- **TEXT** (required) - The supporting text to repair
- **REFERENCE_ID** (required) - Reference ID (e.g., PMID:12345678 or DOI:10.1234/example)

### Options

- `--cache-dir PATH, -c PATH` - Directory for caching references
- `--config PATH` - Path to configuration file (.yaml)
- `--verbose, -v` - Verbose output with detailed logging
- `--auto-fix-threshold FLOAT, -a FLOAT` - Minimum similarity for auto-fixes (default: 0.95)
- `--help` - Show help message

### Examples

**Repair character normalization:**
```bash
linkml-reference-validator repair text \
  "CO2 levels were measured" \
  PMID:12345678
```

**With verbose output:**
```bash
linkml-reference-validator repair text \
  "protein functions in cells" \
  PMID:12345678 \
  --verbose
```

### Exit Codes

- `0` - Repair successful or already valid
- `1` - Could not repair

### Output Format

**Successful repair:**
```
Attempting repair for PMID:12345678...
  Text: CO2 levels were measured

Result:
  ✓ Repaired successfully
    Original: CO2 levels were measured
    Repaired: CO₂ levels were measured
    Action: CHARACTER_NORMALIZATION (Character normalization fix)
    Confidence: HIGH
```

**Already valid:**
```
Result:
  ✓ Text already valid - no repair needed
```

**Could not repair:**
```
Result:
  ✗ Could not repair: Flagged for removal - text not found in reference
    Suggestion: REMOVAL
    Confidence: VERY_LOW (12%)
```

---

## repair data

Repair supporting text in data files.

### Usage

```bash
linkml-reference-validator repair data [OPTIONS] DATA_FILE
```

### Arguments

- **DATA_FILE** (required) - Path to data file (YAML)

### Options

- `--schema PATH, -s PATH` (required) - Path to LinkML schema file
- `--target-class TEXT, -t TEXT` - Target class to validate
- `--dry-run / --no-dry-run, -n / -N` - Show changes without applying (default: dry-run)
- `--auto-fix-threshold FLOAT, -a FLOAT` - Minimum similarity for auto-fixes (default: 0.95)
- `--output PATH, -o PATH` - Output file path (default: overwrite with backup)
- `--config PATH` - Path to configuration file (.yaml)
- `--cache-dir PATH, -c PATH` - Directory for caching references
- `--verbose, -v` - Verbose output with detailed logging
- `--help` - Show help message

### Examples

**Dry run (default):**
```bash
linkml-reference-validator repair data \
  disease.yaml \
  --schema schema.yaml \
  --dry-run
```

**Apply repairs:**
```bash
linkml-reference-validator repair data \
  disease.yaml \
  --schema schema.yaml \
  --no-dry-run
```

**Output to new file:**
```bash
linkml-reference-validator repair data \
  disease.yaml \
  --schema schema.yaml \
  --no-dry-run \
  --output repaired.yaml
```

**With configuration file:**
```bash
linkml-reference-validator repair data \
  disease.yaml \
  --schema schema.yaml \
  --config .linkml-reference-validator.yaml
```

**Custom threshold:**
```bash
linkml-reference-validator repair data \
  disease.yaml \
  --schema schema.yaml \
  --auto-fix-threshold 0.98 \
  --no-dry-run
```

### Exit Codes

- `0` - Repair completed (may have suggestions)
- `1` - Repair completed but has removals or unverifiable items

### Output Format

```
[DRY RUN] Repairing disease.yaml
  Schema: schema.yaml
  Auto-fix threshold: 0.95
  Cache directory: references_cache

Found 5 evidence item(s) to process

============================================================
Repair Report
============================================================

HIGH CONFIDENCE FIXES (auto-applicable):
  PMID:12345678 at evidence[0]:
    Character normalization fix
    'CO2 levels...' → 'CO₂ levels...'

SUGGESTED FIXES (review recommended):
  PMID:23456789 at evidence[1]:
    Inserted ellipsis between non-contiguous parts

RECOMMENDED REMOVALS (low confidence):
  PMID:34567890 at evidence[2]:
    Similarity: 8%
    Snippet: 'Fabricated text...'

------------------------------------------------------------
Summary:
  Total items: 5
  Already valid: 2
  Auto-fixes: 1
  Suggestions: 1
  Removals: 1
  Unverifiable: 0
```

---

## Configuration File

Create `.linkml-reference-validator.yaml` for project-specific settings. Use
the `validation` section for reference fetching behavior and `repair` for
auto-fix settings.

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

  # References to skip
  skip_references:
    - "PMID:12345678"

  # References trusted despite low similarity
  trusted_low_similarity:
    - "PMID:98765432"
```

---

## cache

Manage reference cache.

```bash
linkml-reference-validator cache COMMAND [ARGS]...
```

### Subcommands

- `reference` - Cache a reference for offline use

---

## cache reference

Pre-fetch and cache a reference for offline use.

### Usage

```bash
linkml-reference-validator cache reference [OPTIONS] REFERENCE_ID
```

### Arguments

- **REFERENCE_ID** (required) - Reference ID (e.g., PMID:12345678 or DOI:10.1234/example)

### Options

- `--cache-dir PATH, -c PATH` - Directory for caching references (default: `references_cache`)
- `--config PATH` - Path to validation configuration file (.yaml)
- `--force, -f` - Force re-fetch even if cached
- `--verbose, -v` - Verbose output with detailed logging
- `--help` - Show help message

### Examples

**Cache a reference:**
```bash
linkml-reference-validator cache reference PMID:16888623
```

**Force refresh:**
```bash
linkml-reference-validator cache reference \
  PMID:16888623 \
  --force
```

**Custom cache directory:**
```bash
linkml-reference-validator cache reference \
  PMID:16888623 \
  --cache-dir /path/to/cache
```

**Cache a DOI:**
```bash
linkml-reference-validator cache reference DOI:10.1038/nature12373
```

### Output Format

```
Fetching PMID:16888623...
Successfully cached PMID:16888623
  Title: MUC1 oncoprotein blocks nuclear targeting...
  Authors: Raina D, Ahmad R, Joshi MD
  Content type: abstract_only
  Content length: 1523 characters
```

---

## Reference ID Formats

### PubMed (PMID)

```
PMID:12345678
PMID:9876543
```

- Numeric identifier only
- Fetches abstract and metadata from NCBI

### PubMed Central (PMC)

```
PMC:3458566
PMC:7654321
```

- Numeric identifier only
- Fetches full-text when available

### DOI (Digital Object Identifier)

```
DOI:10.1038/nature12373
DOI:10.1126/science.1234567
```

- Standard DOI format (10.prefix/suffix)
- Fetches metadata from Crossref API
- Abstract availability depends on publisher

---

## Environment Variables

### LINKML_REFERENCE_VALIDATOR_CACHE_DIR

Override default cache directory:

```bash
export LINKML_REFERENCE_VALIDATOR_CACHE_DIR=/custom/cache
linkml-reference-validator validate text "..." PMID:12345678
```

### NCBI_API_KEY

Set NCBI API key for higher rate limits:

```bash
export NCBI_API_KEY=your_api_key_here
linkml-reference-validator validate text "..." PMID:12345678
```

Request an API key: https://www.ncbi.nlm.nih.gov/account/settings/

---

## Shell Integration

### Exit Code Usage

```bash
if linkml-reference-validator validate text \
    "MUC1 oncoprotein blocks nuclear targeting" \
    PMID:16888623 > /dev/null 2>&1; then
  echo "✓ Valid"
else
  echo "✗ Invalid"
fi
```

### Batch Processing

```bash
for pmid in PMID:111 PMID:222 PMID:333; do
  echo "Validating $pmid..."
  linkml-reference-validator validate text \
    "some text" \
    "$pmid"
done
```

### Piping Output

```bash
# Save output to file
linkml-reference-validator validate text \
  "..." PMID:12345678 \
  > validation_result.txt

# Grep for specific info
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml \
  | grep "Valid:"
```

---

## Backward Compatibility

Old hyphenated commands still work but are deprecated:

```bash
# Old (deprecated but working)
linkml-reference-validator validate-text "..." PMID:123
linkml-reference-validator validate-data data.yaml --schema schema.yaml
linkml-reference-validator cache-reference PMID:123

# New (preferred)
linkml-reference-validator validate text "..." PMID:123
linkml-reference-validator validate data data.yaml --schema schema.yaml
linkml-reference-validator cache reference PMID:123
```

The old commands are hidden from `--help` but continue to function.

---

## See Also

- [Quickstart](../quickstart.md) - Get started quickly
- [Tutorial 1](../notebooks/01_getting_started.ipynb) - CLI examples
- [Python API Reference](python-api.md) - Programmatic usage
