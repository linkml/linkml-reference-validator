# Complete Workflow Tutorial: Building a Validated Gene Annotation System

This tutorial walks you through building a complete gene annotation validation system from scratch, using real examples and best practices.

## What We'll Build

A validated gene function annotation system that:
- Stores gene function claims with supporting text from publications
- Automatically validates that quotes match their cited sources
- Supports multiple reference types (PMID, DOI, PMC)
- Includes repair capabilities for common errors
- Can be integrated into a CI/CD pipeline

**Time required:** 30-45 minutes

## Prerequisites

- Python 3.10+ installed
- Basic understanding of YAML
- Familiarity with command line
- (Optional) NCBI API key for higher rate limits

## Step 1: Installation and Setup (5 minutes)

### Install the Tool

```bash
# Using pip
pip install linkml-reference-validator

# Or using uv (faster)
curl -LsSf https://astral.sh/uv/install.sh | sh
uv pip install linkml-reference-validator
```

### Create Project Structure

```bash
# Create project directory
mkdir gene-annotation-validator
cd gene-annotation-validator

# Create subdirectories
mkdir -p schemas data references_cache tests

# Verify installation
linkml-reference-validator --version
```

### Configure NCBI Access (Optional)

```bash
# Set environment variables
export NCBI_EMAIL="your.email@example.com"

# Test with a simple validation
linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting of c-Abl" \
  PMID:16888623
```

Expected output:
```
Validating text against PMID:16888623...
Result:
  Valid: True
  Message: Supporting text validated successfully in PMID:16888623
```

## Step 2: Design Your Data Model (10 minutes)

### Create the LinkML Schema

We'll create a schema for gene function annotations with evidence from literature.

**schemas/gene_annotations.yaml:**
```yaml
id: https://example.org/gene-annotations
name: gene-annotations
description: Schema for validated gene function annotations

prefixes:
  linkml: https://w3id.org/linkml/
  dcterms: http://purl.org/dc/terms/
  biolink: https://w3id.org/biolink/vocab/

default_prefix: gene_annotations

classes:
  # Root container class
  GeneAnnotationCollection:
    tree_root: true
    description: Collection of gene function annotations
    attributes:
      annotations:
        multivalued: true
        range: GeneAnnotation
        description: List of gene annotations

  # Main annotation class
  GeneAnnotation:
    description: An annotation describing a gene's function with supporting evidence
    attributes:
      id:
        identifier: true
        required: true
        description: Unique identifier for this annotation

      gene_symbol:
        required: true
        description: Official gene symbol (e.g., TP53, BRCA1)
        pattern: "^[A-Z0-9]+$"

      gene_name:
        description: Full gene name

      function_summary:
        required: true
        description: Brief summary of the gene's function

      function_category:
        range: FunctionCategory
        description: Broad categorization of gene function

      species:
        range: Species
        description: Species this annotation applies to
        required: true

      evidence:
        required: true
        multivalued: true
        range: Evidence
        description: Supporting evidence from literature

      last_reviewed:
        range: date
        description: Date this annotation was last reviewed

      curator:
        description: Person who created/reviewed this annotation

  # Evidence class with reference validation
  Evidence:
    description: Evidence supporting a gene function claim
    attributes:
      reference_id:
        required: true
        slot_uri: linkml:authoritative_reference
        description: |
          Reference identifier (PMID, PMC, DOI, or file path)
          Examples: PMID:16888623, PMC:3458566, DOI:10.1038/nature12373

      reference_title:
        slot_uri: dcterms:title
        description: Title of the referenced publication (validated if provided)

      supporting_text:
        required: true
        slot_uri: linkml:excerpt
        description: |
          Direct quote from the reference supporting the annotation.
          Use [brackets] for editorial clarifications.
          Use ... for omitted text between parts.

      evidence_type:
        range: EvidenceType
        description: Type of experimental evidence

      confidence:
        range: ConfidenceLevel
        description: Curator's confidence in this evidence

      notes:
        description: Additional context or clarifications

# Enumerations
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
      KINASE:
        description: Phosphorylates other proteins
      PHOSPHATASE:
        description: Removes phosphate groups
      RECEPTOR:
        description: Receives extracellular signals
      SIGNALING:
        description: Transmits cellular signals

  EvidenceType:
    permissible_values:
      EXPERIMENTAL:
        description: Direct experimental evidence
      COMPUTATIONAL:
        description: Computational prediction or inference
      LITERATURE:
        description: Statement from literature without original data
      CURATOR_INFERENCE:
        description: Inferred by curator from related evidence

  ConfidenceLevel:
    permissible_values:
      HIGH:
        description: Strong, consistent evidence
      MEDIUM:
        description: Good evidence but some uncertainty
      LOW:
        description: Limited or conflicting evidence

  Species:
    permissible_values:
      HUMAN:
        description: Homo sapiens
      MOUSE:
        description: Mus musculus
      RAT:
        description: Rattus norvegicus
      YEAST:
        description: Saccharomyces cerevisiae
```

