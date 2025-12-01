# Future Enhancements

This document tracks potential enhancements that could be ported from [ai-gene-review](https://github.com/monarch-initiative/ai-gene-review).

## Common Issue Detection (from ai-gene-review)

The following issue detection features are available in ai-gene-review's `SupportingTextSubstringValidator` class and could be added to linkml-reference-validator:

### 1. Ellipsis Detection

Detect when `...` causes validation issues and suggest using only the first part of the quote:

```python
if "..." in supporting_text:
    first_part = supporting_text.split("...")[0].strip()
    suggestions.append(f"Remove '...' - use only first part: \"{first_part}\"")
```

### 2. Short Text Detection

Warn when query text is too short (<20 chars after removing brackets):

```python
if len(non_bracket_text) < MIN_SPAN_LENGTH:
    suggestions.append(f"Too short ({len(non_bracket_text)} chars) - extend with context from source")
```

### 3. Bracket Ratio Detection

Warn when bracketed content exceeds the actual quoted content:

```python
bracket_content = ''.join(re.findall(r'\[.*?\]', supporting_text))
if len(bracket_content) > len(non_bracket_text):
    suggestions.append("More brackets than quotes - reduce editorial additions")
```

### 4. All-Bracketed Detection

Error when supporting_text is entirely in brackets (no actual quoted text):

```python
if total_query_length == 0:
    return (
        False,
        "Supporting text contains no quotable text - all content is in [brackets]. "
        "Supporting text must contain actual quoted text from the source."
    )
```

### 5. Smart Editorial Bracket Detection

The `is_editorial_bracket()` method distinguishes between editorial notes and scientific notation:

- Editorial brackets (removed): `[important]`, `[The protein]`, `[according to studies]`
- Scientific notation (kept): `[+21]`, `[G14]`, `[Ca 2+]`, `[Mg2+]`

## Reference Code

See the following files in ai-gene-review for implementation details:

- `src/ai_gene_review/validation/supporting_text_validator.py`:
  - `SupportingTextSubstringValidator` class
  - `generate_suggested_fix()` method (full version with issue detection)
  - `is_editorial_bracket()` method

- `src/ai_gene_review/validation/fuzzy_text_utils.py`:
  - `find_fuzzy_match_with_context()` for position-aware matching
