# Future Enhancements

This document tracks planned and potential enhancements for linkml-reference-validator.

## Roadmap

### Full Text Access Improvements

#### PDF Support

**Status:** Planned

Currently, local files must be text or markdown. PDF support would enable:

- Direct validation against local PDF files (`file:./paper.pdf`)
- Automatic text extraction from downloaded papers
- Integration with reference managers that store PDFs

**Potential libraries:**
- [pymupdf4llm](https://github.com/pymupdf/PyMuPDF) - Best balance of speed and quality
- [marker-pdf](https://github.com/VikParuchuri/marker) - Best structure preservation for complex layouts

**Challenges:**
- Scientific papers have complex layouts (multi-column, figures, tables)
- OCR needed for scanned PDFs
- Text extraction quality varies significantly

#### Zotero Integration

**Status:** Under consideration

Integration with [Zotero](https://www.zotero.org/) would enable:

- Fetching full text from Zotero library attachments
- Using Zotero's cached PDFs for validation
- Syncing with Zotero collections

**Potential approach:**
- [pyzotero](https://github.com/urschrei/pyzotero) - Official Python API wrapper
- [pyzotero-local](https://github.com/sailist/pyzotero-local) - Direct SQLite database access
- Zotero 7 local API (`http://localhost:23119/api/`)

**Note:** Zotero 7 beta includes a `/fulltext` endpoint for retrieving full content.

#### Paperpile Integration

**Status:** Blocked (no API)

[Paperpile](https://paperpile.com/) does not provide a public API. Integration would require:

- Manual BibTeX export + PDF file association
- Unofficial workarounds

See [Paperpile API feature request](https://forum.paperpile.com/t/public-developer-api/918).

### Validation Enhancements

#### Cross-Source Fallback

**Status:** Under consideration

When a PMID has no PMC full text, automatically try:

1. DOI lookup via Crossref
2. URL if available in metadata
3. User-configured fallback sources

#### Content Type Preferences

**Status:** Under consideration

Allow users to configure validation strictness based on content type:

```yaml
validation:
  require_full_text: true  # Fail if only abstract available
  warn_on_abstract_only: true  # Warn but don't fail
```

### Common Issue Detection (from ai-gene-review)

The following features are available in [ai-gene-review](https://github.com/monarch-initiative/ai-gene-review) and could be ported:

#### 1. Ellipsis Detection

Detect when `...` causes validation issues and suggest using only the first part of the quote:

```python
if "..." in supporting_text:
    first_part = supporting_text.split("...")[0].strip()
    suggestions.append(f"Remove '...' - use only first part: \"{first_part}\"")
```

#### 2. Short Text Detection

Warn when query text is too short (<20 chars after removing brackets):

```python
if len(non_bracket_text) < MIN_SPAN_LENGTH:
    suggestions.append(f"Too short ({len(non_bracket_text)} chars) - extend with context from source")
```

#### 3. Bracket Ratio Detection

Warn when bracketed content exceeds the actual quoted content:

```python
bracket_content = ''.join(re.findall(r'\[.*?\]', supporting_text))
if len(bracket_content) > len(non_bracket_text):
    suggestions.append("More brackets than quotes - reduce editorial additions")
```

#### 4. All-Bracketed Detection

Error when supporting_text is entirely in brackets (no actual quoted text):

```python
if total_query_length == 0:
    return (
        False,
        "Supporting text contains no quotable text - all content is in [brackets]. "
        "Supporting text must contain actual quoted text from the source."
    )
```

#### 5. Smart Editorial Bracket Detection

The `is_editorial_bracket()` method distinguishes between editorial notes and scientific notation:

- Editorial brackets (removed): `[important]`, `[The protein]`, `[according to studies]`
- Scientific notation (kept): `[+21]`, `[G14]`, `[Ca 2+]`, `[Mg2+]`

### Reference Code

See the following files in ai-gene-review for implementation details:

- `src/ai_gene_review/validation/supporting_text_validator.py`:
  - `SupportingTextSubstringValidator` class
  - `generate_suggested_fix()` method (full version with issue detection)
  - `is_editorial_bracket()` method

- `src/ai_gene_review/validation/fuzzy_text_utils.py`:
  - `find_fuzzy_match_with_context()` for position-aware matching

## Contributing

Want to help implement these features? See [GitHub Issues](https://github.com/linkml/linkml-reference-validator/issues) for current work items.
