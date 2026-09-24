# Configure and diagnose reference checks

## Confirm the effective inputs

Use the project's wrapper and locked runtime. The commands below illustrate
targeted investigation with the nested CLI; substitute real paths and IDs.
LRV's `--config` selects a config file; `-c` means **cache directory**, unlike
LTV. An explicit config avoids depending on the invocation directory's
`.linkml-reference-validator.yaml` or `.yml` autodiscovery.

The config accepts a `validation` envelope, a legacy `reference_validation`
envelope, or flat validation fields. Prefer one unambiguous representation:

```yaml
validation:
  cache_dir: references_cache
  unknown_prefix_severity: ERROR
  skip_prefixes: []
```

Inspect CLI overrides and project wrappers as well as the file. Check a known
failure to confirm configuration is being consumed; a misplaced envelope can
leave defaults in effect. Keep custom source definitions reproducible in the
project rather than relying on a developer's home-directory configuration.

## Map the schema to the evidence

Plausible field names alone do not establish schema-aware coverage. Excerpt
slots need `implements` or `slot_uri` identifying `oa:exact`; reference slots
need `dcterms:references`. Legacy `linkml:excerpt` and
`linkml:authoritative_reference` are also supported. Check the schema's actual
nesting and target class, including nested reference objects. Confirm a known
evidence item contributes a comparison and a bad quote fails.

For plain text, `validate text-file` uses regex extraction: inspect `--help`
for text/reference capture groups and test the extracted pairs. A regex that
matches nothing does not validate the document.

## Diagnose retrieval before matching

```bash
uv run --locked linkml-reference-validator lookup PMID:16888623 \
  --format json --cache-dir references_cache --config conf/reference-validator.yaml
```

Lookup can return success when only some supplied identifiers resolve. Inspect
each record and its `content_type` (for example, `abstract_only` or full text),
not just the status. Ordinary validation does not read the private research
library cache. Access to a paper during research does not establish that the
shared validation cache contains that paper's body.

Unknown-prefix/fetch failures, explicitly skipped prefixes, and quote
mismatches need different remedies. `skip_prefixes` is case-insensitive and
bypasses checking those references. `unknown_prefix_severity` changes how
retrieval failures are reported; it does not supply missing evidence. When
enabling a new source, populate its cache and assess newly exposed title and
snippet failures before changing the gate.

`file:` references can support local sources; use absolute paths or configure
`reference_base_dir` so a temporary hook file or changed working directory does
not resolve a different source.

## Diagnose matching and configuration policy

For one quote, arguments are **text first, reference second**:

```bash
uv run --locked linkml-reference-validator validate text \
  "MUC1 oncoprotein blocks nuclear targeting" PMID:16888623 \
  --cache-dir references_cache --config conf/reference-validator.yaml
```

Add `--title` with the supplied title to check metadata too. Quote fragments
separated by ellipses and bracketed editorial material have normalization
rules; review the source before treating every substring failure as paraphrase.

`literal_bracket_patterns` preserves bracket contents matching configured
regexes. This matters when a source itself contains bracketed abbreviations or
statistics. Choose patterns using actual source/quote pairs and test both
literal text and editorial glosses. A broad pattern changes which editorial
material is treated as a verbatim quotation. `min_excerpt_length` can require
more substantive excerpts, but length alone does not establish evidential
strength. Explain the corpus impact of either policy change.

## Use repair as a reviewed suggestion

When a repair is appropriate, preview with `repair text "QUOTE" REFERENCE_ID`
or `repair data ... --dry-run`. Data repair uses a simpler extractor than
schema-aware validation and expects scalar reference IDs in common evidence
fields; it does not support every nested layout. For
`reference: {id: PMID:...}`, use the extracted ID with text repair rather than
rewriting the dataset to suit the repair command.

Review suggestions for fidelity to the source and the intended claim. When
applying a data repair, `--no-dry-run --output repaired.yaml` preserves the input;
otherwise the CLI overwrites it with a backup. Revalidate the result with the
same schema, config, and source content. Consult the
[CLI reference](https://linkml.io/linkml-reference-validator/reference/cli/)
for source-specific options supported by the installed release.
