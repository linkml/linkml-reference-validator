# Using Local Files and URLs as References

In addition to PubMed IDs and DOIs, the validator supports local files and web URLs as reference sources. This is useful when your supporting text comes from internal documentation, research notes, or web pages.

## Local File References

Use the `file:` prefix to reference local files:

```bash
linkml-reference-validator validate text \
  "JAK1 binds to the receptor complex" \
  file:./research/jak-signaling-notes.md
```

### Supported File Types

- **Markdown** (`.md`) - Title extracted from first `# heading`
- **Plain text** (`.txt`) - Content used as-is
- **HTML** (`.html`) - Content preserved including HTML entities

### Path Resolution

**Absolute paths** always work:

```bash
file:/Users/me/research/notes.md
```

**Relative paths** are resolved in order:

1. If `reference_base_dir` is configured, paths resolve relative to it
2. Otherwise, paths resolve relative to the current working directory

### Configuring a Base Directory

Set a base directory for all relative file references:

```python
from linkml_reference_validator.models import ReferenceValidationConfig
from pathlib import Path

config = ReferenceValidationConfig(
    reference_base_dir=Path("./references"),
)
```

Then `file:notes.md` resolves to `./references/notes.md`.

### Example: Validating Against Research Notes

Create a research file:

```markdown
# JAK-STAT Signaling Pathway

JAK1 binds to the receptor complex and initiates downstream signaling.
This leads to STAT phosphorylation and nuclear translocation.
```

Validate:

```bash
linkml-reference-validator validate text \
  "JAK1 binds to the receptor complex" \
  file:./jak-signaling.md
```

## URL References

Use the `url:` prefix to reference web pages:

```bash
linkml-reference-validator validate text \
  "Climate change affects biodiversity" \
  url:https://example.org/climate-report.html
```

### Caching

URLs are cached the same way as PMID and DOI references:

- First fetch downloads and caches the content
- Subsequent validations use the cached version
- Use `--force-refresh` to re-fetch

### Title Extraction

For HTML pages, the title is extracted from the `<title>` tag. For other content types, the URL itself is used as the title.

### Example: Validating Against a Web Page

```bash
# First validation fetches and caches
linkml-reference-validator validate text \
  "The quick brown fox jumps over the lazy dog" \
  url:https://example.com/pangram-examples.html

# Subsequent validations use cache
linkml-reference-validator validate text \
  "A quick brown fox" \
  url:https://example.com/pangram-examples.html
```

## Using in Data Files

Both file and URL references work in LinkML data files:

```yaml
# data.yaml
- id: local-evidence
  supporting_text: JAK1 binds to the receptor complex
  reference: file:./research/jak-notes.md

- id: web-evidence
  supporting_text: Climate impacts are accelerating
  reference: url:https://example.org/climate-report.html
```

## Reference Type Summary

| Prefix | Example | Source |
|--------|---------|--------|
| `PMID:` | `PMID:16888623` | PubMed via NCBI Entrez |
| `DOI:` | `DOI:10.1038/nature12373` | Crossref API |
| `file:` | `file:./notes.md` | Local filesystem |
| `url:` | `url:https://example.com` | Web (HTTP/HTTPS) |

## Best Practices

### For Local Files

- Keep reference files in a dedicated directory
- Use `reference_base_dir` for consistent path resolution
- Use markdown for structured content with clear headings

### For URLs

- Prefer stable URLs (avoid query parameters that change)
- Be aware that web content may change (cache helps with reproducibility)
- Consider downloading important pages as local files for long-term stability

## Limitations

- **PDF files**: Not yet supported (planned for future)
- **Authentication**: URLs requiring login are not supported
- **Dynamic content**: JavaScript-rendered pages may not work
