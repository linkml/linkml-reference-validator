# Using Signed Excerpts from a Private Full-Text Store

A public repository cannot commit closed-access full texts to its
`references_cache/`, so a quote taken from the body of a paywalled paper fails
ordinary validation. Signed excerpts close that gap. A **private store** holds
the full texts and verifies short, fair-use excerpts against them. The
verified excerpts are then copied into the public repository, where the
validator accepts an exact match against them.

The store is any directory of YAML bundles. The reference setup is
[claimstore](https://github.com/monarch-initiative/claimstore), a private
repository that runs this validator over its own full texts and writes its
bundles to `signed_excerpts/`.

## How validation uses signed excerpts

Set `signed_excerpts_dir` in `.linkml-reference-validator.yaml`:

```yaml
validation:
  cache_dir: references_cache
  signed_excerpts_dir: signed_excerpts
```

An excerpt then passes if EITHER:

1. it matches the reference in `references_cache/` as usual, OR
2. it exactly matches (after collapsing whitespace) an excerpt recorded for
   that reference in `signed_excerpts/<REF_ID>.yaml`.

Any edit to a signed excerpt in the public repository makes it fail, so the
public copy cannot drift from what the private store verified.

A bundle is named like a cache file (`PMID_12345.yaml`,
`DOI_10.1038_s41418-020-0601-5.yaml`) and looks like this:

```yaml
reference_id: PMID:12345
title: Example title
excerpts:
- text: The verbatim quote ... with omitted words marked by an ellipsis.
  claim_text: Optional paraphrase of the claim the quote supports.
  target_repo:
  - dismech:kb/disorders/Example.yaml
```

Only `reference_id` and each excerpt's `text` are used by validation. Other
fields (claims, NER annotations, checksums) are carried along unchanged.

## Signing excerpts from local full text

You may not need a separate private store. If you hold a closed paper's full
text on your own machine, licensed for your use but not for redistribution,
the validator can check quotes against it and write the bundle itself.

### 1. Map the reference to the local file

Cite the paper by its real identifier in the data:

```yaml
evidence:
  - reference: DOI:10.1016/j.ajodo.2025.11.017
    supporting_text: "The T-appliance is a removable activator supported by both the maxilla and the mandible."
```

Then tell the validator where the text is, either one reference at a time:

```yaml
validation:
  signed_excerpts_dir: signed_excerpts
  local_full_text:
    DOI:10.1016/j.ajodo.2025.11.017: papers/10.1016_j.ajodo.2025.11.017.md
```

or with a directory of files named like cache files
(`DOI_10.1016_j.ajodo.2025.11.017.md`, `.txt`, or `.pdf`):

```yaml
validation:
   local_full_text_dir: ~/private-papers
```

If you used `linkml-reference-validator cache enrich --provider zotero --apply`
(see [Export a Reference Cache to Zotero](export-cache-to-zotero.md)), its
output in `private_cache_dir` (`~/.cache/linkml-reference-validator/private`) is
checked automatically by `excerpts sign` when `local_full_text_dir` is unset.

Relative paths, including a relative `local_full_text_dir`, resolve against
`reference_base_dir`, or the working directory if that is unset. Set
`reference_base_dir` so the result does not depend on where you run the
command. Keep the files out of the repository, or list them in
`.gitignore`.

While a mapped file exists, quotes citing that ID are matched against it, in
preference to any fetched text. The paper's metadata (title and so on) is
still fetched and cached as usual, but **the file's text is never written to
any cache**. Where the file is absent, for example in CI or on another
curator's machine, validation works exactly as if nothing were mapped.

### 2. Sign the quotes

```bash
linkml-reference-validator excerpts sign kb/disorders/*.yaml
```

For every cited reference that has local text, each quote is validated
against the file, with the usual matcher and fair-use caps
(`max_excerpt_length`, `max_total_chars_per_reference`,
`max_reference_fraction`). Quotes that pass are written to
`signed_excerpts/<REF_ID>.yaml`. Quotes that fail are listed, are not signed,
and make the command exit 1.

```yaml
reference_id: DOI:10.1016/j.ajodo.2025.11.017
title: ...
source_char_count: 41230
excerpts:
- text: The T-appliance is a removable activator supported by both the maxilla and the mandible.
  verification:
    method: local_full_text
    source_sha256: 3f1c...
    validator_version: 0.7.0
    verified_at: '2026-11-17'
```

The bundle stores each quote as it is written in the data, because CI
compares quotes against the bundle exactly. `source_char_count` lets CI
apply `max_reference_fraction` without the file.

Options:

- `--reference ID` (repeatable) signs only those references. A requested
  reference with no local text is reported and the command exits 1.
- `--check` writes nothing and exits 1 if any bundle is out of date.
- `--prune` removes excerpts this command signed earlier that the data no
  longer cites, including from bundles for references the data no longer
  cites at all. Excerpts from anywhere else, such as a private store, are
  always kept. Pass **every** data file with `--prune`: a quote cited only in
  a file you left out counts as no longer cited. A reference with any quote
  that fails to verify is not pruned in that run, so a wrongly mapped file
  (a preprint instead of the published paper, say) cannot delete good
  excerpts. With `--reference`, only the named references are pruned, and
  bundles for references the data no longer cites are left alone.
  Only bundles named as validation reads them (`<REF_ID>.yaml`, or `.yml`
  when there is no `.yaml`) are pruned; a hand-named file is left alone.
  A bundle whose excerpts from elsewhere are already over a cap is reported
  on every `--prune` run, because pruning never removes them; trim it by hand.
  Keep only bundles in `signed_excerpts_dir`: `--prune` reads every YAML
  file there, and one that is not a readable bundle is reported and makes the
  command exit 1.
- `--signed-excerpts-dir DIR` overrides the destination in the config.

The fair-use caps are checked twice: on each run's quotes, as in validation,
and on the merged bundle as a whole, because the bundle keeps every quote
ever signed into it. This is checked for every bundle the command would
write to, including one that is otherwise unchanged, so `--check` reports a bundle that a lowered
cap or a hand edit has pushed over. A bundle that would go over
`max_total_chars_per_reference` or `max_reference_fraction` is not written.
The same is true if the source file changes while its quotes are being
checked, since the recorded hash would not match the text that was checked.

Re-signing is deterministic. An existing bundle keeps its excerpts, their
order and their other fields (such as `target_repo`). An excerpt already
verified against the same file (the same `source_sha256`) is left as it is,
so an unchanged run rewrites nothing. New quotes are added in sorted order.
An existing bundle is never used as evidence when signing, so an entry typed
by hand cannot be re-signed without matching the file.

### 3. Commit the bundle

Commit `signed_excerpts/*.yaml` together with the data. CI validates the same
`DOI:` citation through the bundle and never needs the paper.

### What "signed" means here

The `verification` record is an **attestation, not a cryptographic
signature**. It records which text a quote was checked against, with which
version, and when, so a reviewer can tell signed entries from hand-typed
ones. It cannot stop someone who can edit the bundle from also editing the
record. In particular, it does not defend against an agent that writes a
bundle directly. To require the record, set:

```yaml
validation:
  signed_excerpts_require_verification: true
```

Then validation ignores excerpts that have no `verification.source_sha256`.
This is off by default so bundles written before `excerpts sign` existed keep
working.

The hash identifies the *text file* that was matched, not the paper. Two
extractions of one paper (PDF to text, or JATS XML) have different hashes.

## Syncing bundles with `excerpts sync`

`excerpts sync` copies bundles from a local checkout of the private store
into `signed_excerpts_dir`. Files are copied byte for byte, so the public copy
is exactly what the store verified.

```bash
linkml-reference-validator excerpts sync --source ../claimstore/signed_excerpts
```

With no filters every bundle is copied. A store usually serves several
repositories, so two filters narrow the selection. A bundle is copied if it
passes EITHER filter:

- `--target-repo NAME` selects bundles with an excerpt whose `target_repo`
  is `NAME` or starts with `NAME:`.
- `--referenced-in GLOB` (repeatable) selects bundles whose `reference_id` is
  cited in a file matching the glob. This catches excerpts that were never
  tagged with a `target_repo`. Globs are relative to the working directory,
  and a glob that matches no files is an error. The `reference_id` is matched
  as written in the bundle (ignoring case), without the prefix normalization
  that validation applies, so bundles should use the same CURIE form as the
  citing data.

List every directory whose files are validated against `signed_excerpts_dir`.
With `--prune`, a bundle cited only from a directory left out of the list is
deleted.

Other options:

- `--prune` deletes bundles in the destination that are no longer selected.
  Files that are not YAML, such as a README, are left alone. Pruning is refused
  if nothing is selected, so a wrong source cannot empty the destination.
- `--check` writes nothing and exits 1 if the destination is out of date. Other
  errors (missing source, malformed bundle, bad glob) exit 2.
- `--signed-excerpts-dir DIR` overrides the destination from the config.

### Configuring a repository

Put the selection in the config file so that everyone syncs the same way. The
source path depends on where each person cloned the private store, so supply it
with `--source` or the `LRV_SIGNED_EXCERPTS_SOURCE` environment variable. It can
also go in `signed_excerpts_sync.source_dir`, but then it is the same for everyone.

```yaml
validation:
  signed_excerpts_dir: signed_excerpts
  signed_excerpts_sync:
    target_repo: dismech
    referenced_in:
      - kb/disorders/*.yaml
      - kb/modules/*.yaml
    prune: true
```

Options given on the command line override the config.

### Example: dismech

[dismech](https://github.com/monarch-initiative/dismech) cites claimstore
excerpts in `kb/disorders/`. Its config holds the settings above, and its
justfile wraps the command:

```bash
# needs read access to the private monarch-initiative/claimstore repo
git clone git@github.com:monarch-initiative/claimstore.git ../claimstore
just sync-signed-excerpts                         # uses ../claimstore by default
CLAIMSTORE_DIR=~/repos/claimstore just sync-signed-excerpts
```

Then commit the changed `signed_excerpts/*.yaml` files with the disorder files
that quote them. Validation in dismech CI reads only the committed
`signed_excerpts/` and never needs access to the private store.
