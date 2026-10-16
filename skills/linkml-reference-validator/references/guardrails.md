# Put LRV in repository guardrails

Read this when adding or changing automated validation. Routine evidence
correction should use the project's existing commands.

## Establish one repository contract

Inspect existing task runners, dependency locks, schema annotations, wrappers,
hooks, and CI before adding another entry point. Record the selected files,
target class, explicit config, cache location, and which findings block each
stage. Keep these decisions in version control so humans and agents run the
same checks.

If LRV is absent from a uv project, add it with `uv add linkml-reference-validator`
and commit the dependency and lockfile changes as part of setup. Skill installation
alone does not supply the runtime. Check the locked release's subcommand help when
integrating or upgrading: repository wrappers can target an older release than
upstream documentation.

For a project with `schema.yaml`, an evidence-bearing class `Statement`, and
`conf/reference-validator.yaml`, a validation command is:

```bash
uv run --locked linkml-reference-validator validate data data.yaml \
  --schema schema.yaml --target-class Statement \
  --config conf/reference-validator.yaml --cache-dir references_cache
```

Adapt those paths/class to the actual project and wrap the command in its task
runner. Use the same wrapper from CI and hooks. Include structural LinkML
validation separately: source matching is not schema validation. Check that
file selection and schema extraction actually produce comparisons.

## Separate retrieval from the frequent check

Matching is deterministic for fixed inputs, config, tool version, and source
content. Live retrieval and changing caches affect what can be compared.
Define how references enter the cache, how source provenance is retained, and
how unavailable content is reported. Prepare newly cited references before
expecting cached checks to cover them.

Keep expensive enrichment and cache normalization out of every edit. Where
supported, `--no-full-text` disables full-text fetching; it is **not an offline
switch** and new references may still be fetched and cached. Test both a cache
hit and a cache miss before describing a hook as offline or non-mutating.
Do not silently treat unavailable content as verified evidence.

## Add a hook appropriate to the editing stage

Use a command hook that invokes the deterministic checker. Configure the event
using the installed Claude Code version's
[hook protocol](https://code.claude.com/docs/en/hooks), preserving existing hooks.

- A `PreToolUse` edit hook must validate the **proposed content** in a temporary
  file, faithfully implementing the tool's edit semantics, including repeated
  replacements. Checking the old file cannot reject a bad proposed edit.
- Resolve paths against the checkout containing the edited file. A hook's
  script or launch directory can belong to the main checkout while the agent
  edits a worktree. Preserve the real schema/config/cache context for temporary
  files, including relative reference paths.
- Map a blocking validation failure to hook exit 2 with an actionable stderr
  diagnostic. Do not merely forward CLI exit 1 and assume it blocks. Bound
  subprocess runtime so the hook can report failure before its own timeout.
- A `PostToolUse` hook can report on the saved result; it cannot undo the write.
  A tool-specific hook also misses edits by other tools or humans. CI provides
  the common check for all changes.

Decide explicitly whether incomplete retrieval should interrupt editing or be
reported for resolution before merge. Preserve the project's chosen distinction
between advisory feedback and required validation.

## Wire CI and verify the integration

Install locked dependencies, prepare the intended cache, and call the repository
recipe. Cover changes to data, schema, validation config, wrappers, dependencies,
and cache policy. Schema/config changes can affect the whole corpus even when
no data file changed. Handle deleted files and an intentionally empty selection
explicitly; accidental selection of zero files must not look like successful QC.

Exercise a matching quote, a mismatch, a wrong title, a missing source, and an
input with no extractable evidence. Verify the actual wrapper/hook/CI outcomes,
not just the standalone CLI. Confirm that failures remain failures through
shell pipelines and that advisory results stay visible. Inspect cache changes
and runtime on representative files. Retain logs with comparison coverage and
the source/tool/config versions needed to reproduce findings.

## Example: dismech's two stages

At [dismech's inspected revision](https://github.com/monarch-initiative/dismech/tree/6bd2810f2f896fd9aa05f8223f7f50caebe457b3),
the [pre-edit hook](https://github.com/monarch-initiative/dismech/blob/6bd2810f2f896fd9aa05f8223f7f50caebe457b3/.claude/hooks/validate_disorder_hook.py)
finds the edited file's worktree and calls `just validate-pre-edit` on candidate
content. The [recipes](https://github.com/monarch-initiative/dismech/blob/6bd2810f2f896fd9aa05f8223f7f50caebe457b3/project.justfile)
block schema and term failures at this stage, but report reference findings as
advisory with `--no-full-text`. Broader validation runs before merge.

The [reference wrapper](https://github.com/monarch-initiative/dismech/blob/6bd2810f2f896fd9aa05f8223f7f50caebe457b3/scripts/run_reference_validator.sh)
implements project-specific warning handling and appends a separate, advisory
snippet audit. Recipes explicitly select `conf/reference_validator_config.yaml`;
reading only the root dotfile would describe the wrong effective policy.
These are design examples, not a universal configuration to copy wholesale.
