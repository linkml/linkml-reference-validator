# Editorial Conventions

How to use brackets and ellipsis in supporting text quotes.

## Overview

When citing scientific text, you often need to:
- Add clarifications that weren't in the original
- Omit portions of text between relevant parts

linkml-reference-validator supports standard editorial conventions for these cases.

## Square Brackets `[...]`

Use square brackets to insert **editorial clarifications** that should be ignored during validation.

### Basic Usage

**Reference text:**
```
"MUC1 oncoprotein blocks nuclear targeting of c-Abl"
```

**Your quote with clarification:**
```
"MUC1 [mucin 1] oncoprotein blocks nuclear targeting of c-Abl"
```

The `[mucin 1]` is ignored during matching, so this validates successfully.

### Common Uses

#### Expanding Abbreviations

```
Reference: "TP53 functions in cell cycle regulation"
Your quote: "TP53 [tumor protein p53] functions in cell cycle regulation"
```

#### Adding Context

```
Reference: "The protein blocks nuclear targeting"
Your quote: "The protein [MUC1] blocks nuclear targeting"
```

#### Clarifying Pronouns

```
Reference: "It regulates transcription"
Your quote: "It [BRCA1] regulates transcription"
```

### Multiple Brackets

You can use multiple editorial notes in one quote:

```
"The protein [MUC1] blocks nuclear targeting of c-Abl [a tyrosine kinase]"
```

Both bracketed portions are removed before matching.

### Nested Brackets

Nested brackets are not recommended and may not work as expected:

```
❌ "MUC1 [mucin 1 [a membrane protein]] blocks targeting"
✅ "MUC1 [mucin 1, a membrane protein] blocks targeting"
```

## Ellipsis `...`

Use ellipsis (three dots) to indicate **omitted text** between parts of a quote.

### Basic Usage

**Reference text:**
```
"MUC1 oncoprotein blocks nuclear targeting of c-Abl in the apoptotic response"
```

**Your quote with ellipsis:**
```
"MUC1 oncoprotein ... apoptotic response"
```

Both parts must exist in the reference.

### How It Works

The validator:
1. Splits on `...` → `["MUC1 oncoprotein", "apoptotic response"]`
2. Normalizes each part
3. Checks that both appear in the reference content
4. Returns valid only if **both** parts are found

### Common Uses

#### Removing Middle Content

```
Reference: "BRCA1 plays a critical role in DNA repair mechanisms through homologous recombination"
Your quote: "BRCA1 plays a critical role in DNA repair ... homologous recombination"
```

#### Extracting Key Points

```
Reference: "The MUC1 cytoplasmic domain, upon phosphorylation by Src kinases, interacts with β-catenin"
Your quote: "MUC1 cytoplasmic domain ... interacts with β-catenin"
```

### Multiple Ellipses

You can use multiple ellipses:

```
"MUC1 ... blocks nuclear targeting ... apoptotic response"
```

This creates three parts that must all be found.

### Order Matters

The parts must appear in the reference in the same order:

```
Reference: "A then B then C"

✅ "A ... C"        # Valid: A before C
✅ "A ... B ... C"  # Valid: correct order
❌ "C ... A"        # Invalid: wrong order
```

## Combining Conventions

You can combine brackets and ellipsis:

```
"MUC1 [mucin 1] oncoprotein ... c-Abl [a tyrosine kinase]"
```

Processing order:
1. Remove brackets: `"MUC1 oncoprotein ... c-Abl"`
2. Split on ellipsis: `["MUC1 oncoprotein", "c-Abl"]`
3. Normalize and match each part

## Best Practices

### Do ✅

- Use brackets for actual editorial clarifications
- Use ellipsis only when omitting substantial text
- Keep your quotes as close to the original as practical
- Use these sparingly - direct quotes are clearer

### Don't ❌

- Don't use brackets for emphasis or comments
- Don't use ellipsis for single word omissions
- Don't change the meaning with your insertions
- Don't nest brackets or use non-standard notation

### Examples

**Good usage:**
```yaml
supporting_text: BRCA1 [breast cancer 1] plays a role in DNA repair
reference: PMID:12345678
```

**Questionable usage:**
```yaml
supporting_text: BRCA1 [IMPORTANT!] plays a role in DNA repair  # ❌ Not editorial
supporting_text: BRCA1 plays a ... in DNA repair                # ❌ Unnecessary ellipsis
```

## Command Line Examples

### With Brackets

```bash
linkml-reference-validator validate text \
  'MUC1 [mucin 1] oncoprotein blocks nuclear targeting' \
  PMID:16888623
```

Note: Use single quotes in shell to avoid bracket expansion.

### With Ellipsis

```bash
linkml-reference-validator validate text \
  "MUC1 oncoprotein ... apoptotic response" \
  PMID:16888623
```

### Combined

```bash
linkml-reference-validator validate text \
  'MUC1 [an oncoprotein] blocks ... c-Abl [a tyrosine kinase]' \
  PMID:16888623
```

## In Data Files

Editorial conventions work the same in data files:

```yaml
- gene_symbol: MUC1
  function: oncoprotein blocking c-Abl
  supporting_text: MUC1 [mucin 1] oncoprotein ... c-Abl
  reference: PMID:16888623
```

## Technical Details

### Normalization Order

1. Remove everything inside `[...]`
2. Split on `...` if present
3. For each part:
   - Lowercase
   - Remove punctuation
   - Collapse whitespace
4. Match normalized parts against normalized reference

### Regular Expressions

Brackets: `\[([^\]]*)\]` (removes content and brackets)
Ellipsis: `\.\.\.` (splits on three dots exactly)

Note: `..` (two dots) and `....` (four dots) are NOT treated as ellipsis.

## See Also

- [How It Works](how-it-works.md) - Understanding the validation process
- [Tutorial 1](../notebooks/01_getting_started.ipynb) - Examples in practice
