---
name: linkml-reference-validator
description: Validate cited quotations and reference titles with LinkML Reference Validator (LRV). Use for checking supporting_text against publications or local sources, validating evidence in LinkML YAML/JSON, investigating mismatched quotes, or previewing quote repairs.
---

# Validate reference evidence

LRV checks whether quoted text occurs in a cited source after supported
normalization. It does not decide whether a scientific claim follows from that
quote. Use separate reasoning for relevance, interpretation, and contradictions.

## Set up and choose the check

Examples use `uvx linkml-reference-validator`; in a repository checkout use
`uv run linkml-reference-validator`. Installing this skill does not install the
Python package. Inspect `--help` if the installed release has different options.
Prefer the nested CLI commands below over deprecated hyphenated aliases.

Use the supplied reference identifier, never an invented PMID or DOI. Check its
metadata and available content first:

```bash
uvx linkml-reference-validator lookup PMID:16888623 \
  --format json --cache-dir references_cache
```

Lookup supports multiple identifiers. Its success exit code means at least one
lookup succeeded; inspect each result. Check `content_type`: an abstract-only
cache cannot establish absence of a quote from the full paper. Supported sources
include PubMed/PMC, DOI, `file:/absolute/path/to/source.txt`, and
`url:https://example.org/source`; consult the docs for other source types.

For a single quote, the positional arguments are **text first, reference second**:

```bash
uvx linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting" PMID:16888623 \
  --cache-dir references_cache
```

Add `--title "Expected title"` when also checking the supplied title. Ellipses can
separate quote fragments and bracketed editorial notes are ignored by matching;
neither is permission to rewrite a source's meaning.

## Validate structured evidence

```bash
uvx linkml-reference-validator validate data data.yaml \
  --schema schema.yaml --target-class Statement --cache-dir references_cache
```

Use the actual target class from the schema. The schema must identify excerpts
and references through `implements` or `slot_uri`, not just plausible field names.
Canonical interfaces are `oa:exact` for excerpts and `dcterms:references` for
references; legacy `linkml:excerpt` and `linkml:authoritative_reference` are also
supported. Inspect the schema before changing it. For plain text or OBO files,
use `validate text-file --help` to supply a regex and the correct capture groups.

Read the summary as well as the exit code. Exit 0 can mean **zero comparisons**.
Report files and snippets checked, skipped, unavailable, and failed separately;
do not count skipped prefixes, missing excerpts, or unavailable sources as
validated evidence. Preserve reference cache contents for reproducibility.
Retrieval failures, access restrictions, and a quote absent from the retrieved
content are different findings.

## Investigate or repair failures

Inspect the retrieved source and exact input before suggesting a correction.
Never fabricate a replacement quotation, substitute a different citation just
to make validation pass, or lower matching criteria to hide a mismatch.

When repair is requested, preview changes first. `repair data` uses a simpler
extractor than schema-aware validation: it expects scalar reference IDs in
common evidence fields and does not support every schema layout:

```bash
uvx linkml-reference-validator repair data data.yaml \
  --schema schema.yaml --target-class Statement \
  --cache-dir references_cache --dry-run
```

Review suggested edits against the source and intended claim. When applying an
authorized repair, use `--no-dry-run --output repaired.yaml` to preserve the input,
then revalidate the result. The CLI otherwise overwrites input with a backup.

For nested reference objects such as `reference: {id: PMID:...}`, extract the
identifier and preview one quote with `repair text "QUOTE" REFERENCE_ID` instead;
current `repair data` can fail on that layout. Do not flatten or rewrite the
dataset merely to make the repair command run.

Deliver the failing file/field, reference identifier, failure category, source
coverage (abstract or full text), and supported correction if one exists.
Include remaining unchecked evidence, even if the command succeeded.

See the [CLI reference](https://linkml.io/linkml-reference-validator/reference/cli/)
for cache configuration, source-specific retrieval, and extraction options.
