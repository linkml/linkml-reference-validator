# Feature Request: Automated Repair Function for Reference Validation

## Summary

Add a `--repair` mode to `linkml-reference-validator` that can automatically fix or flag snippet validation errors based on configurable confidence thresholds.

## Background

After manually fixing ~40 validation errors across 11 disease YAML files, clear patterns emerged in the types of errors and their appropriate fixes:

### Error Categories (from real-world experience)

1. **Minor Text Differences (~30% of errors)**
   - Special character mismatches: `+/-` vs `±`, `Δ` vs `∆`, `CO2` vs `CO₂`
   - Parentheses variations: `(131)I` vs `131I`, `FBN1(T7498C)` vs `FBN1T7498C`
   - Abbreviation differences: `Haemophilus influenzae type b` vs `H. influenzae type b`
   - Minor spacing/punctuation issues

2. **Missing Ellipsis Connectors (~20% of errors)**
   - Non-contiguous text portions quoted without `...` separator
   - Text spans across abstract sections without indicator

3. **Completely Fabricated Snippets (~35% of errors)**
   - Text that appears nowhere in the referenced abstract
   - Often AI-hallucinated plausible-sounding but incorrect quotes
   - Meta-commentary like "No abstract provided" or "No environmental factors mentioned"

4. **No Abstract Available (~15% of errors)**
   - Reference exists but PubMed has no abstract (older papers, certain journals)
   - Cannot be validated - must be flagged or removed

## Proposed Solution

### Command-Line Interface

```bash
# Dry run - show what would be changed
uv run linkml-reference-validator repair data file.yaml \
  --schema schema.yaml \
  --target-class Disease \
  --dry-run

# Auto-fix with confidence threshold
uv run linkml-reference-validator repair data file.yaml \
  --schema schema.yaml \
  --target-class Disease \
  --auto-fix-threshold 0.95 \
  --output repaired.yaml

# Interactive mode for ambiguous cases
uv run linkml-reference-validator repair data file.yaml \
  --schema schema.yaml \
  --target-class Disease \
  --interactive
```

### Confidence Thresholds

| Threshold | Action | Use Case |
|-----------|--------|----------|
| 0.95-1.00 | Auto-fix | Minor character substitutions (±, subscripts) |
| 0.80-0.95 | Suggest fix | Abbreviation changes, minor rewording |
| 0.50-0.80 | Flag for review | Partial matches, possible ellipsis insertion points |
| 0.00-0.50 | Recommend removal | Likely fabricated or wrong reference |
| N/A | Flag as unverifiable | No abstract available for reference |

### Repair Strategies

#### 1. Character Normalization (High Confidence)
```yaml
# Before (fails validation)
snippet: "CO2 levels were measured"

# After (auto-fixed)
snippet: "CO₂ levels were measured"
```

Implement character mapping table:
- `+/-` → `±`
- `Δ` ↔ `∆` (Unicode normalization)
- `(X)Y` → `XY` where X is a number (isotope notation)
- ASCII approximations → proper Unicode

#### 2. Ellipsis Insertion (Medium Confidence)
```yaml
# Before (fails - non-contiguous text)
snippet: "Disease X affects children. Treatment involves medication Y."

# After (suggested fix)
snippet: "Disease X affects children. ... Treatment involves medication Y."
```

Algorithm:
1. Split snippet on sentence boundaries
2. Find each sentence in abstract
3. If gap between matched sentences > threshold, insert `...`
4. Recalculate similarity score

#### 3. Fuzzy Match Correction (Medium Confidence)
```yaml
# Before (fails - abbreviation mismatch)
snippet: "Haemophilus influenzae type b causes meningitis"

# After (suggested from abstract)
snippet: "H. influenzae type b causes meningitis"
```

Use sequence alignment to find best-matching substring in abstract.

#### 4. Removal Recommendation (Low Confidence)
```yaml
# Before (fabricated - not in abstract)
- reference: PMID:12345678
  supports: SUPPORT
  snippet: "This completely made up text that doesn't exist anywhere"
  explanation: "..."

# After (flagged for removal)
# REMOVED: Evidence item for PMID:12345678 - snippet not found in abstract (similarity: 0.12)
```

### Output Modes

