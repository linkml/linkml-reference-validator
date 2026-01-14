# Troubleshooting Guide

This guide covers common issues and their solutions when using linkml-reference-validator.

## Installation Issues

### Command not found: linkml-reference-validator

**Symptom:**
```bash
$ linkml-reference-validator --help
bash: linkml-reference-validator: command not found
```

**Causes:**
- Package not installed
- Package installed but not in PATH
- Using wrong Python environment

**Solutions:**

1. **Verify installation:**
```bash
pip list | grep linkml-reference-validator
```

2. **Reinstall if missing:**
```bash
pip install linkml-reference-validator
```

3. **Check if it's in PATH:**
```bash
which linkml-reference-validator
```

4. **Use module invocation:**
```bash
python -m linkml_reference_validator --help
```

5. **Check Python environment:**
```bash
# Show current Python
which python
python --version

# If using virtual environment
source venv/bin/activate  # Linux/Mac
venv\Scripts\activate     # Windows
```

### ImportError: No module named 'linkml_reference_validator'

**Symptom:**
```python
ImportError: No module named 'linkml_reference_validator'
```

**Solutions:**

1. **Install in correct environment:**
```bash
# Check current environment
python -c "import sys; print(sys.executable)"

# Install in that environment
python -m pip install linkml-reference-validator
```

2. **Verify installation:**
```python
python -c "import linkml_reference_validator; print(linkml_reference_validator.__version__)"
```

### Version conflicts

**Symptom:**
```
ERROR: pip's dependency resolver does not currently take into account all the packages that are installed. This behaviour is the source of the following dependency conflicts.
```

**Solutions:**

1. **Use uv (recommended):**
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv pip install linkml-reference-validator
```

2. **Create fresh virtual environment:**
```bash
python -m venv fresh_env
source fresh_env/bin/activate
pip install --upgrade pip
pip install linkml-reference-validator
```

3. **Use compatible versions:**
```bash
pip install linkml-reference-validator --upgrade
```

## Reference Fetching Issues

### Could not fetch reference: PMID:XXXXXXXX

**Symptom:**
```
Error: Could not fetch reference PMID:12345678
Failed to retrieve reference content
```

**Causes:**
- PMID doesn't exist
- Network connectivity issues
- NCBI API temporarily unavailable
- Rate limiting
- Missing NCBI email configuration

**Solutions:**

1. **Verify PMID exists:**
   - Visit https://pubmed.ncbi.nlm.nih.gov/12345678/
   - Check if the number is correct

2. **Check network connectivity:**
```bash
ping www.ncbi.nlm.nih.gov
curl -I https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
```

3. **Set NCBI email (required):**
```bash
export NCBI_EMAIL="your.email@example.com"
```

4. **Get NCBI API key for higher limits:**
   - Visit https://www.ncbi.nlm.nih.gov/account/
   - Generate API key
   - Set environment variable:
```bash
export NCBI_API_KEY="your_api_key_here"
```

5. **Retry after delay:**
```bash
# Wait a moment and try again
sleep 5
linkml-reference-validator validate text "quote" PMID:12345678
```

6. **Check cache directory permissions:**
```bash
ls -ld references_cache/
chmod 755 references_cache/
```

### No content available for reference

**Symptom:**
```
Error: No content available for PMID:12345678
Content type: unavailable
```

**Causes:**
- Abstract not available
- Article behind paywall (no PMC access)
- Retracted article
- Very old article
- Article not yet indexed

**Solutions:**

1. **Try PMC version:**
```bash
# Search for PMC ID at https://www.ncbi.nlm.nih.gov/pmc/
linkml-reference-validator validate text "quote" PMC:3458566
```

2. **Use DOI instead:**
```bash
linkml-reference-validator validate text "quote" DOI:10.1038/nature12373
```

3. **Use local file:**
```bash
# Save article content as markdown or text
linkml-reference-validator validate text "quote" file:./papers/article.md
```

4. **Check cache file:**
```bash
# See what was actually fetched
cat references_cache/PMID_12345678.md
```

### Rate limiting errors

**Symptom:**
```
Error: Too many requests to NCBI API
HTTP Error 429: Too Many Requests
```

**Solutions:**

1. **Set NCBI API key:**
```bash
export NCBI_API_KEY="your_api_key"
```
Without key: 3 requests/second
With key: 10 requests/second

2. **Pre-cache references:**
```bash
# Cache all references before validation
for pmid in PMID:111 PMID:222 PMID:333; do
  linkml-reference-validator cache reference $pmid
  sleep 1  # Add delay between requests
done
```

3. **Use cached references:**
```bash
# If cache exists, no API call is made
linkml-reference-validator validate text "quote" PMID:12345678 \
  --cache-dir ./references_cache
