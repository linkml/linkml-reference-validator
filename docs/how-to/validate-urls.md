# Validating URL References

This guide explains how to validate references that use URLs instead of traditional identifiers like PMIDs or DOIs.

## Overview

The linkml-reference-validator supports validating references that point to web content, such as:

- Book chapters hosted online
- Educational resources
- Documentation pages
- Blog posts or articles
- Any static web content

When a reference field contains a URL, the validator:

1. Fetches the web page content
2. Extracts the page title from `<title>` tag (for HTML)
3. Caches the content for future validations
4. Validates your supporting text against the page content

## URL Format

Use the `url:` prefix to specify URL references:

```yaml
my_field:
  value: "Some text from the web page..."
  references:
    - "url:https://example.com/book/chapter1"
```

Or via CLI:

```bash
linkml-reference-validator validate text \
  "Some text from the web page" \
  url:https://example.com/book/chapter1
```

## Example

Suppose you have an online textbook chapter at `https://example.com/biology/cell-structure` with the following content:

```html
<html>
  <head>
    <title>Chapter 3: Cell Structure and Function</title>
  </head>
  <body>
    <h1>Cell Structure and Function</h1>
    <p>The cell is the basic structural and functional unit of all living organisms.</p>
    <p>Cells contain various organelles that perform specific functions...</p>
  </body>
</html>
```

You can validate text extracted from this chapter:

```bash
linkml-reference-validator validate text \
  "The cell is the basic structural and functional unit of all living organisms" \
  url:https://example.com/biology/cell-structure
```

## How URL Validation Works

### 1. Content Fetching

When the validator encounters a URL reference, it:

- Makes an HTTP GET request to fetch the page
- Uses a polite user agent header identifying the tool
- Respects rate limiting (configurable via `rate_limit_delay`)
- Handles timeouts (default 30 seconds)

### 2. Content Storage

The fetcher stores:

- **Title**: Extracted from the `<title>` tag (for HTML pages)
- **Content**: The raw page content as received
- **Content type**: Marked as `url` to distinguish from other reference types

Note: Unlike some tools, the validator stores the raw page content without HTML-to-text conversion. This preserves the original content, though HTML tags will be present in the cached file.

### 3. Caching

Fetched URL content is cached to disk in markdown format with YAML frontmatter:

```markdown
---
reference_id: url:https://example.com/biology/cell-structure
title: "Chapter 3: Cell Structure and Function"
content_type: url
---

# Chapter 3: Cell Structure and Function

## Content

<html>
  <head>
    <title>Chapter 3: Cell Structure and Function</title>
  </head>
  ...
```

Cache files are stored in the configured cache directory (default: `references_cache/`).

## Configuration

URL fetching behavior can be configured:

```yaml
# config.yaml
rate_limit_delay: 0.5  # Wait 0.5 seconds between requests
email: "your-email@example.com"  # Used in user agent
cache_dir: ".cache/references"  # Where to cache fetched content
```

Or via command-line:

```bash
linkml-reference-validator validate \
  --cache-dir .cache \
  --rate-limit-delay 0.5 \
  my-data.yaml
```

## Limitations

### Static Content Only

URL validation is designed for static web pages. It may not work well with:

- Dynamic content loaded via JavaScript
- Pages requiring authentication
- Content behind paywalls
- Frequently changing content

### Raw Content

The validator stores raw page content. For HTML pages:

- HTML tags are preserved in the cache
- The text normalization during validation handles most cases
- Complex HTML layouts may require careful text extraction

### No Rendering

The fetcher downloads raw HTML and parses it directly. It does not:

- Execute JavaScript
- Render the page in a browser
- Handle dynamic content

## Best Practices

### 1. Use Stable URLs

Choose URLs that are unlikely to change:

- Versioned documentation: `https://docs.example.com/v1.0/chapter1`
- Archived content: `https://archive.example.com/2024/article`
- Avoid URLs with session parameters

### 2. Verify Content Quality

After adding a URL reference, verify the extracted content:

```bash
# Check what was extracted
cat references_cache/url_https___example.com_page.md
```

Ensure the cached content contains the text you're referencing.

### 3. Cache Management

- Commit cache files to version control for reproducibility
- Use `--force-refresh` to update cached content when pages change
- Periodically review cached URLs to ensure they're still accessible

### 4. Mix Reference Types

URL references work alongside PMIDs and DOIs:

```yaml
findings:
  value: "Multiple studies confirm this relationship"
  references:
    - "PMID:12345678"  # Research paper
    - "DOI:10.1234/journal.article"  # Another paper
    - "url:https://example.com/textbook/chapter5"  # Textbook chapter
```

## Troubleshooting

### URL Not Fetching

If URL content isn't being fetched:

1. Check network connectivity
2. Verify the URL is accessible in a browser
3. Check for rate limiting or IP blocks
4. Look for error messages in the logs

### Validation Failing

If validation fails for URL references:

1. Check the cached content to see what was extracted
2. Verify your supporting text actually appears on the page
3. Check for whitespace or formatting differences
4. Consider if the page content has changed since caching

### Force Refresh

To re-fetch content for a URL that may have changed:

```bash
linkml-reference-validator validate text \
  "Updated content" \
  url:https://example.com/page \
  --force-refresh
```

## Comparison with Other Reference Types

| Feature | PMID | DOI | URL | file |
|---------|------|-----|-----|------|
| Source | PubMed | Crossref | Any web page | Local filesystem |
| Content Type | Abstract + Full Text | Abstract | Raw HTML/text | Raw file content |
| Metadata | Rich (authors, journal, etc.) | Rich | Minimal (title only) | Minimal (title from heading) |
| Stability | High | High | Variable | High (local control) |
| Access | Free for abstracts | Varies | Varies | Always available |
| Caching | Yes | Yes | Yes | Yes |

## See Also

- [Using Local Files and URLs](use-local-files-and-urls.md) - Quick reference for file and URL sources
- [Validating DOIs](validate-dois.md) - For journal articles with DOIs
- [Validating OBO Files](validate-obo-files.md) - For ontology-specific validation
- [How It Works](../concepts/how-it-works.md) - Core validation concepts
- [CLI Reference](../reference/cli.md) - Command-line options
