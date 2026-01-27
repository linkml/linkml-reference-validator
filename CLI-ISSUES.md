# CLI Issues

## 1) `validate data` summary label is misleading

**Current behavior**
The CLI prints:
```
Validation Summary:
  Total checks: <N>
```
where `<N>` is the **number of issues** (`len(all_results)`), not the number of checks performed. This makes successful runs look like they performed zero checks (e.g., “Total checks: 0”), which is confusing.

**Where**
`linkml_reference_validator/cli/validate.py` (near the end of `validate data` command).

**Repro**
Run with a file that has valid evidence/snippets and get:
```
Validation Summary:
  Total checks: 0
  All validations passed!
```

**Suggested fix**
Either:
- Rename the label to **“Total issues”**, or
- Add two counters:
  - **Checks performed** (number of excerpt/reference pairs found)
  - **Issues found** (`len(all_results)`) 

This would make the summary accurate and less surprising.