```

## Validation Issues

### Supporting text not found in reference

**Symptom:**
```
Error: Supporting text not found in reference
Text part not found as substring: "your quote here"
```

**Causes:**
- Quote is paraphrased, not exact
- Text only in figures/tables/supplementary materials
- Text uses different terminology in reference
- Unicode/character differences
- Only abstract available (text in full text)

**Solutions:**

1. **Verify exact quote:**
   - Open the PDF or HTML of the article
   - Copy the exact text
   - Check for character differences (O2 vs O₂, α vs alpha)

2. **Check content type:**
```bash
linkml-reference-validator cache reference PMID:12345678
# Look for "Content type: abstract_only" vs "full_text_xml"
```

3. **Try PMC for full text:**
```bash
# If only abstract was fetched
linkml-reference-validator validate text "quote" PMC:3458566
```

4. **Use repair command:**
```bash
linkml-reference-validator repair text \
  "your quote here" \
  PMID:12345678
```

5. **Add editorial notes:**
```yaml
# If you need to clarify or modernize
supporting_text: "protein [X] functions in cells"
```

6. **Use ellipsis for non-contiguous text:**
```yaml
supporting_text: "protein functions ... in cell regulation"
```

7. **Check normalization:**
```python
# Test what the text looks like after normalization
from linkml_reference_validator.validation.supporting_text_validator import normalize_text

text = "Your quote here"
print(normalize_text(text))
```

### Query is empty after removing brackets

**Symptom:**
```
Error: Query is empty after removing brackets
Supporting text: "[editorial note]"
```

**Cause:**
- Entire supporting_text is in brackets

**Solution:**

Include actual quote text:
```yaml
# Wrong
supporting_text: "[sic]"

# Correct
supporting_text: "protein functions in cells [sic]"
```

### Title validation failed

**Symptom:**
```
Error: Reference title mismatch
Expected: "Study of Protein X"
Actual: "Study of protein X function"
```

**Causes:**
- Title in data doesn't match fetched title
- Partial title provided
- Capitalization differences

**Solutions:**

1. **Use exact title:**
```bash
# Fetch reference to see actual title
linkml-reference-validator cache reference PMID:12345678
cat references_cache/PMID_12345678.md | head -20
```

2. **Omit title if uncertain:**
```yaml
# Title validation is optional
reference_id: PMID:12345678
# Don't include reference_title if unsure
supporting_text: "your quote"
```

3. **Understand title matching:**
   - Titles must match completely (not substring)
   - Case and punctuation are normalized
   - But all words must match

```yaml
# These match (after normalization):
reference_title: "Role of JAK1 in Cell-Signaling"
actual_title: "Role of JAK1 in Cell Signaling"

# These DON'T match (partial):
reference_title: "Role of JAK1"
actual_title: "Role of JAK1 in Cell Signaling"
```

## Schema Issues

### No reference or supporting_text fields found

**Symptom:**
```
Error: Could not find fields marked with linkml:authoritative_reference or linkml:excerpt
```

**Causes:**
- Schema doesn't have required slot_uri markers
- Using wrong field names
- Schema not properly configured

**Solutions:**

1. **Add slot_uri markers:**
```yaml
classes:
  Evidence:
    attributes:
      reference:
        slot_uri: linkml:authoritative_reference  # Required
      supporting_text:
        slot_uri: linkml:excerpt  # Required
```

2. **Or use implements:**
```yaml
classes:
  Evidence:
    attributes:
      reference:
        implements:
          - linkml:authoritative_reference
      supporting_text:
        implements:
          - linkml:excerpt
```

3. **Or use standard field names:**
   - `reference`, `reference_id`, `pmid` for references
   - `supporting_text`, `excerpt`, `quote` for text

### Schema validation errors

**Symptom:**
```
LinkML schema validation failed
```

**Solutions:**

1. **Validate schema separately:**
```bash
linkml-validate --schema schema.yaml schema.yaml
```

2. **Check required fields:**
```yaml
prefixes:
  linkml: https://w3id.org/linkml/  # Must be defined

classes:
  MyClass:
    tree_root: true  # At least one class needs this
```

3. **Fix common issues:**
```yaml
# Bad: missing range
reference:
  required: true

# Good: includes range
reference:
  required: true
  range: string
```

## Data Format Issues

### YAML parsing errors

**Symptom:**
```
yaml.scanner.ScannerError: mapping values are not allowed here
```

**Solutions:**

1. **Check YAML syntax:**
```bash
# Use YAML validator
python -c "import yaml; yaml.safe_load(open('data.yaml'))"
```

2. **Common YAML mistakes:**

```yaml
# Bad: missing quotes
supporting_text: Text with: colon

# Good: quoted
supporting_text: "Text with: colon"

# Bad: incorrect indentation
evidence:
  reference: PMID:123
supporting_text: "text"

# Good: proper indentation
evidence:
  reference: PMID:123
  supporting_text: "text"
