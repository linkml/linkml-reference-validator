# linkml-reference-validator

[![Tests](https://img.shields.io/badge/tests-91%20passing-brightgreen)]()
[![Coverage](https://img.shields.io/badge/coverage-86%25-green)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()

Validate that supporting text quotes in your data actually appear in their cited references.

This tool fetches scientific publications (currently PubMed/PMC) and verifies that quoted text (`supporting_text`) can be found in the referenced document using deterministic substring matching.

---

## Quick Start

### Installation

```bash
# Using uv (recommended)
uv pip install linkml-reference-validator

# Using pip
pip install linkml-reference-validator
```

### Basic Usage

```bash
# Validate a single quote against a reference
linkml-reference-validator validate text \
  "protein functions in cell cycle regulation" \
  PMID:12345678

# Validate a data file using LinkML validation
linkml-validate -s schema.yaml data.yaml \
  --validate-plugins linkml_reference_validator.plugins.ReferenceValidationPlugin
```

---

## Why Use This Tool?

Scientific data often includes claims supported by quotes from publications. But how do you know the quotes are accurate?

**Before:**
```yaml
gene_function:
  gene: TP53
  function: "regulates cell cycle"
  evidence:
    reference: PMID:12345678
    supporting_text: "TP53 is critical for cell cycle regulation"  # Is this really in the paper?
```

**After validation:**
```bash
$ linkml-reference-validator validate text \
    "TP53 is critical for cell cycle regulation" \
    PMID:12345678

✓ Valid: True
✓ Supporting text validated successfully in PMID:12345678
```

---

## CLI Commands

> **Note:** The CLI was restructured in v1.x to use nested commands (`validate text`, `validate data`, `cache reference`). The old hyphenated commands (`validate-text`, `validate-data`, `cache-reference`) still work for backward compatibility but are deprecated.

### 1. `validate text` - Quick Single Quote Validation

Validate a single quote against a reference without needing a schema.

```bash
linkml-reference-validator validate text <TEXT> <REFERENCE_ID> [OPTIONS]
```

**Example:**
```bash
# Basic validation
linkml-reference-validator validate text \
  "protein functions in cell cycle regulation" \
  PMID:12345678

# With editorial notes (ignored in matching)
linkml-reference-validator validate text \
  "protein [X] functions in cell cycle regulation" \
  PMID:12345678

# Multi-part quote with omitted text
linkml-reference-validator validate text \
  "protein functions ... cell cycle regulation" \
  PMID:12345678
```

**Options:**
- `--cache-dir PATH` - Directory for caching references (default: `references_cache`)
- `--verbose` - Show detailed validation information
- `--help` - Show help message

**Exit Codes:**
- `0` - Validation successful
- `1` - Validation failed

---

### 2. `validate data` - Full Data File Validation

Validate an entire data file using a LinkML schema.

```bash
linkml-reference-validator validate data <DATA_FILE> --schema <SCHEMA> [OPTIONS]
```

**Example:**

**Schema** (`gene_schema.yaml`):
```yaml
id: https://example.org/genes
name: gene-schema

classes:
  GeneFunction:
    attributes:
      gene:
        range: string
      function:
        range: string
      evidence:
        range: Evidence

  Evidence:
    attributes:
      reference:
        range: Reference
        implements:
          - linkml:authoritative_reference  # Marks this as a reference field
      supporting_text:
        range: string
        implements:
          - linkml:excerpt  # Marks this as text to validate

  Reference:
    attributes:
      id:
        identifier: true
        range: string
      title:
        range: string
```

**Data** (`gene_data.yaml`):
```yaml
gene: TP53
function: "regulates cell cycle"
evidence:
  reference:
    id: PMID:12345678
    title: "TP53 in cell cycle control"
  supporting_text: "TP53 protein functions in cell cycle regulation"
```

**Validation:**
```bash
linkml-reference-validator validate data \
  gene_data.yaml \
  --schema gene_schema.yaml

# Output:
Validating gene_data.yaml against schema gene_schema.yaml
Cache directory: references_cache

✓ All validations passed!
```

**Options:**
- `--schema PATH` (required) - Path to LinkML schema
- `--target-class CLASS` - Specific class to validate
- `--cache-dir PATH` - Directory for caching references
- `--verbose` - Show detailed output
- `--help` - Show help message

---

### 3. `repair` - Automated Repair of Validation Errors

Automatically fix or flag supporting text validation errors based on confidence thresholds.

```bash
# Repair a single quote
linkml-reference-validator repair text <TEXT> <REFERENCE_ID> [OPTIONS]

# Repair a data file (dry run by default)
linkml-reference-validator repair data <DATA_FILE> --schema <SCHEMA> [OPTIONS]
```

**Example - Single Quote:**
```bash
# Try to repair a quote with ASCII subscript
linkml-reference-validator repair text "CO2 levels were measured" PMID:12345678

# Output:
# ✓ Repaired successfully
#   Original: CO2 levels were measured
#   Repaired: CO₂ levels were measured
#   Action: CHARACTER_NORMALIZATION
#   Confidence: HIGH
```

**Example - Data File:**
```bash
# Dry run - show what would be changed
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml \
  --dry-run

# Apply auto-fixes (creates backup)
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml \
  --no-dry-run

# Custom output file
linkml-reference-validator repair data disease.yaml \
  --schema schema.yaml \
  --no-dry-run \
  --output repaired.yaml
```

**Repair Report Output:**
```
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
    Snippet: 'Fabricated text that...'

------------------------------------------------------------
Summary:
  Total items: 5
  Already valid: 2
  Auto-fixes: 1
  Suggestions: 1
  Removals: 1
  Unverifiable: 0
```

**Repair Strategies:**

| Strategy | Confidence | Description |
|----------|------------|-------------|
| Character Normalization | HIGH | Fix Unicode/symbol differences (CO2→CO₂, +/-→±) |
| Ellipsis Insertion | MEDIUM | Insert `...` between non-contiguous text parts |
| Fuzzy Correction | VARIES | Suggest closest matching text from reference |
| Removal | VERY_LOW | Flag fabricated/not-found text for manual removal |

**Options:**
- `--dry-run / --no-dry-run` - Show changes without applying (default: dry-run)
- `--auto-fix-threshold FLOAT` - Minimum similarity for auto-fixes (default: 0.95)
- `--output PATH` - Output file path (default: overwrite with backup)
- `--config PATH` - Path to repair configuration file
- `--cache-dir PATH` - Directory for caching references
- `--verbose` - Show detailed output

---

### 4. `cache reference` - Pre-cache References

Download and cache references for offline use.

```bash
linkml-reference-validator cache reference <REFERENCE_ID> [OPTIONS]
```

**Example:**
```bash
# Cache a single reference
linkml-reference-validator cache reference PMID:12345678

# Output:
Fetching PMID:12345678...
✓ Successfully cached PMID:12345678
  Title: TP53 in cell cycle control
  Authors: Smith J, Doe A, Johnson K
  Content type: full_text_xml
  Content length: 45231 characters
```

**Use Cases:**
- Pre-fetch references before validation
- Build offline reference library
- Verify reference availability

---

## Integration with `linkml-validate`

The recommended way to use this tool is as a **LinkML validation plugin** with the standard `linkml-validate` command.

### Setup

**1. Install both packages:**
```bash
uv pip install linkml linkml-reference-validator
```

**2. Create your schema with interface markers:**
```yaml
# my_schema.yaml
id: https://example.org/my-schema
name: my-schema

prefixes:
  linkml: https://w3id.org/linkml/

classes:
  Evidence:
    attributes:
      reference:
        range: Reference
        implements:
          - linkml:authoritative_reference  # <-- This marks it as a reference
      supporting_text:
        range: string
        implements:
          - linkml:excerpt  # <-- This marks it as text to validate
```

**3. Validate using linkml-validate:**
```bash
linkml-validate \
  --schema my_schema.yaml \
  --validate-plugins linkml_reference_validator.plugins.ReferenceValidationPlugin \
  my_data.yaml
```

### Why Use the Plugin?

✅ **Integrated validation** - Combines schema validation + reference validation in one command
✅ **Standard LinkML workflow** - Uses familiar LinkML tools
✅ **Flexible schema design** - Works with any schema using the interface pattern
✅ **Rich error reporting** - Shows exactly where validation fails in your data

---

## Supported Reference Formats

### Currently Supported

#### PubMed IDs (PMID)
```yaml
reference:
  id: PMID:12345678
  supporting_text: "protein functions in cells"
```

**Fetches:**
- Abstract (always)
- Full text from PMC (when available)
- Metadata (title, authors, journal, year, DOI)

**ID Formats:**
- `PMID:12345678`
- `12345678` (assumes PMID)

### Coming Soon

- **DOI** - `DOI:10.1038/nature12345`
- **URLs** - Web pages and online documents

---

## Schema Requirements

For the validator to work, your LinkML schema must:

### 1. Mark Reference Fields

Use `implements: [linkml:authoritative_reference]` on slots that contain references:

```yaml
classes:
  Evidence:
    attributes:
      reference:           # Can be nested object
        range: Reference
        implements:
          - linkml:authoritative_reference
```

**OR** use a flat structure:

```yaml
classes:
  Evidence:
    attributes:
      reference_id:        # Can be flat string
        range: string
        implements:
          - linkml:authoritative_reference
```

### 2. Mark Excerpt Fields

Use `implements: [linkml:excerpt]` on slots containing quoted text:

```yaml
classes:
  Evidence:
    attributes:
      supporting_text:     # The quote to validate
        range: string
        implements:
          - linkml:excerpt
```

### 3. Define Reference Structure

If using nested references, define the Reference class:

```yaml
classes:
  Reference:
    attributes:
      id:
        identifier: true
        range: string
      title:              # Optional: validates if provided
        range: string
```

---

## Data Formats

### Nested Reference (Recommended)

```yaml
evidence:
  reference:
    id: PMID:12345678
    title: "Study of Protein X"
  supporting_text: "protein functions in cell cycle regulation"
```

### Flat Reference ID

```yaml
evidence:
  reference_id: PMID:12345678
  supporting_text: "protein functions in cell cycle regulation"
```

### Multiple Evidence Items

```yaml
statement:
  text: "Protein X has multiple functions"
  evidence:
    - reference:
        id: PMID:11111111
      supporting_text: "protein functions in cell cycle"
    - reference:
        id: PMID:22222222
      supporting_text: "protein regulates DNA repair"
```

---

## Text Matching Syntax

### Editorial Notes `[...]`

Use square brackets for editorial insertions that should be ignored during matching:

```yaml
supporting_text: "protein [X] functions in cell cycle regulation"
# Matches: "protein functions in cell cycle regulation"
# Ignores: "X"
```

**Use cases:**
- `[sic]` - Original spelling
- `[emphasis added]` - Added emphasis
- `[gene name]` - Clarifications
- `[...]` - Omitted content markers

### Omitted Text `...`

Use ellipsis for gaps in quoted text:

```yaml
supporting_text: "protein functions ... in cell cycle regulation"
# Matches both parts independently:
# - "protein functions"
# - "in cell cycle regulation"
```

**Requirements:**
- Both parts must appear in the reference (order independent)
- Each part must be a substring match after normalization

### Text Normalization

Before matching, text is normalized:
- Greek letters spelled out (α→alpha, β→beta, etc.)
- Lowercased
- Punctuation removed
- Extra whitespace collapsed

**Examples:**
```
"T-Cell Receptor"     → "t cell receptor"
"TP53 (p53) protein"  → "tp53 p53 protein"
"α-catenin"          → "alpha catenin"
"β-actin"            → "beta actin"
"γ-tubulin"          → "gamma tubulin"
```

**Greek Letter Support:**

All Greek letters (both uppercase and lowercase) are converted to their spelled-out English equivalents. This ensures:
- **Bidirectional matching**: "α-catenin" in a query matches "alpha-catenin" in the reference, and vice versa
- **Preserved distinctions**: "α-catenin" and "β-catenin" remain distinct (not collapsed to just "catenin")
- **Consistent behavior**: Works with any Greek letter commonly used in biomedical nomenclature

---

## Caching

References are automatically cached to disk to:
- Speed up repeated validations
- Reduce API calls to PubMed
- Enable offline validation

### Cache Structure

```
references_cache/
├── PMID_12345678.md
├── PMID_98765432.md
└── PMC_7654321.md
```

### Cache File Format

Cache files are stored as Markdown with YAML frontmatter for easy readability and compatibility:

```markdown
---
reference_id: PMID:12345678
title: TP53 in cell cycle control
authors:
- Smith J
- Doe A
- Johnson K
journal: Nature
year: '2024'
doi: 10.1038/nature12345
content_type: full_text_xml
---

# TP53 in cell cycle control
**Authors:** Smith J, Doe A, Johnson K
**Journal:** Nature (2024)
**DOI:** [10.1038/nature12345](https://doi.org/10.1038/nature12345)

## Content

[Full text content follows...]
```

**Note:** The validator still supports reading legacy `.txt` format cache files for backward compatibility.

### Cache Management

```bash
# Use custom cache directory
linkml-reference-validator validate text \
  "quote" PMID:123 \
  --cache-dir /path/to/cache

# Pre-cache references
linkml-reference-validator cache reference PMID:12345678

# Force re-fetch (bypass cache)
linkml-reference-validator cache reference PMID:12345678 --force
```

---

## Examples

### Example 1: Simple Gene Function Validation

**Schema** (`gene.yaml`):
```yaml
id: https://example.org/genes
name: gene-schema

classes:
  GeneFunctionStatement:
    tree_root: true
    attributes:
      gene_symbol:
        range: string
      function_description:
        range: string
      evidence:
        range: Evidence

  Evidence:
    attributes:
      reference:
        range: Reference
        implements:
          - linkml:authoritative_reference
      supporting_text:
        range: string
        implements:
          - linkml:excerpt

  Reference:
    attributes:
      id:
        identifier: true
```

**Data** (`tp53.yaml`):
```yaml
gene_symbol: TP53
function_description: "tumor suppressor"
evidence:
  reference:
    id: PMID:12345678
  supporting_text: "TP53 functions as a tumor suppressor"
```

**Validation:**
```bash
linkml-validate \
  --schema gene.yaml \
  --validate-plugins linkml_reference_validator.plugins.ReferenceValidationPlugin \
  tp53.yaml
```

---

### Example 2: Quick Text Check

```bash
# Check if a quote is in a paper
linkml-reference-validator validate text \
  "protein kinase activity regulates cell proliferation" \
  PMID:12345678

# With editorial note
linkml-reference-validator validate text \
  "protein kinase [PKA] activity regulates cell proliferation" \
  PMID:12345678

# Multi-part quote
linkml-reference-validator validate text \
  "protein kinase activity ... regulates cell proliferation" \
  PMID:12345678
```

---

### Example 3: Batch Validation with Multiple References

**Data** (`gene_annotations.yaml`):
```yaml
- gene_symbol: BRCA1
  annotations:
    - function: "DNA repair"
      evidence:
        reference:
          id: PMID:11111111
        supporting_text: "BRCA1 plays a critical role in DNA repair"
    - function: "tumor suppressor"
      evidence:
        reference:
          id: PMID:22222222
        supporting_text: "BRCA1 functions as a tumor suppressor"

- gene_symbol: TP53
  annotations:
    - function: "cell cycle regulation"
      evidence:
        reference:
          id: PMID:33333333
        supporting_text: "TP53 regulates cell cycle checkpoints"
```

**Validation:**
```bash
linkml-reference-validator validate data \
  gene_annotations.yaml \
  --schema gene_schema.yaml \
  --verbose

# Output shows validation for each reference:
# ✓ PMID:11111111 - "BRCA1 plays a critical role in DNA repair"
# ✓ PMID:22222222 - "BRCA1 functions as a tumor suppressor"
# ✓ PMID:33333333 - "TP53 regulates cell cycle checkpoints"
```

---

## Validation Rules

### What Passes

✅ **Exact substring match** (after normalization)
```yaml
supporting_text: "protein functions in cells"
reference_content: "The protein functions in cells during mitosis."
# ✓ PASS - exact substring found
```

✅ **Multi-part match**
```yaml
supporting_text: "protein functions ... during mitosis"
reference_content: "The protein functions in cells during mitosis."
# ✓ PASS - both parts found
```

✅ **Editorial notes ignored**
```yaml
supporting_text: "protein [X] functions"
reference_content: "The protein functions in cells."
# ✓ PASS - [X] ignored in matching
```

✅ **Case and punctuation normalized**
```yaml
supporting_text: "T-Cell Receptor"
reference_content: "The t cell receptor binds antigens."
# ✓ PASS - normalized to "t cell receptor"
```

### What Fails

❌ **Text not in reference**
```yaml
supporting_text: "protein inhibits apoptosis"
reference_content: "The protein functions in cells."
# ✗ FAIL - "inhibits apoptosis" not found
```

❌ **Partial multi-part match**
```yaml
supporting_text: "protein functions ... inhibits apoptosis"
reference_content: "The protein functions in cells."
# ✗ FAIL - second part not found
```

❌ **Reference not accessible**
```yaml
supporting_text: "any quote"
reference_id: PMID:99999999
# ✗ FAIL - reference doesn't exist or can't be fetched
```

❌ **Title mismatch** (when title provided)
```yaml
reference:
  id: PMID:12345678
  title: "Wrong Title"
supporting_text: "correct quote"
# ✗ FAIL - title doesn't match fetched reference
```

---

## Configuration

### Cache Directory

Default: `references_cache/` in current directory

```bash
# Custom cache location
export REFERENCE_CACHE_DIR=/path/to/cache
linkml-reference-validator validate text "quote" PMID:123

# Or use CLI option
linkml-reference-validator validate text "quote" PMID:123 \
  --cache-dir /path/to/cache
```

### NCBI API Settings

The tool respects NCBI API rate limits (3 requests/second without API key).

**Optional: Set email for NCBI Entrez (recommended):**
```bash
export NCBI_EMAIL="your.email@example.com"
```

**Optional: Use NCBI API key for higher rate limits:**
```bash
export NCBI_API_KEY="your_api_key_here"
```

---

## Troubleshooting

### Common Issues

#### "Could not fetch reference: PMID:12345678"

**Causes:**
- PMID doesn't exist
- Network connectivity issues
- NCBI API temporarily unavailable

**Solutions:**
```bash
# Verify PMID exists on PubMed
# Check network connection
# Try again later (NCBI may be down)
```

#### "No content available for reference"

**Causes:**
- Abstract not available
- Article behind paywall (no PMC access)
- Retracted article

**Solutions:**
```bash
# Check if article has abstract on PubMed
# Look for PMC full text availability
# Try a different reference
```

#### "Supporting text not found"

**Causes:**
- Quote is incorrect or paraphrased
- Text only in figures/tables (not extracted)
- Text uses different terminology
- Unicode characters normalized out

**Solutions:**
```bash
# Verify exact quote from PDF/HTML
# Try shorter, more specific quote
# Check if text is in figure caption
# Use editorial notes for differences: "protein [X] functions"
```

#### "Query is empty after removing brackets"

**Cause:**
- Entire supporting_text is in brackets: `"[editorial note]"`

**Solution:**
```yaml
# Include actual quote text
supporting_text: "protein functions [in cells]"
# Not just: "[editorial note]"
```

---

## Performance

### Benchmarks

- **First validation:** ~2-3 seconds (includes fetch + cache)
- **Cached validation:** ~10-50ms
- **Batch validation:** ~50ms per reference (cached)

### Tips for Speed

1. **Pre-cache references:**
   ```bash
   # Cache all references before validation
   for pmid in PMID:111 PMID:222 PMID:333; do
     linkml-reference-validator cache reference $pmid
   done
   ```

2. **Reuse cache directory:**
   ```bash
   # Share cache across projects
   export REFERENCE_CACHE_DIR=~/.reference_cache
   ```

3. **Use verbose mode to see what's slow:**
   ```bash
   linkml-reference-validator validate data data.yaml \
     --schema schema.yaml \
     --verbose
   ```

---

## Development

### Installation for Development

```bash
# Clone repository
git clone https://github.com/linkml/linkml-reference-validator
cd linkml-reference-validator

# Install with dev dependencies
uv sync --group dev

# Run tests
just test

# Run specific test
uv run pytest tests/test_cli.py::test_validate_text_command_success
```

### Project Structure

```
linkml-reference-validator/
├── src/linkml_reference_validator/
│   ├── cli.py                    # CLI commands
│   ├── models.py                 # Data models
│   ├── validation/
│   │   └── supporting_text_validator.py  # Core validation logic
│   ├── etl/
│   │   └── reference_fetcher.py  # Reference fetching
│   └── plugins/
│       └── reference_validation_plugin.py  # LinkML plugin
├── tests/
│   ├── fixtures/                 # Test reference files
│   ├── test_cli.py              # CLI tests
│   ├── test_e2e_integration.py  # End-to-end tests
│   └── ...
├── justfile                      # Development commands
└── pyproject.toml               # Project configuration
```

### Running Tests

```bash
# All tests
just test

# Just pytest
just pytest

# With coverage
uv run pytest --cov=src/linkml_reference_validator

# Specific test file
uv run pytest tests/test_cli.py

# Doctests
just doctest
```

---

## API Usage (Python)

While the CLI is recommended, you can also use the Python API:

```python
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator
)
from linkml_reference_validator.models import ReferenceValidationConfig

# Create validator
config = ReferenceValidationConfig(cache_dir="my_cache")
validator = SupportingTextValidator(config)

# Validate text
result = validator.validate(
    supporting_text="protein functions in cell cycle regulation",
    reference_id="PMID:12345678",
)

print(result.is_valid)  # True/False
print(result.message)   # Validation message
```

---

## Limitations

### Current Limitations

1. **PubMed only** - Currently only supports PMID references (DOI and URLs coming soon)
2. **Text extraction** - Only extracts text from abstracts and main article text (not figures, tables, or supplementary materials)
3. **Unicode normalization** - Greek letters and special symbols are removed during normalization (e.g., α → a, β → b)
4. **No fuzzy matching** - Uses deterministic substring matching only (intentional design choice)
5. **English-centric** - Text normalization assumes English text

### Known Edge Cases

- **Greek letters:** "α-catenin" matches "a catenin" or "catenin"
- **Chemical formulas:** "H₂O" becomes "h o" or "h2o"
- **Hyphens:** "T-cell" matches "t cell"
- **Abbreviations:** Must match exactly as they appear (normalized)

---

## Comparison to Other Tools

### vs. Manual Verification

| Manual | linkml-reference-validator |
|--------|----------------------------|
| ❌ Time consuming | ✅ Automated |
| ❌ Error prone | ✅ Consistent |
| ❌ Not scalable | ✅ Validates 100s of quotes |
| ❌ Not reproducible | ✅ Cached, versioned |

### vs. Fuzzy Matching Tools

linkml-reference-validator uses **deterministic substring matching**, not fuzzy matching:

✅ **Predictable** - Same input always gives same result
✅ **Explainable** - Easy to understand why validation passed/failed
✅ **No false positives** - Won't accept paraphrased text
✅ **Fast** - No complex similarity calculations

---

## Contributing

Contributions welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

### Priority Areas

- [ ] DOI support
- [ ] URL/webpage support
- [ ] Better Unicode handling
- [ ] Performance improvements for large batches
- [ ] More comprehensive error messages

---

## Citation

If you use this tool in your research, please cite:

```bibtex
@software{linkml_reference_validator,
  title = {linkml-reference-validator: Validation of supporting text from references},
  author = {Mungall, Chris},
  year = {2024},
  url = {https://github.com/linkml/linkml-reference-validator}
}
```

---

## License

Apache 2.0 - see [LICENSE](LICENSE)

---

## Support

- **Issues:** [GitHub Issues](https://github.com/linkml/linkml-reference-validator/issues)
- **Discussions:** [GitHub Discussions](https://github.com/linkml/linkml-reference-validator/discussions)
- **Documentation:** [Full Documentation](https://linkml.github.io/linkml-reference-validator)

---

## Related Projects

- [LinkML](https://linkml.io/) - Modeling language for linked data
- [linkml-validator](https://github.com/linkml/linkml) - Core LinkML validation
- [ai-gene-reviews](https://github.com/monarch-initiative/ai-gene-reviews) - Inspiration for this project
