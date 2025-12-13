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
2. Extracts the page title
3. Converts HTML to plain text
4. Validates the extracted content against your supporting text

## URL Format

URLs can be specified in two ways:

### Explicit URL Prefix

```yaml
my_field:
  value: "Some text from the web page..."
  references:
    - "URL:https://example.com/book/chapter1"
```

### Direct URL

```yaml
my_field:
  value: "Some text from the web page..."
  references:
    - "https://example.com/book/chapter1"
```

Both formats are equivalent. If a reference starts with `http://` or `https://`, it's automatically recognized as a URL reference.

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

```yaml
description:
  value: "The cell is the basic structural and functional unit of all living organisms"
  references:
    - "https://example.com/biology/cell-structure"
```

## How URL Validation Works

### 1. Content Fetching

When the validator encounters a URL reference, it:

- Makes an HTTP GET request to fetch the page
- Uses a polite user agent header identifying the tool
- Respects rate limiting (configurable via `rate_limit_delay`)
- Handles timeouts (default 30 seconds)

### 2. Content Extraction

The fetcher extracts content from the HTML:

- **Title**: Extracted from the `<title>` tag
- **Content**: HTML is converted to plain text using BeautifulSoup
- **Cleanup**: Removes scripts, styles, navigation, headers, and footers
- **Normalization**: Whitespace is normalized for better matching

### 3. Content Type

URL references are marked with content type `html_converted` to distinguish them from other reference types like abstracts or full-text articles.

### 4. Caching

Fetched URL content is cached to disk in markdown format with YAML frontmatter:

```markdown
---
reference_id: URL:https://example.com/biology/cell-structure
title: "Chapter 3: Cell Structure and Function"
content_type: html_converted
---

# Chapter 3: Cell Structure and Function

## Content

The cell is the basic structural and functional unit of all living organisms.
Cells contain various organelles that perform specific functions...
```

Cache files are stored in the configured cache directory (default: `.linkml-reference-validator-cache/`).

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

### HTML Structure

The content extraction works by:

- Removing navigation, headers, and footers
- Converting remaining HTML to text
- Normalizing whitespace

This works well for simple HTML but may not capture content perfectly from complex layouts.

### No Rendering

The fetcher downloads raw HTML and parses it directly. It does not:

- Execute JavaScript
- Render the page in a browser
- Follow redirects automatically (may be added in future)
- Handle dynamic content

## Best Practices

### 1. Use Stable URLs

Choose URLs that are unlikely to change:

- ✅ Versioned documentation: `https://docs.example.com/v1.0/chapter1`
- ✅ Archived content: `https://archive.example.com/2024/article`
- ❌ Blog posts with dates that might be reorganized
- ❌ URLs with session parameters

### 2. Verify Content Quality

After adding a URL reference, verify the extracted content:

```bash
# Check what was extracted
cat .linkml-reference-validator-cache/URL_https___example.com_page.md
```

Ensure the extracted text contains the relevant information you're referencing.

### 3. Cache Management

- Commit cache files to version control for reproducibility
- Use `--force-refresh` to update cached content
- Periodically review cached URLs to ensure they're still accessible

### 4. Mix Reference Types

URL references work alongside PMIDs and DOIs:

```yaml
findings:
  value: "Multiple studies confirm this relationship"
  references:
    - "PMID:12345678"  # Research paper
    - "DOI:10.1234/journal.article"  # Another paper
    - "https://example.com/textbook/chapter5"  # Textbook chapter
```

## Troubleshooting

### URL Not Fetching

If URL content isn't being fetched:

1. Check network connectivity
2. Verify the URL is accessible in a browser
3. Check for rate limiting or IP blocks
4. Look for error messages in the logs

### Incorrect Content Extraction

If the wrong content is extracted:

1. Inspect the cached markdown file
2. Check if the page uses complex JavaScript
3. Consider if the page structure requires custom parsing
4. File an issue with the page URL for improvement

### Validation Failing

If validation fails for URL references:

1. Check the cached content to see what was extracted
2. Verify your supporting text actually appears on the page
3. Check for whitespace or formatting differences
4. Consider if the page content has changed since caching

## Comparison with Other Reference Types

| Feature | PMID | DOI | URL |
|---------|------|-----|-----|
| Source | PubMed | Crossref | Any web page |
| Content Type | Abstract + Full Text | Abstract | HTML converted |
| Metadata | Rich (authors, journal, etc.) | Rich | Minimal (title only) |
| Stability | High | High | Variable |
| Access | Free for abstracts | Varies | Varies |
| Caching | Yes | Yes | Yes |

## See Also

- [Validating DOIs](validate-dois.md) - For journal articles with DOIs
- [Validating OBO Files](validate-obo-files.md) - For ontology-specific validation
- [How It Works](../concepts/how-it-works.md) - Core validation concepts
- [CLI Reference](../reference/cli.md) - Command-line options