### Understanding the Schema

Key elements:
- **`slot_uri: linkml:excerpt`** - Marks `supporting_text` for validation
- **`slot_uri: linkml:authoritative_reference`** - Marks `reference_id` as the reference
- **`slot_uri: dcterms:title`** - Optionally validates reference titles
- **Enumerations** - Controlled vocabularies for consistency
- **Required fields** - Ensures data completeness

## Step 3: Create Sample Data (10 minutes)

### Example 1: Simple Annotation

**data/tp53_annotation.yaml:**
```yaml
annotations:
  - id: ANN001
    gene_symbol: TP53
    gene_name: Tumor protein p53
    function_summary: Regulates cell cycle and acts as tumor suppressor
    function_category: TUMOR_SUPPRESSOR
    species: HUMAN
    curator: Jane Doe
    last_reviewed: 2024-01-15

    evidence:
      - reference_id: PMID:16888623
        reference_title: MUC1 oncoprotein blocks nuclear targeting of c-Abl
        supporting_text: "MUC1 oncoprotein blocks nuclear targeting of c-Abl"
        evidence_type: EXPERIMENTAL
        confidence: HIGH
```

### Example 2: Multiple Evidence Items

**data/brca1_annotation.yaml:**
```yaml
annotations:
  - id: ANN002
    gene_symbol: BRCA1
    gene_name: Breast cancer type 1 susceptibility protein
    function_summary: Critical role in DNA repair and tumor suppression
    function_category: DNA_REPAIR
    species: HUMAN
    curator: John Smith
    last_reviewed: 2024-02-20

    evidence:
      # Evidence 1: DNA repair function
      - reference_id: PMID:12345678
        supporting_text: "BRCA1 plays a critical role in DNA double-strand break repair"
        evidence_type: EXPERIMENTAL
        confidence: HIGH
        notes: Direct experimental demonstration

      # Evidence 2: Tumor suppressor function
      - reference_id: PMID:23456789
        supporting_text: "BRCA1 functions as a tumor suppressor ... maintaining genomic stability"
        evidence_type: EXPERIMENTAL
        confidence: HIGH
        notes: Used ellipsis to connect non-contiguous parts

      # Evidence 3: Using editorial notes
      - reference_id: PMC:3458566
        supporting_text: "BRCA1 [breast cancer type 1] is involved in homologous recombination"
        evidence_type: LITERATURE
        confidence: MEDIUM
        notes: Added gene name clarification in brackets
```

### Example 3: Mixed Reference Types

**data/multi_gene_annotations.yaml:**
```yaml
annotations:
  - id: ANN003
    gene_symbol: EGFR
    gene_name: Epidermal growth factor receptor
    function_summary: Receptor tyrosine kinase involved in cell proliferation
    function_category: RECEPTOR
    species: HUMAN
    curator: Jane Doe

    evidence:
      # Using DOI
      - reference_id: DOI:10.1038/nature12373
        supporting_text: "EGFR is a receptor tyrosine kinase"
        evidence_type: EXPERIMENTAL
        confidence: HIGH

      # Using local file
      - reference_id: file:./references/egfr_review.md
        supporting_text: "EGFR mutations are found in many cancers"
        evidence_type: LITERATURE
        confidence: MEDIUM
        notes: From local review article

  - id: ANN004
    gene_symbol: JAK1
    gene_name: Janus kinase 1
    function_summary: Tyrosine kinase in cytokine signaling
    function_category: KINASE
    species: HUMAN
    curator: John Smith

    evidence:
      # Using URL
      - reference_id: url:https://example.org/jak1-article.html
        supporting_text: "JAK1 is a key mediator of cytokine signaling"
        evidence_type: LITERATURE
        confidence: MEDIUM
```

## Step 4: Validate Your Data (10 minutes)

### Basic Validation

```bash
# Validate single file
linkml-reference-validator validate data \
  data/tp53_annotation.yaml \
  --schema schemas/gene_annotations.yaml \
  --target-class GeneAnnotationCollection

# Expected output:
# Validating data/tp53_annotation.yaml...
# ✓ All validations passed!
```

### Verbose Validation