```

3. **Use YAML linter:**
```bash
pip install yamllint
yamllint data.yaml
```

### Invalid reference ID format

**Symptom:**
```
Error: Invalid reference ID format: "invalid_id"
```

**Solutions:**

Use correct format:
```yaml
# Correct formats:
reference_id: PMID:12345678
reference_id: PMC:3458566
reference_id: DOI:10.1038/nature12373
reference_id: file:./path/to/file.md
reference_id: url:https://example.org/article

# Incorrect:
reference_id: 12345678  # Missing PMID: prefix
reference_id: www.example.org  # Missing url: prefix
reference_id: ./file.md  # Missing file: prefix
```

## Performance Issues

### Validation is very slow

**Symptom:**
Validation takes minutes instead of seconds

**Causes:**
- References not cached
- Network latency
- Large number of references
- Fetching full text for each validation

**Solutions:**

1. **Pre-cache references:**
```bash
# Extract all PMIDs from data
grep -r "PMID:" data/ | grep -o "PMID:[0-9]*" | sort -u > pmids.txt

# Cache all
while read pmid; do
  linkml-reference-validator cache reference "$pmid"
done < pmids.txt
```

2. **Use global cache:**
```bash
export REFERENCE_CACHE_DIR=~/.cache/linkml-reference-validator
```

3. **Use verbose mode to identify bottlenecks:**
```bash
linkml-reference-validator validate data data.yaml \
  --schema schema.yaml \
  --verbose
```

4. **Check cache hits:**
```bash
# Cached validations should be <100ms
# First fetch will be 2-3 seconds
```

### Large cache directory

**Symptom:**
```bash
du -sh references_cache/
500M    references_cache/
```

**Solutions:**

1. **Clean old entries:**
```bash
# Remove cache entries older than 30 days
find references_cache/ -name "*.md" -mtime +30 -delete
```

2. **Use selective caching:**
```bash
# Cache only what you need
# Don't cache during experimentation
```

3. **Compress cache:**
```bash
tar -czf references_cache_backup.tar.gz references_cache/
rm -rf references_cache/
```

## Common Error Messages

### "Text normalization resulted in empty string"

**Cause:**
Text only contains punctuation or whitespace

**Solution:**
```yaml
# Bad
supporting_text: "..."

# Good
supporting_text: "text content ... more text"
```

### "Multiple reference fields found"

**Cause:**
Schema has multiple fields marked as authoritative_reference

**Solution:**
Only mark one field per class:
```yaml
# Bad
attributes:
  pmid:
    slot_uri: linkml:authoritative_reference
  doi:
    slot_uri: linkml:authoritative_reference

# Good - use one field that can hold different types
attributes:
  reference_id:
    slot_uri: linkml:authoritative_reference
```

### "Reference base directory not found"

**Cause:**
Using `file:` references but base directory not configured

**Solution:**
```yaml
# In .linkml-reference-validator.yaml
validation:
  reference_base_dir: ./references

# Or use absolute paths
reference_id: file:/full/path/to/file.md
```

## Getting More Help

### Enable verbose logging

```bash
linkml-reference-validator validate text \
  "quote" PMID:12345678 \
  --verbose
```

### Check cache contents

```bash
# View cached reference
cat references_cache/PMID_12345678.md

# Check cache metadata
head -n 20 references_cache/PMID_12345678.md
```

### Test with simple example

```bash
# Known working example
linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting of c-Abl" \
  PMID:16888623
```

### Report bugs

If you've found a bug:

1. **Check existing issues:**
   https://github.com/linkml/linkml-reference-validator/issues

2. **Create minimal reproduction:**
```bash
# Simplest possible command that shows the issue
linkml-reference-validator validate text "test" PMID:12345678 --verbose
```

3. **Include:**
   - Command you ran
   - Expected behavior
   - Actual behavior
   - Error messages (full output)
   - Schema (if applicable)
   - Data file (if applicable, minimal example)
   - Version: `linkml-reference-validator --version`
   - Python version: `python --version`
   - OS: `uname -a` (Linux/Mac) or `ver` (Windows)

## Quick Diagnostic Checklist

Run through this checklist when encountering issues:

- [ ] Installation successful: `linkml-reference-validator --version`
- [ ] Network accessible: `ping www.ncbi.nlm.nih.gov`
- [ ] NCBI email set: `echo $NCBI_EMAIL`
- [ ] Cache directory writable: `touch references_cache/test && rm references_cache/test`
- [ ] Schema valid: `linkml-validate --schema schema.yaml schema.yaml`
- [ ] Data valid YAML: `python -c "import yaml; yaml.safe_load(open('data.yaml'))"`
- [ ] Reference exists: Visit PubMed URL for the PMID
- [ ] Simple test works: Validate known-good example

## See Also

- [Setup Guide](setup-guide.md) - Initial installation and configuration
- [Quickstart](quickstart.md) - Basic usage examples
- [CLI Reference](reference/cli.md) - Complete command documentation
- [How to Repair Validation Errors](how-to/repair-validation-errors.md) - Fixing common issues
- [GitHub Issues](https://github.com/linkml/linkml-reference-validator/issues) - Report bugs
