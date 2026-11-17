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
