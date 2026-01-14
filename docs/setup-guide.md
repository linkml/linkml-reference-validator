# Complete Setup Guide

This guide walks you through setting up linkml-reference-validator from scratch, with complete examples for different use cases.

## Prerequisites

### System Requirements

- **Python 3.10 or higher** - Check with `python --version`
- **pip or uv** - Package installer (uv is faster and recommended)
- **Internet connection** - For fetching references from PubMed, Crossref, etc.

### Optional but Recommended

- **NCBI API Key** - For higher rate limits when fetching PubMed articles
- **Git** - For version control of your data and schemas

## Installation

### Option 1: Using pip (Standard)

```bash
pip install linkml-reference-validator
```

Verify the installation:

```bash
linkml-reference-validator --version
```

### Option 2: Using uv (Recommended for Speed)

[uv](https://github.com/astral-sh/uv) is a fast Python package installer:

```bash
# Install uv first (if you don't have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install linkml-reference-validator
uv pip install linkml-reference-validator
```

Verify:

```bash
uv run linkml-reference-validator --version
```

### Option 3: Development Installation

If you want to contribute or modify the code:

```bash
# Clone the repository
git clone https://github.com/linkml/linkml-reference-validator.git
cd linkml-reference-validator

# Install with development dependencies
uv sync --group dev

# Run tests to verify
just test
```

## Initial Configuration

### 1. Set Up Your Workspace

Create a directory for your validation project:

```bash
mkdir my-validation-project
cd my-validation-project
```

### 2. Configure NCBI Access (Optional but Recommended)

To avoid rate limits when fetching PubMed articles:

1. **Get an NCBI API Key** (free):
   - Visit https://www.ncbi.nlm.nih.gov/account/
   - Sign up or log in
   - Go to Settings → API Key Management
   - Create a new API key

2. **Set environment variables**:

```bash
# Add to your ~/.bashrc, ~/.zshrc, or ~/.profile
export NCBI_EMAIL="your.email@example.com"
export NCBI_API_KEY="your_api_key_here"

# Or create a .env file in your project
echo 'NCBI_EMAIL=your.email@example.com' >> .env
echo 'NCBI_API_KEY=your_api_key_here' >> .env
```

3. **Test the configuration**:

```bash
linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting of c-Abl" \
  PMID:16888623
```

If successful, you should see:
```
Validating text against PMID:16888623...
  Text: MUC1 oncoprotein blocks nuclear targeting of c-Abl

Result:
  Valid: True
  Message: Supporting text validated successfully in PMID:16888623
```

### 3. Set Up Cache Directory

By default, references are cached in `references_cache/` in your current directory. To use a global cache:

```bash
# Create a global cache directory
mkdir -p ~/.cache/linkml-reference-validator

# Set environment variable
export REFERENCE_CACHE_DIR=~/.cache/linkml-reference-validator

# Or add to your shell profile
echo 'export REFERENCE_CACHE_DIR=~/.cache/linkml-reference-validator' >> ~/.bashrc
```

Benefits of a global cache:
- Share references across multiple projects
- Avoid re-downloading the same papers
- Faster validation when working on multiple datasets

## Quick Start Examples

### Example 1: Validate a Single Quote

The simplest use case - verify that a quote appears in a paper:

```bash
linkml-reference-validator validate text \
  "TP53 functions as a tumor suppressor" \
  PMID:12345678
```

**What happens:**
1. Fetches the reference from PubMed
2. Caches it locally in `references_cache/PMID_12345678.md`
3. Searches for the quote in the reference content
4. Returns validation result

### Example 2: Create Your First Schema

Create a schema file to define your data structure:

**schema.yaml:**
```yaml
id: https://example.org/gene-validation
name: gene-validation-schema

prefixes:
  linkml: https://w3id.org/linkml/

classes:
  GeneAnnotation:
    tree_root: true
    attributes:
      gene_symbol:
        required: true
        description: Gene symbol (e.g., TP53, BRCA1)

      function:
        required: true
        description: Functional description of the gene

      supporting_text:
        required: true
        description: Quote from the reference supporting this annotation
        slot_uri: linkml:excerpt

      reference_id:
        required: true
        description: PubMed ID or DOI of the reference
        slot_uri: linkml:authoritative_reference
```

**Key points:**
- `slot_uri: linkml:excerpt` marks the field containing quoted text
- `slot_uri: linkml:authoritative_reference` marks the reference identifier
- These special URIs tell the validator which fields to check

### Example 3: Create Your First Data File

Create a data file matching your schema:

**gene_data.yaml:**
```yaml
gene_symbol: TP53
function: Tumor suppressor that regulates cell cycle
supporting_text: TP53 functions as a tumor suppressor through regulation of cell cycle arrest
reference_id: PMID:12345678
```

### Example 4: Validate Your Data

```bash
linkml-reference-validator validate data \
  gene_data.yaml \
  --schema schema.yaml \
  --target-class GeneAnnotation
```

**Expected output (if valid):**
```
Validating gene_data.yaml against schema schema.yaml
Cache directory: references_cache

Validating 1 object(s) of type GeneAnnotation...
✓ All validations passed!
```

**Output if validation fails:**
```
Validating gene_data.yaml against schema schema.yaml
Cache directory: references_cache

Validating 1 object(s) of type GeneAnnotation...
✗ Validation failed for:
  Reference: PMID:12345678
  Supporting text: "TP53 functions as a tumor suppressor through regulation of cell cycle arrest"
  Error: Text not found in reference

1 validation(s) failed, 0 passed
```

## Real-World Example: Validating Gene Functions

Let's work through a complete real-world example: validating gene function annotations.

### Step 1: Project Setup

```bash
# Create project directory
mkdir gene-annotations
cd gene-annotations

# Create subdirectories
mkdir schemas
mkdir data
mkdir references_cache
```

### Step 2: Create the Schema

**schemas/gene_function_schema.yaml:**
```yaml
id: https://example.org/gene-functions
name: gene-functions

prefixes:
  linkml: https://w3id.org/linkml/

classes:
  GeneFunctionDataset:
    tree_root: true
    attributes:
      genes:
        multivalued: true
        range: GeneFunction

  GeneFunction:
    attributes:
      gene_symbol:
        identifier: true
        required: true
        description: Official gene symbol

      function_category:
        required: true
        description: Broad category of function
        range: FunctionCategory

      detailed_function:
        required: true
        description: Detailed description of function

      evidence:
        required: true
        range: Evidence
        description: Supporting evidence from literature

  Evidence:
    attributes:
      reference_id:
        required: true
        slot_uri: linkml:authoritative_reference
        description: PMID, DOI, or PMC identifier

      supporting_text:
        required: true
        slot_uri: linkml:excerpt
        description: Direct quote from the reference

      notes:
        description: Additional context or clarifications

enums:
  FunctionCategory:
    permissible_values:
      TUMOR_SUPPRESSOR:
        description: Prevents uncontrolled cell growth
      ONCOGENE:
        description: Promotes cell growth and division
      DNA_REPAIR:
        description: Repairs damaged DNA
      TRANSCRIPTION_FACTOR:
        description: Regulates gene expression
      CELL_CYCLE_REGULATOR:
        description: Controls cell cycle progression
```

### Step 3: Create Sample Data

**data/tp53_brca1.yaml:**
```yaml
genes:
  - gene_symbol: TP53
    function_category: TUMOR_SUPPRESSOR
    detailed_function: Regulates cell cycle arrest and apoptosis in response to DNA damage
    evidence:
      reference_id: PMID:16888623
      supporting_text: "MUC1 oncoprotein blocks nuclear targeting of c-Abl"
      notes: Example from actual paper

  - gene_symbol: BRCA1
    function_category: DNA_REPAIR
    detailed_function: Critical role in homologous recombination DNA repair
    evidence:
      reference_id: PMID:12345678
      supporting_text: "BRCA1 plays a critical role in DNA double-strand break repair through homologous recombination"
```

### Step 4: Validate

```bash
linkml-reference-validator validate data \
  data/tp53_brca1.yaml \
  --schema schemas/gene_function_schema.yaml \
  --target-class GeneFunctionDataset \
  --verbose
```

### Step 5: Handle Validation Errors

If validation fails, use the repair command:

```bash
# First, see what repairs are suggested (dry run)
linkml-reference-validator repair data \
  data/tp53_brca1.yaml \
  --schema schemas/gene_function_schema.yaml \
  --target-class GeneFunctionDataset \
  --dry-run

# Review the suggested repairs, then apply if appropriate
linkml-reference-validator repair data \
  data/tp53_brca1.yaml \
  --schema schemas/gene_function_schema.yaml \
  --target-class GeneFunctionDataset \
  --no-dry-run
```

## Advanced Configuration

### Project Configuration File

Create `.linkml-reference-validator.yaml` in your project root:

```yaml
# Validation settings
validation:
  # Cache directory (relative to config file or absolute)
  cache_dir: ./references_cache

  # Custom reference prefix mappings
  reference_prefix_map:
    geo: GEO
    NCBIGeo: GEO
    pubmed: PMID

  # Base directory for resolving file:// references
  reference_base_dir: ./references

# Repair settings
repair:
  # Confidence thresholds
  auto_fix_threshold: 0.95
  suggest_threshold: 0.80
  removal_threshold: 0.50

  # Character normalization mappings
  character_mappings:
    "CO2": "CO₂"
    "H2O": "H₂O"
    "O2": "O₂"
    "+/-": "±"
    "+-": "±"

  # Skip certain references
  skip_references:
    - "PMID:00000000"  # Example: no abstract available

  # Trust low-similarity matches (manually verified)
  trusted_low_similarity:
    - "PMID:99999999"  # Example: verified manually
```

Use the config file:

```bash
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml \
  --config .linkml-reference-validator.yaml
```

### Using Environment Variables

Create a `.env` file:

```bash
# NCBI Configuration
NCBI_EMAIL=your.email@example.com
NCBI_API_KEY=your_api_key_here

# Cache Configuration
REFERENCE_CACHE_DIR=/path/to/global/cache

# Rate Limiting (requests per second)
NCBI_RATE_LIMIT=3
CROSSREF_RATE_LIMIT=2
```

Load environment variables:

```bash
# Using direnv (recommended)
echo 'dotenv' > .envrc
direnv allow

# Or manually source
set -a
source .env
set +a
```

## Working with Different Reference Types

### PubMed IDs (PMID)

```bash
linkml-reference-validator validate text \
  "Your quote here" \
  PMID:16888623
```

### PubMed Central (PMC)

For full-text access:

```bash
linkml-reference-validator validate text \
  "Your quote here" \
  PMC:3458566
```

### Digital Object Identifiers (DOI)

```bash
linkml-reference-validator validate text \
  "Your quote here" \
  DOI:10.1038/nature12373
```

### Local Files

```bash
# Markdown file
linkml-reference-validator validate text \
  "Your quote here" \
  file:./references/paper1.md

# Text file
linkml-reference-validator validate text \
  "Your quote here" \
  file:./references/paper1.txt

# HTML file
linkml-reference-validator validate text \
  "Your quote here" \
  file:./references/paper1.html
```

### Web URLs

```bash
linkml-reference-validator validate text \
  "Your quote here" \
  url:https://example.org/article.html
```

## Integration with Existing Workflows

### Pre-commit Hook

Add validation to your git pre-commit:

**.git/hooks/pre-commit:**
```bash
#!/bin/bash

echo "Running reference validation..."

linkml-reference-validator validate data \
  data/*.yaml \
  --schema schemas/schema.yaml \
  --target-class Dataset

if [ $? -ne 0 ]; then
  echo "❌ Reference validation failed!"
  echo "Run 'linkml-reference-validator repair data ...' to fix errors"
  exit 1
fi

echo "✅ Reference validation passed!"
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

### CI/CD Integration (GitHub Actions)

**.github/workflows/validate.yml:**
```yaml
name: Validate References

on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install linkml-reference-validator

      - name: Validate references
        run: |
          linkml-reference-validator validate data \
            data/*.yaml \
            --schema schemas/schema.yaml \
            --target-class Dataset
        env:
          NCBI_EMAIL: ${{ secrets.NCBI_EMAIL }}
          NCBI_API_KEY: ${{ secrets.NCBI_API_KEY }}
```

### Makefile Integration

**Makefile:**
```makefile
.PHONY: validate repair clean

SCHEMA := schemas/schema.yaml
DATA := data/*.yaml
CLASS := Dataset

validate:
	linkml-reference-validator validate data \
		$(DATA) \
		--schema $(SCHEMA) \
		--target-class $(CLASS)

repair:
	linkml-reference-validator repair data \
		$(DATA) \
		--schema $(SCHEMA) \
		--target-class $(CLASS) \
		--dry-run

repair-apply:
	linkml-reference-validator repair data \
		$(DATA) \
		--schema $(SCHEMA) \
		--target-class $(CLASS) \
		--no-dry-run

clean:
	rm -rf references_cache/
```

Usage:
```bash
make validate
make repair
make repair-apply
```

## Verification Checklist

After setup, verify everything works:

- [ ] Installation successful: `linkml-reference-validator --version`
- [ ] Can fetch PubMed articles: `linkml-reference-validator cache reference PMID:16888623`
- [ ] Can validate text: `linkml-reference-validator validate text "test" PMID:16888623`
- [ ] Schema validates: `linkml-validate --schema schema.yaml data.yaml`
- [ ] Reference validation works: `linkml-reference-validator validate data data.yaml --schema schema.yaml`
- [ ] Cache directory created: `ls -l references_cache/`
- [ ] Configuration file recognized: `linkml-reference-validator --help` shows config options

## Next Steps

Now that you're set up:

1. **Read the Quickstart** - [quickstart.md](quickstart.md) for basic usage
2. **Explore Tutorials** - Work through the Jupyter notebooks in `docs/notebooks/`
3. **Learn Editorial Conventions** - [concepts/editorial-conventions.md](concepts/editorial-conventions.md) for using `[...]` and `...`
4. **Review How-To Guides** - Specific recipes for common tasks
5. **Check out the CLI Reference** - [reference/cli.md](reference/cli.md) for all commands

## Getting Help

If you encounter issues:

1. **Check the documentation** - Most common questions are covered
2. **Search existing issues** - https://github.com/linkml/linkml-reference-validator/issues
3. **Ask for help** - Create a new issue with:
   - Your command
   - Expected behavior
   - Actual behavior
   - Schema and data samples (if applicable)
4. **Join the community** - LinkML discussions on GitHub

## Troubleshooting

See the [Troubleshooting Guide](troubleshooting.md) for common issues and solutions.

### Quick Fixes

**"Command not found: linkml-reference-validator"**
```bash
# Ensure it's installed
pip install linkml-reference-validator

# Check if it's in PATH
which linkml-reference-validator

# Use full path if needed
python -m linkml_reference_validator --help
```

**"Could not fetch reference: PMID:12345678"**
```bash
# Check internet connection
ping www.ncbi.nlm.nih.gov

# Verify PMID exists
# Visit: https://pubmed.ncbi.nlm.nih.gov/12345678/

# Set email for NCBI (required for API access)
export NCBI_EMAIL="your.email@example.com"
```

**"Permission denied: references_cache/"**
```bash
# Check directory permissions
ls -ld references_cache/

# Create with proper permissions
mkdir -p references_cache
chmod 755 references_cache
```

**"Validation failed but text is in the paper"**
- Check if only abstract was fetched (full text may be in PMC)
- Use PMC ID instead: `PMC:3458566`
- Or use a local file with full text: `file:./paper.md`
- See [repair-validation-errors.md](how-to/repair-validation-errors.md)
