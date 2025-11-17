# Validating OBO Format Files

This guide shows how to validate supporting text in OBO format ontology files using the `validate text-file` command.

## Overview

OBO format ontologies may include axiom annotations that contain supporting text from publications. For example:

```obo
[Term]
id: GO:0043263
name: cellulosome
def: "An extracellular multi-enzyme complex..." [PMID:11601609] {ex:supporting_text="a unique extracellular multi-enzyme complex, called cellulosome[PMID:11601609]"}
```

The `validate text-file` command can extract these supporting text annotations using regular expressions and validate them against the referenced publications.

## Basic Usage

### Command Structure

```bash
linkml-reference-validator validate text-file <file-path> \
  --regex <pattern> \
  [--text-group <number>] \
  [--ref-group <number>] \
  [--summary]
```

### Example: Validating OBO Axiom Annotations

For OBO files with `ex:supporting_text` annotations:

```bash
linkml-reference-validator validate text-file my_ontology.obo \
  --regex 'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"' \
  --text-group 1 \
  --ref-group 2
```

**Explanation:**
- `--regex`: Regular expression pattern with two capture groups
  - Group 1: `([^"]*)` - captures the supporting text (everything before `[`)
  - Group 2: `(\S+:\S+)` - captures the reference ID (e.g., `PMID:11601609`)
- `--text-group 1`: First capture group contains the supporting text
- `--ref-group 2`: Second capture group contains the reference ID

### Example Output

```
Extracting text from my_ontology.obo
  Regex pattern: ex:supporting_text="([^"]*)\[(\S+:\S+)\]"
  Text group: 1, Reference group: 2
  Cache directory: references_cache

Found 15 match(es) to validate

Line 8: def: "..." [PMID:11601609] {ex:supporting_text="a unique extracel...
  ✓ VALID: Supporting text validated successfully

Line 23: def: "..." [PMID:23456789] {ex:supporting_text="protein complex fo...
  ✗ INVALID: Supporting text not found in reference

============================================================
Validation Summary:
  Total validations: 15
  Valid: 13
  Invalid: 2
  Errors: 2

✗ Some validations failed
```

## Advanced Usage

### Summary Mode

To see only the summary statistics without individual line results:

```bash
linkml-reference-validator validate text-file my_ontology.obo \
  --regex 'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"' \
  --summary
```

### Verbose Mode

To see detailed matching information:

```bash
linkml-reference-validator validate text-file my_ontology.obo \
  --regex 'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"' \
  --verbose
```

### Custom Cache Directory

To use a specific cache directory for downloaded references:

```bash
linkml-reference-validator validate text-file my_ontology.obo \
  --regex 'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"' \
  --cache-dir /path/to/cache
```

## Regex Pattern Guide

The regex pattern must have at least two capture groups:
1. One for the supporting text
2. One for the reference ID

### Common Patterns

**OBO axiom annotations:**
```regex
ex:supporting_text="([^"]*)\[(\S+:\S+)\]"
```

**Different annotation property:**
```regex
my_prop:text="([^"]*)" my_prop:ref=(\S+)
```

**Custom format:**
```regex
evidence\{text:([^,]+),ref:([^}]+)\}
```

### Capture Group Specification

By default:
- `--text-group 1` (first capture group is supporting text)
- `--ref-group 2` (second capture group is reference ID)

You can change these if your pattern has groups in a different order:

```bash
# If reference comes before text in your pattern
linkml-reference-validator validate text-file file.obo \
  --regex 'ref=(\S+) text="([^"]+)"' \
  --text-group 2 \
  --ref-group 1
```

## Understanding Results

### Valid Results (✓)

The supporting text was found in the reference content (abstract or full text) using substring matching.

### Invalid Results (✗)

The supporting text was not found. This could mean:
- The text is a hallucination or paraphrase
- The text uses different wording than the source
- The reference ID is incorrect
- The full text is not available (only abstract was checked)

### Editorial Conventions

The validator supports editorial conventions:
- `[...]` - Editorial insertions (ignored during matching)
- `...` - Omitted text (matches any text)

Example:
```
Supporting text: "protein [X] functions ... in cells"
Matches: "protein ABC functions in regulation of cell growth in cells"
```

## Best Practices

1. **Start with a small test file** to verify your regex pattern works correctly
2. **Use verbose mode** initially to understand what's being matched
3. **Cache references** locally to avoid repeated API calls during development
4. **Check the extraction** first - if no matches are found, your regex may be incorrect
5. **Be specific** with your regex to avoid false matches

## Troubleshooting

### No matches found

- Verify your regex pattern matches the actual file format
- Use a regex tester to check your pattern against sample lines
- Check that capture groups are correctly numbered

### All validations fail

- Check that reference IDs are correct (e.g., `PMID:12345`)
- Verify supporting text is actually from the reference
- Use `--verbose` to see what text is being searched

### Rate limiting

- Use `--cache-dir` to cache downloaded references
- The validator respects rate limits automatically (0.5s delay between requests)

## See Also

- [How It Works](../concepts/how-it-works.md) - Understanding the validation process
- [Editorial Conventions](../concepts/editorial-conventions.md) - Supported text patterns
- [CLI Reference](../reference/cli.md) - Complete CLI documentation
