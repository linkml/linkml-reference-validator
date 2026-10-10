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
2. Extracts the page title (see [Titles](#titles))
3. Converts HTML to readable text and caches it for future validations
4. Validates your supporting text against the page content

## URL Format

Use the `url:` prefix to specify URL references (the prefix is optional for bare
HTTP/HTTPS URLs and will be normalized to `url:` internally):

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

- **Title**: See [Titles](#titles)
- **Content**: Readable text for HTML pages; plain text and XML as received;
  extracted text for PDFs
- **Content type**: `url` for pages, `full_text_pdf` for PDFs with text

HTML is converted to readable text before it is cached. A quote copied from
the page then matches even when it runs through a link, bold or italic text,
and a cached page can be read, and diffed, line by line:

- Inline tags (`<a>`, `<b>`, `<em>`, `<span>`, ...) are removed and their
  text is kept in place.
- Block-level tags (`<p>`, `<li>`, `<h1>`-`<h6>`, `<div>`, `<br>`, ...) start
  a new line.
- A table row is one line, its cells separated by ` | `. Normalization drops
  the `|`, so a quote copied from a rendered row with its cells separated by
  spaces still matches.
- `<pre>` keeps its whitespace. Elsewhere whitespace collapses to one space.
- Entities such as `&amp;` are unescaped.

The whole page is kept, including navigation, sidebars and footers; it is not
narrowed to the article body. Because caches are often committed to public
repositories and page scripts routinely carry signed asset URLs and API keys,
`<script>`, `<style>`, `<noscript>` and `<template>` elements and HTML comments
are removed with their text, and no tag attribute reaches the cache.

#### Titles

For HTML pages the title is the `citation_title` meta tag when present (the
Highwire / Google Scholar convention, which names the article rather than the
site), then the `<title>` tag.

For PDFs the validator tries, in order:

1. The `citation_title` of the publisher's landing page, where a known rule
   maps the PDF URL to it. Currently J-STAGE: `.../_pdf` becomes
   `.../_article`.
2. The PDF's embedded `/Title` metadata, ignoring placeholders such as
   `Microsoft Word - draft.doc`, bare filenames and `Untitled`.
3. The URL itself.

So a PDF entry whose `title` equals its URL is one for which no title was
found.

The landing-page rules and the placeholder titles are kept in
`src/linkml_reference_validator/etl/rules.py`, with the other publisher and
site rules. Each rule sits beside examples of what it must and must not match.
To support another publisher, add a rule there with at least one example;
`tests/test_rules.py` fails for a rule without one.

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

The validator stores the page's text, not its markup. For HTML pages:

- Text that only appears in an attribute, such as an image's `alt` text, is
  not kept
- Text inside `<noscript>` or `<template>` is not kept
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
linkml-reference-validator cache lookup url:https://example.com/page --content
```

Ensure the cached content contains the text you're referencing.

### 3. Cache Management

- Commit cache files to version control for reproducibility
- Use `linkml-reference-validator cache reference url:https://... --force` to update cached content when pages change
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

To re-fetch content for a URL that may have changed, refresh the cache before
validating:

```bash
linkml-reference-validator cache reference url:https://example.com/page --force

linkml-reference-validator validate text \
  "Updated content" \
  url:https://example.com/page
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