```bash
# See detailed validation info
linkml-reference-validator validate data \
  data/brca1_annotation.yaml \
  --schema schemas/gene_annotations.yaml \
  --target-class GeneAnnotationCollection \
  --verbose

# Shows:
# - Each reference being validated
# - What text is being searched for
# - Whether full text or abstract was used
# - Validation results for each item
```

### Batch Validation

```bash
# Validate all files in data directory
for file in data/*.yaml; do
  echo "Validating $file..."
  linkml-reference-validator validate data \
    "$file" \
    --schema schemas/gene_annotations.yaml \
    --target-class GeneAnnotationCollection
done
```

## Step 5: Handle Validation Errors (10 minutes)

### Scenario 1: Character Encoding Issues

Create a file with common encoding issues:

**data/error_example1.yaml:**
```yaml
annotations:
  - id: ANN005
    gene_symbol: TEST1
    function_summary: Test gene for CO2 transport
    function_category: SIGNALING
    species: HUMAN

    evidence:
      - reference_id: PMID:16888623
        # This will fail: ASCII "O2" instead of subscript
        supporting_text: "protein involved in O2 transport"
        evidence_type: EXPERIMENTAL
        confidence: HIGH
```

Validate and repair:

```bash
# First validate to see the error
linkml-reference-validator validate data \
  data/error_example1.yaml \
  --schema schemas/gene_annotations.yaml \
  --target-class GeneAnnotationCollection

# Use repair to fix (dry run first)
linkml-reference-validator repair data \
  data/error_example1.yaml \
  --schema schemas/gene_annotations.yaml \
  --target-class GeneAnnotationCollection \
  --dry-run

# Review the suggested fixes, then apply
linkml-reference-validator repair data \
  data/error_example1.yaml \
  --schema schemas/gene_annotations.yaml \
  --target-class GeneAnnotationCollection \
  --no-dry-run
```

### Scenario 2: Missing Ellipsis

**data/error_example2.yaml:**
```yaml
annotations:
  - id: ANN006
    gene_symbol: TEST2
    function_summary: Test gene
    function_category: SIGNALING
    species: HUMAN

    evidence:
      - reference_id: PMID:16888623
        # This will fail: missing "..." between non-contiguous parts
        supporting_text: "MUC1 oncoprotein blocks c-Abl"
        evidence_type: EXPERIMENTAL
        confidence: HIGH
```

The repair command will suggest adding ellipsis:
```
Suggested fix (MEDIUM confidence):
  "MUC1 oncoprotein blocks c-Abl" → "MUC1 oncoprotein ... blocks ... c-Abl"
```

### Scenario 3: Text Not in Reference

**data/error_example3.yaml:**
```yaml
annotations:
  - id: ANN007
    gene_symbol: TEST3
    function_summary: Test gene
    function_category: SIGNALING
    species: HUMAN

    evidence:
      - reference_id: PMID:16888623
        # This will fail: text doesn't exist in reference
        supporting_text: "completely fabricated text that doesn't exist"
        evidence_type: EXPERIMENTAL
        confidence: HIGH
```

The repair command will flag for removal:
```
RECOMMENDED REMOVALS (low confidence):
  PMID:16888623 at evidence[0]:
    Similarity: 5%
    Snippet: 'completely fabricated text that doesn't exist'
    Action: Remove or find correct reference
```

## Step 6: Create Configuration File (5 minutes)

Create a project configuration:

**.linkml-reference-validator.yaml:**
```yaml
# Validation configuration
validation:
  cache_dir: ./references_cache

  # Custom prefix mappings
  reference_prefix_map:
    pubmed: PMID
    pmc: PMC
    doi: DOI

  # Base directory for file:// references
  reference_base_dir: ./references

# Repair configuration
repair:
  # Confidence thresholds
  auto_fix_threshold: 0.95
  suggest_threshold: 0.80
  removal_threshold: 0.50

  # Character normalization
  character_mappings:
    "O2": "O₂"
    "CO2": "CO₂"
    "H2O": "H₂O"
    "N2": "N₂"
    "+/-": "±"
    "alpha": "α"
    "beta": "β"
    "gamma": "γ"

  # Skip references with known issues
  skip_references: []

  # Trusted references (manually verified)
  trusted_low_similarity: []
```

Use the configuration:

```bash
linkml-reference-validator validate data \
  data/*.yaml \
  --schema schemas/gene_annotations.yaml \
  --target-class GeneAnnotationCollection \
  --config .linkml-reference-validator.yaml
```

## Step 7: Integrate with Version Control (5 minutes)

### Create Git Pre-commit Hook

