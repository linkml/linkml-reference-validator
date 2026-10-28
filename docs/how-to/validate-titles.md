# Validating Reference Titles

This guide explains how to validate that reference titles in your data match the actual titles from the source publications.

## Overview

Title validation ensures that when you cite a reference with a title, that title matches what the publication actually has. Unlike excerpt validation (which uses substring matching), title validation uses **exact matching after normalization**.

## When to Use Title Validation

Title validation is useful when:

- Your data includes reference titles that should match the source
- You want to catch typos or outdated titles
- You need to verify metadata accuracy in curated datasets

## Schema Setup

Mark title fields in your LinkML schema using `dcterms:title`:

### Using `implements`

```yaml
id: https://example.org/my-schema
name: my-schema

prefixes:
  linkml: https://w3id.org/linkml/
  dcterms: http://purl.org/dc/terms/

classes:
  Evidence:
    attributes:
      reference:
        implements:
          - linkml:authoritative_reference
      reference_title:
        implements:
          - dcterms:title
      supporting_text:
        implements:
          - linkml:excerpt
```

### Using `slot_uri`

```yaml
classes:
  Evidence:
    attributes:
      reference:
        slot_uri: linkml:authoritative_reference
      title:
        slot_uri: dcterms:title
      supporting_text:
        slot_uri: linkml:excerpt
```

## Example Data

**data.yaml:**
```yaml
- reference: PMID:16888623
  reference_title: "MUC1 oncoprotein blocks nuclear targeting of c-Abl"
  supporting_text: "MUC1 oncoprotein blocks nuclear targeting"
```

**Validate:**
```bash
linkml-reference-validator validate data \
  data.yaml \
  --schema schema.yaml \
  --target-class Evidence
```

## What Gets Normalized

Title matching allows for minor orthographic variations:

| Variation | Example |
|-----------|---------|
| **Case** | `"JAK1 Protein"` matches `"jak1 protein"` |
| **Whitespace** | `"Cell  Signaling"` matches `"Cell Signaling"` |
| **Punctuation** | `"T-Cell Receptor"` matches `"T Cell Receptor"` |
| **Greek letters** | `"α-catenin"` matches `"alpha-catenin"` |
| **Trailing periods** | `"Study Title."` matches `"Study Title"` |

## Title-Only Validation

You can validate titles without excerpts. If your data has reference and title fields but no excerpt field, the validator will validate the title alone:

```yaml
classes:
  Reference:
    attributes:
      id:
        implements:
          - linkml:authoritative_reference
      title:
        implements:
          - dcterms:title
```

```yaml
- id: PMID:16888623
  title: "MUC1 oncoprotein blocks nuclear targeting of c-Abl"
```

The reference may take the same shapes as for excerpts:

- **A list of one** is checked like a single reference.
- **Several references with one title field** pass if the title is any one
  reference's title, since it names one paper. If it is none of them, a single
  error names each reference with its own reason. A reference whose prefix is
  skipped vouches for nothing.
- **Reference objects with their own `title`**, listed or not, and with no title
  field beside them, each have that title checked against their own reference.
- **A reference with no usable identifier** (an object without `id`, an empty
  string) is reported as an error, not skipped.

With an excerpt as well, the title field is checked the same way: against the
one reference, or, with several, passing if it is any one reference's title.
It replaces any `title` a reference object carries. Without a title field,
each reference object's own `title` is checked with the excerpt.

## Combined Validation

When both title and excerpt fields are present, both are validated together:

1. The excerpt is checked for substring match in the reference content
2. The title is checked for exact match (after normalization) against the reference title

If either fails, validation fails with a specific error message.

## Error Messages

### Title Mismatch

```
Title mismatch for PMID:16888623: expected 'Wrong Title' but got 'MUC1 oncoprotein blocks nuclear targeting of c-Abl'
```

### Reference Has No Title

```
Reference PMID:99999999 has no title to validate against
```

## Differences from Excerpt Validation

| Aspect | Title Validation | Excerpt Validation |
|--------|------------------|-------------------|
| **Matching** | Exact (after normalization) | Substring |
| **Partial matches** | Not allowed | Allowed with `...` |
| **Editorial notes** | Not supported | `[brackets]` removed |
| **Use case** | Metadata accuracy | Quote verification |

## Best Practices

1. **Use exact titles**: Copy the title exactly from the source
2. **Don't abbreviate**: Title must match completely
3. **Check special characters**: Greek letters, subscripts, etc.
4. **Verify after fetching**: The cached reference shows the actual title