#### 1. Report Mode (Default)
```
=== Repair Report for disease.yaml ===

HIGH CONFIDENCE FIXES (auto-applicable):
  Line 45: Changed "CO2" → "CO₂" (PMID:12345678)
  Line 89: Changed "+/-" → "±" (PMID:23456789)

SUGGESTED FIXES (review recommended):
  Line 123: Insert "..." between sentences (similarity: 0.85)
    Before: "Sentence A. Sentence B."
    After:  "Sentence A. ... Sentence B."

RECOMMENDED REMOVALS (low confidence):
  Line 234: PMID:34567890 - snippet similarity 0.08
    Snippet appears to be fabricated or from wrong reference

UNVERIFIABLE (no abstract available):
  Line 345: PMID:45678901 - no abstract in PubMed
    Consider finding alternative reference or removing

Summary: 4 auto-fixes, 2 suggestions, 3 removals, 1 unverifiable
```

#### 2. YAML Output Mode
Write repaired YAML with comments for manual review items:

```yaml
evidence:
  - reference: PMID:12345678
    supports: SUPPORT
    snippet: "CO₂ levels were measured"  # AUTO-FIXED: CO2 → CO₂
    explanation: "..."
  # REVIEW: Consider inserting "..." - similarity 0.85
  - reference: PMID:23456789
    supports: SUPPORT
    snippet: "Sentence A. Sentence B."
    explanation: "..."
  # FLAGGED FOR REMOVAL: snippet not found (similarity: 0.08)
  # - reference: PMID:34567890
  #   supports: SUPPORT
  #   snippet: "Fabricated text..."
```

### Configuration File

Allow project-specific repair settings:

```yaml
# .linkml-reference-validator.yaml
repair:
  auto_fix_threshold: 0.95
  suggest_threshold: 0.80
  removal_threshold: 0.50

  character_mappings:
    "+/-": "±"
    "Δ": "∆"

  abbreviation_patterns:
    - pattern: "Haemophilus influenzae"
      alternatives: ["H. influenzae", "H influenzae"]

  skip_references:
    - "PMID:12345678"  # Known to have no abstract

  trusted_low_similarity:
    - "PMID:98765432"  # Manually verified despite low similarity
```

## Implementation Notes

### Similarity Metrics

Recommend using multiple metrics and combining:

1. **Levenshtein distance** - catches typos and minor edits
2. **Token overlap (Jaccard)** - catches reordering
3. **Longest common subsequence** - catches insertions/deletions
4. **Semantic similarity (optional)** - using sentence embeddings for paraphrase detection

Weighted combination:
```python
confidence = 0.4 * levenshtein_sim + 0.3 * jaccard_sim + 0.3 * lcs_sim
```

### Safety Considerations

1. **Never auto-remove evidence** - only flag for removal
2. **Preserve original in comments** when auto-fixing
3. **Git-friendly output** - changes should be reviewable in diffs
4. **Backup original file** before in-place repair
5. **Audit log** - record all changes made and why

### Edge Cases to Handle

1. **Multiple evidence items for same claim** - safer to remove one bad item if others support
2. **Only evidence item for claim** - require higher confidence or manual review
3. **Snippet matches but different reference** - flag as possible wrong PMID
4. **Abstract has been updated** - note that cached vs live abstracts may differ

## Acceptance Criteria

- [ ] `--repair` command with `--dry-run` mode
- [ ] Configurable confidence thresholds
- [ ] Character normalization auto-fix
- [ ] Ellipsis insertion suggestions
- [ ] Fuzzy match suggestions from actual abstract text
- [ ] Removal recommendations with similarity scores
- [ ] Detection of references without abstracts
- [ ] Report output format
- [ ] Repaired YAML output format
- [ ] Configuration file support
- [ ] Audit logging of all changes

## Related Work

- [linkml-runtime](https://github.com/linkml/linkml-runtime) - core LinkML functionality
- [rapidfuzz](https://github.com/maxbachmann/RapidFuzz) - fast fuzzy string matching
- [textdistance](https://github.com/life4/textdistance) - comprehensive text similarity metrics

## Notes from Manual Repair Experience

After fixing ~40 errors manually, key observations:

1. **Most fabricated snippets are obvious** - they often contain meta-commentary or suspiciously perfect phrasing
2. **Character issues are mechanical** - a fixed mapping table handles 90% of cases
3. **Ellipsis insertion is usually correct** - when text is in abstract but non-contiguous
4. **Removal is safe when multiple evidence exists** - claims typically have 2-5 supporting references
5. **Human review is essential for edge cases** - especially single-evidence claims

The 0.95 threshold for auto-fix is conservative and appropriate - it catches the obvious mechanical fixes while requiring human review for anything ambiguous.
