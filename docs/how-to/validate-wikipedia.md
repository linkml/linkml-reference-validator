# Validating Wikipedia References

This guide shows how to validate supporting text against English Wikipedia articles.

## Overview

The `WIKIPEDIA` source reads an article as plain text from the
[MediaWiki Action API](https://www.mediawiki.org/wiki/API:Main_page)
(`prop=extracts` with `explaintext`). It gets:

- **Title**: the article's title, after any redirect
- **Content**: the whole article body as plain text (`content_type: full_text`),
  with section headings as plain lines
- **Version**: the article's canonical URL, the revision that was read and its timestamp
- **License**: `CC BY-SA 4.0`

Because the text has no markup, a quote that runs through a link or bold text
on the rendered page matches. A `url:https://en.wikipedia.org/wiki/...`
reference also works, but it reads the whole rendered page, navigation and
footer included, and does not record which revision it read.

## Basic Usage

Cite the article by its title, as it appears in the article's URL:

```bash
linkml-reference-validator validate text \
  "The Saanen originates in the historic region of Saanen" \
  WIKIPEDIA:Saanen_goat
```

In data:

```yaml
evidence:
  - reference: WIKIPEDIA:Saanen_goat
    supporting_text: The Saanen originates in the historic region of Saanen
```

## Accepted Identifier Formats

```
WIKIPEDIA:Saanen_goat        # as in the URL (recommended)
WIKIPEDIA:Saanen goat        # spaces also work
WIKIPEDIA:Caf%C3%A9          # percent-encoded, as copied from a URL
wikipedia:Saanen_goat        # the prefix is case-insensitive
```

Every spelling normalizes to the one the article's URL uses, as MediaWiki
reads titles: spaces become underscores, percent-encoding is decoded and the
first letter is upper-cased, and a `#Section` anchor is dropped (the citation
is to the whole article). So `WIKIPEDIA:saanen goat` is `WIKIPEDIA:Saanen_goat`,
and all of them share the cache file `WIKIPEDIA_Saanen_goat.md`. A project
that defines its own `WIKIPEDIA` source keeps its IDs as written.

A redirect is followed: `WIKIPEDIA:Saanen` reads the article *Saanen goat*, and
the cached title says so. A title with no article, or an invalid one, is not found.

## Wikipedia Changes Over Time

An article is edited, and a quote that matched last month may not match now.
The cache records what was checked:

```yaml
---
reference_id: WIKIPEDIA:Saanen_goat
content_type: full_text
title: Saanen goat
license: CC BY-SA 4.0
source_url: https://en.wikipedia.org/wiki/Saanen_goat
source_revision: '1250000001'
source_revision_timestamp: '2026-09-01T12:00:00Z'
---
```

Commit the cache with your data, and the quote stays checked against the
revision in it. `cache reference WIKIPEDIA:Saanen_goat --force` reads the
current revision. You can see the revision you quoted at
`https://en.wikipedia.org/w/index.php?oldid=<source_revision>`.

Wikipedia's text is licensed CC BY-SA 4.0: quoting it is fine, and a committed
cache holds a copy of it under that licence.

## Rate Limits

Wikimedia asks API clients to identify themselves. The validator sends a
`User-Agent` naming itself and the `email` in your configuration, so set one:

```yaml
# .linkml-reference-validator.yaml
validation:
  email: you@example.org
```

Wikimedia throttles busy clients with HTTP 429. A throttled request gets no
result; a cached copy is used when there is one, so caching the articles you
cite (and committing the cache) keeps validation working offline and in CI.

## Your Own WIKIPEDIA Source

A project that defined its own `WIKIPEDIA` source in
`.linkml-reference-validator-sources.yaml` before this one existed keeps using
it: a source a project defines takes precedence over a built-in source with the
same prefix. Delete it to use the built-in source.

## Limitations

- English Wikipedia only.
- A citation is to the article, not a revision: a fresh fetch reads the
  current one.
- Tables, infoboxes, references and image captions are not in the plain-text
  extract, so a quote from them is not found.

## See Also

- [Validating URLs](validate-urls.md)
- [Adding a New Reference Source](add-reference-source.md)
- [Cache Format and Validation](../reference/cache-format.md)
