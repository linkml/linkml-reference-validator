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
- **REFERENCE_ID** (required) - Reference ID (e.g., PMID:12345678)

### Options

- `--cache-dir PATH` - Directory for caching references (default: `references_cache`)
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

- **REFERENCE_ID** (required) - Reference ID (e.g., PMID:12345678)

### Options

- `--cache-dir PATH, -c PATH` - Directory for caching references (default: `references_cache`)
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
- Fetches abstract and metadata

### PubMed Central (PMC)

```
PMC:3458566
PMC:7654321
```

- Numeric identifier only
- Fetches full-text when available

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
