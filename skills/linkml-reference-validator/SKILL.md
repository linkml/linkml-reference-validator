---
name: linkml-reference-validator
description: Set up, configure, and troubleshoot LinkML Reference Validator (LRV) as deterministic reference QC in repository hooks and CI. Use when interpreting quote or title failures, diagnosing unchecked evidence and cache coverage, or configuring schema extraction, sources, and matching policy.
---

# Work with reference QC

LRV performs deterministic quote and title checks against retrieved source
content. Run those checks through repository automation. The agent's role is to
integrate the checker, explain findings, and make evidence-based corrections.
Maintainers define required coverage and exception policy; curators decide
whether the evidence supports the scientific claim. A matching quote settles
neither its relevance nor the truth of the claim.

A passing automated check needs no agent reenactment. Apply scientific review
when curating or reviewing evidence, rather than rereading every source on each
QC run.

## Establish the validation context

Read the project's guidance, validation recipe or wrapper, schema, explicit
config, dependency lock, and existing hook/CI output. Identify the affected
files, target class, source cache, and whether this check is blocking or
advisory. Use the existing project command: a wrapper may encode policy absent
from a bare CLI invocation. Reproduce a finding on the affected file with the
same inputs before changing data; avoid repeated whole-corpus retrieval.

- For a new gate or hook/CI changes, read [Guardrail setup](references/guardrails.md).
- For extraction, retrieval, cache, or matching changes, read
  [Configuration and targeted diagnosis](references/configuration.md).

Installing this skill supplies instructions; it does not activate a hook,
install LRV, or establish a required CI check.

## Interpret the result before repairing it

| Finding | Agent's next step |
| --- | --- |
| Quote matched | Report source matching as passed. During evidence review, assess the attached claim, population, and direction of effect separately. |
| Quote did not match | Compare the exact input with the retrieved content. Distinguish paraphrase, wrong citation, normalization, and missing full text. |
| Title mismatch | Check identifier and source metadata together; changing the title to fit the wrong paper hides the real error. |
| Source unavailable or prefix skipped | Report evidence as unchecked. Diagnose retrieval or source configuration; do not label the quote fabricated. |
| Zero comparisons or unexpectedly low coverage | Inspect schema annotations, target class, missing evidence, file selection, and skip policy. Exit 0 does not establish coverage. |
| Crash or invocation error | Repair the execution/configuration problem before drawing conclusions about the evidence. |

An abstract-only record cannot establish that a quotation is absent from the
full paper. Keep matched, failed, skipped, and unavailable evidence distinct;
read coverage diagnostics alongside the exit status. Advisory output from a
hook is not completion of the repository's required checks.

## Correct the cause and close the loop

When fixing evidence, inspect the source and the intended claim together.
Transcribe a supported quote accurately; never invent wording or swap citations
solely to obtain a pass. Preserve the source cache as evidence rather than
editing it to match the submitted quote. Review any automated repair suggestion
against the paper and schema before applying it.

For configuration work, explain which records become checked or unchecked and
demonstrate the intended behavior with representative passing and failing
examples. Preserve established policy during routine repairs: adding a skipped
prefix or lowering retrieval severity changes the QC contract.

Rerun the affected check after corrections and the required repository checks
before delivery. Report the file/field, reference ID, diagnosis, correction,
command and outcome, source coverage, and any evidence still unchecked. Surface
unresolved scientific interpretation or policy choices to the human curator.