**.git/hooks/pre-commit:**
```bash
#!/bin/bash

echo "🔍 Validating gene annotations..."

# Validate all data files
for file in data/*.yaml; do
  if [ -f "$file" ]; then
    echo "  Checking $file..."

    linkml-reference-validator validate data \
      "$file" \
      --schema schemas/gene_annotations.yaml \
      --target-class GeneAnnotationCollection \
      --config .linkml-reference-validator.yaml

    if [ $? -ne 0 ]; then
      echo "❌ Validation failed for $file"
      echo ""
      echo "To fix errors, run:"
      echo "  linkml-reference-validator repair data $file --schema schemas/gene_annotations.yaml --dry-run"
      exit 1
    fi
  fi
done

echo "✅ All validations passed!"
exit 0
```

Make it executable:
```bash
chmod +x .git/hooks/pre-commit
```

### Create Makefile

**Makefile:**
```makefile
.PHONY: validate validate-verbose repair clean test

SCHEMA := schemas/gene_annotations.yaml
DATA_DIR := data
CONFIG := .linkml-reference-validator.yaml
TARGET_CLASS := GeneAnnotationCollection

# Validate all data files
validate:
	@echo "Validating all annotations..."
	@for file in $(DATA_DIR)/*.yaml; do \
		echo "Checking $$file..."; \
		linkml-reference-validator validate data \
			$$file \
			--schema $(SCHEMA) \
			--target-class $(TARGET_CLASS) \
			--config $(CONFIG) || exit 1; \
	done
	@echo "✅ All validations passed!"

# Validate with verbose output
validate-verbose:
	@for file in $(DATA_DIR)/*.yaml; do \
		echo "Checking $$file..."; \
		linkml-reference-validator validate data \
			$$file \
			--schema $(SCHEMA) \
			--target-class $(TARGET_CLASS) \
			--config $(CONFIG) \
			--verbose; \
	done

# Show suggested repairs (dry run)
repair:
	@for file in $(DATA_DIR)/*.yaml; do \
		echo "Checking repairs for $$file..."; \
		linkml-reference-validator repair data \
			$$file \
			--schema $(SCHEMA) \
			--target-class $(TARGET_CLASS) \
			--config $(CONFIG) \
			--dry-run; \
	done

# Apply repairs
repair-apply:
	@for file in $(DATA_DIR)/*.yaml; do \
		echo "Applying repairs to $$file..."; \
		linkml-reference-validator repair data \
			$$file \
			--schema $(SCHEMA) \
			--target-class $(TARGET_CLASS) \
			--config $(CONFIG) \
			--no-dry-run; \
	done

# Clean cache
clean:
	rm -rf references_cache/

# Run tests
test: validate
	@echo "Running tests..."
	@python -m pytest tests/ -v
```

Usage:
```bash
make validate              # Validate all files
make validate-verbose      # Verbose output
make repair                # Show suggested repairs
make repair-apply          # Apply repairs
make clean                 # Clear cache
```

## Step 8: CI/CD Integration

### GitHub Actions

**.github/workflows/validate-annotations.yml:**
```yaml
name: Validate Gene Annotations

on:
  push:
    branches: [ main, develop ]
    paths:
      - 'data/**.yaml'
      - 'schemas/**.yaml'
  pull_request:
    branches: [ main ]
    paths:
      - 'data/**.yaml'
      - 'schemas/**.yaml'

jobs:
  validate:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout code
        uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          pip install linkml-reference-validator

      - name: Cache references
        uses: actions/cache@v3
        with:
          path: references_cache
          key: ${{ runner.os }}-references-${{ hashFiles('data/**/*.yaml') }}
          restore-keys: |
            ${{ runner.os }}-references-

      - name: Validate annotations
        run: |
          make validate
        env:
          NCBI_EMAIL: ${{ secrets.NCBI_EMAIL }}
          NCBI_API_KEY: ${{ secrets.NCBI_API_KEY }}

      - name: Upload cache artifacts
        if: always()
        uses: actions/upload-artifact@v3
        with:
          name: references-cache
          path: references_cache/
          retention-days: 30
```

## Step 9: Testing and Quality Assurance

### Create Test Files

