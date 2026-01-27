# Content Types

When fetching references, the validator tracks what type of content was retrieved using the `content_type` field. This is important because validation reliability depends on having access to the right content - an excerpt from a paper's Methods section won't be found if only the abstract is available.

## Content Type Values

| Value | Source(s) | Description |
|-------|-----------|-------------|
| `full_text_xml` | PMID (via PMC) | Full text retrieved from PubMed Central as XML |
| `full_text_html` | PMID (via PMC) | Full text retrieved from PubMed Central as HTML (fallback) |
| `abstract_only` | PMID, DOI | Only the abstract was available |
| `summary` | GEO, BioProject, BioSample, ClinicalTrials | Database summary/description field |
| `local_file` | file: | Content read from local filesystem |
| `url` | url: | Content fetched from web URL |
| `unavailable` | Any | No content could be retrieved |

### Internal Values (not typically seen by users)

| Value | Meaning |
|-------|---------|
| `no_pmc` | PMID has no corresponding PMC ID |
| `pmc_restricted` | PMC entry exists but content is restricted |
| `unknown` | Default value (content type not determined) |

## How Content Type Affects Validation

### Full Text Available (`full_text_xml`, `full_text_html`)

When full text is available, validation is most reliable. The content includes:

- Abstract
- Introduction
- Methods
- Results
- Discussion
- References

Excerpts from any section can be validated.

### Abstract Only (`abstract_only`)

When only the abstract is available:

- Validation works for text from the abstract
- **Validation will fail for excerpts from other sections**
- Error messages note this limitation: `(note: only abstract available for PMID:nnn, full text may contain this excerpt)`

This is common for PMIDs without open-access PMC versions.

### Summary (`summary`)

For database records (GEO, BioProject, etc.), the "summary" or "description" field is used. This is typically a brief description, not a full publication.

### Unavailable (`unavailable`)

No content was retrieved. Validation will fail with a clear error message.

## PMID Full Text Cascade

For PMID references, the validator automatically attempts to get the best content available:

```mermaid
flowchart TD
    A[Fetch PMID] --> B[Get abstract via Entrez]
    B --> C{Has PMC ID?}
    C -->|No| D[Return abstract_only]
    C -->|Yes| E[Try PMC XML]
    E -->|Success| F[Return full_text_xml]
    E -->|Fail| G[Try PMC HTML]
    G -->|Success| H[Return full_text_html]
    G -->|Fail/Restricted| I{Has abstract?}
    I -->|Yes| D
    I -->|No| J[Return unavailable]
```

When full text is retrieved, it's **concatenated with the abstract** to provide maximum coverage.

## Checking Content Type

### In Cache Files

Cached references store content type in YAML frontmatter:

```yaml
---
reference_id: PMID:16888623
title: Example Article
content_type: abstract_only
---
```

### Via CLI

```bash
linkml-reference-validator cache lookup PMID:16888623 --content
```

Output includes:
```
content_type: abstract_only
```

### In Validation Results

When validation fails and only abstract was available, the error message includes context:

```
Text part not found as substring: 'excerpt from methods section'
(note: only abstract available for PMID:16888623, full text may contain this excerpt)
```

## Strategies When Full Text Unavailable

If validation fails due to abstract-only content:

1. **Check for PMC version**: Search [PubMed Central](https://www.ncbi.nlm.nih.gov/pmc/) for the article - if available, use `PMC:` prefix instead of `PMID:`

2. **Use local file**: If you have the PDF/text, save as markdown and reference with `file:./path/to/paper.md`

3. **Use URL**: If the full text is freely available online, use `url:https://...`

4. **Remove the excerpt**: If the excerpt can't be verified, consider removing it from your data

5. **Accept the limitation**: Document that certain excerpts couldn't be verified due to access limitations

See [Using Local Files and URLs](../how-to/use-local-files-and-urls.md) for detailed guidance on alternatives.

## Reference Metadata

Beyond the main content, the validator extracts additional metadata from references:

### Keywords

The `keywords` field contains subject terms or tags from the source:

| Source | Keyword Type | Example |
|--------|--------------|---------|
| PMID | MeSH terms | `Adaptor Proteins, Signal Transducing/metabolism` |
| DOI (Crossref) | Subjects | `General Chemistry`, `Biochemistry` |
| DOI (DataCite) | Subjects | `Climate Change`, `Bioinformatics` |

MeSH (Medical Subject Headings) terms from PubMed are particularly valuable for biomedical literature, providing standardized vocabulary with qualifier subheadings (e.g., `/metabolism`, `/genetics`).

**Example cache file with keywords:**
```yaml
---
reference_id: PMID:33505029
title: Genomic mechanisms of climate adaptation...
keywords:
- Acclimatization/genetics
- Biofuels
- Genetic Introgression
- Genome, Plant/genetics
content_type: abstract_only
---
```

**Viewing keywords via CLI:**
```bash
linkml-reference-validator lookup PMID:33505029 --format text
```

Output:
```
Reference: PMID:33505029
Title: Genomic mechanisms of climate adaptation...
Keywords: Acclimatization/genetics, Biofuels, Genetic Introgression, ...
```

### Supplementary Files

For repository DOIs (Zenodo, etc.), the `supplementary_files` field lists associated files:

```yaml
---
reference_id: DOI:10.5281/zenodo.7961621
supplementary_files:
  - filename: data_analysis.xlsx
    download_url: https://zenodo.org/api/records/7961621/files/data_analysis.xlsx/content
    size_bytes: 123456
    checksum: md5:88c66d378d886fea4969949c5877802f
---
```

See [Validating DOIs](../how-to/validate-dois.md#supported-repository-dois) for details on supplementary files.
