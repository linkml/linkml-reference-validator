# Splitting supporting text in Python

The public import is:

```python
from linkml_reference_validator.matching import split_supporting_text

parts = split_supporting_text("protein [important] functions ... in cells")
assert parts == ["protein functions", "in cells"]
```

This pure helper needs no validator, fetcher, cache, or network access. The
validator's existing `_split_query` method delegates to it, so offline snippet
reports and validation share the same splitting implementation.

## Contract

`split_supporting_text(text, literal_bracket_patterns=()) -> list[str]`

- Replace editorial bracketed text with a space.
- Split on runs of **two or more ASCII periods**, including `..`, `...`, and
  `....`. A single period and the Unicode ellipsis `…` remain literal.
- Collapse whitespace within each part, trim it, and discard empty parts.
- Return parts in input order; empty text or only editorial notes/separators
  produces `[]`.

The helper performs splitting only; it does not normalize case or punctuation,
check a reference, or enforce validation policies such as minimum excerpt length.
An empty list contains no quoted evidence and should not be treated as a verified
snippet.

Bracket parsing retains the existing non-nested, single-line regex behavior:
`[` matches through the next `]` on the same line. Unmatched brackets remain.
Periods inside preserved brackets still act as separators.

## Literal scientific notation and configuration

The default is an empty pattern sequence, matching
`ReferenceValidationConfig.literal_bracket_patterns`. **No scientific notation is
preserved automatically.** Each supplied regex is searched against the content
inside brackets, without the brackets themselves. Any match preserves the whole
bracketed text; otherwise it is removed. Supplied patterns are the complete set
of exceptions, with no implicit patterns added.

```python
from linkml_reference_validator.models import ReferenceValidationConfig

config = ReferenceValidationConfig(literal_bracket_patterns=[r"\d", r"[()+]"])
parts = split_supporting_text(
    "binds [2Fe-2S] [important] ... exports [poly(A)+] RNA",
    literal_bracket_patterns=config.literal_bracket_patterns,
)
assert parts == ["binds [2Fe-2S]", "exports [poly(A)+] RNA"]
```

For repeated calls, pass a sequence of compiled string regexes to reuse them.
Compiled flags are preserved; invalid regex strings raise `re.error`.

```python
import re

patterns = tuple(re.compile(p) for p in config.literal_bracket_patterns)
assert split_supporting_text("[2Fe-2S] ... [poly(A)+]", patterns) == [
    "[2Fe-2S]", "[poly(A)+]"
]
```

See [Editorial Conventions](../concepts/editorial-conventions.md) for authoring
examples.