**tests/test_validation.py:**
```python
#!/usr/bin/env python3
"""Test suite for gene annotation validation."""

import subprocess
import yaml
from pathlib import Path

DATA_DIR = Path("data")
SCHEMA = Path("schemas/gene_annotations.yaml")
TARGET_CLASS = "GeneAnnotationCollection"

def test_schema_valid():
    """Test that schema itself is valid."""
    result = subprocess.run(
        ["linkml-validate", "--schema", str(SCHEMA), str(SCHEMA)],
        capture_output=True,
        text=True
    )
    assert result.returncode == 0, f"Schema validation failed: {result.stderr}"

def test_all_data_files_valid():
    """Test that all data files validate against schema."""
    for data_file in DATA_DIR.glob("*.yaml"):
        if "error" in data_file.name:
            continue  # Skip error example files

        print(f"Testing {data_file}...")
        result = subprocess.run(
            [
                "linkml-reference-validator", "validate", "data",
                str(data_file),
                "--schema", str(SCHEMA),
                "--target-class", TARGET_CLASS
            ],
            capture_output=True,
            text=True
        )
        assert result.returncode == 0, \
            f"Validation failed for {data_file}: {result.stderr}"

def test_data_completeness():
    """Test that all required fields are present."""
    for data_file in DATA_DIR.glob("*.yaml"):
        if "error" in data_file.name:
            continue

        with open(data_file) as f:
            data = yaml.safe_load(f)

        # Check each annotation
        for ann in data.get("annotations", []):
            assert "id" in ann, f"Missing id in {data_file}"
            assert "gene_symbol" in ann, f"Missing gene_symbol in {data_file}"
            assert "evidence" in ann, f"Missing evidence in {data_file}"

            # Check each evidence item
            for ev in ann["evidence"]:
                assert "reference_id" in ev, f"Missing reference_id in {data_file}"
                assert "supporting_text" in ev, f"Missing supporting_text in {data_file}"

if __name__ == "__main__":
    test_schema_valid()
    test_all_data_files_valid()
    test_data_completeness()
    print("✅ All tests passed!")
```

Run tests:
```bash
python tests/test_validation.py
```

## Step 10: Documentation and Maintenance

### Create README

**README.md:**
```markdown
# Gene Annotation Validation System

Validated gene function annotations with supporting evidence from literature.

## Quick Start

```bash
# Validate all annotations
make validate

# Add new annotation
cp templates/annotation_template.yaml data/new_gene.yaml
# Edit data/new_gene.yaml with your annotation
make validate

# Repair validation errors
make repair
```

## Directory Structure

```
.
├── schemas/
│   └── gene_annotations.yaml    # LinkML schema
├── data/
│   ├── tp53_annotation.yaml     # Gene annotations
│   └── ...
├── references_cache/             # Cached references
├── tests/
│   └── test_validation.py       # Test suite
├── .linkml-reference-validator.yaml  # Config
└── Makefile                     # Build commands
```

## Contributing

1. Create new annotation file in `data/`
2. Validate: `make validate`
3. Fix any errors: `make repair`
4. Commit and push (pre-commit hook will validate)
```

### Create Template

**templates/annotation_template.yaml:**
```yaml
annotations:
  - id: ANN_XXX  # Replace with unique ID
    gene_symbol: GENE_SYMBOL  # Official gene symbol
    gene_name: Full Gene Name
    function_summary: Brief summary of function
    function_category: CATEGORY  # See schema for options
    species: HUMAN  # Or MOUSE, RAT, YEAST
    curator: Your Name
    last_reviewed: YYYY-MM-DD

    evidence:
      - reference_id: PMID:XXXXXXXX  # Or DOI:, PMC:, file:, url:
        reference_title: Article title (optional but recommended)
        supporting_text: "Direct quote from the reference"
        evidence_type: EXPERIMENTAL  # Or COMPUTATIONAL, LITERATURE, CURATOR_INFERENCE
        confidence: HIGH  # Or MEDIUM, LOW
        notes: Additional context (optional)
```

## Summary

You've now built a complete gene annotation validation system! You've learned:

- ✅ How to install and configure linkml-reference-validator
- ✅ How to design a LinkML schema with validation markers
- ✅ How to create validated data files
- ✅ How to validate and repair data
- ✅ How to integrate validation into your workflow
- ✅ How to set up CI/CD for automatic validation
- ✅ How to write tests for your validation system

## Next Steps

1. **Expand your schema** - Add more gene attributes, relationships, or evidence types
2. **Import existing data** - Convert existing annotations to your new format
3. **Integrate with databases** - Export validated data to SQL, MongoDB, or RDF
4. **Build a web interface** - Create a UI for curators to add/edit annotations
5. **Set up monitoring** - Track validation success rates and common error patterns

## Additional Resources

- [linkml-reference-validator Documentation](https://linkml.github.io/linkml-reference-validator/)
- [LinkML Schema Language](https://linkml.io/)
- [PubMed E-utilities API](https://www.ncbi.nlm.nih.gov/books/NBK25501/)
- [Crossref API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/)
