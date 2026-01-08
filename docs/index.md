# linkml-reference-validator

**Validate quotes and excerpts against their source publications**

linkml-reference-validator ensures that text excerpts in your data accurately match their cited sources. It fetches references from PubMed/PMC, DOIs, local files, and URLs, then performs deterministic substring matching with support for editorial conventions like brackets `[...]` and ellipsis `...`.

## Key Features

- **Deterministic validation** - No fuzzy matching or AI hallucinations
- **Multiple reference sources** - PubMed, DOIs, local files, and URLs
- **Editorial convention support** - Handles `[clarifications]` and `...` ellipsis
- **Title validation** - Verify reference titles with `dcterms:title`
- **Multiple interfaces** - CLI for quick checks, Python API for integration
- **LinkML integration** - Validates data files with `linkml:excerpt` annotations
- **Smart caching** - Stores references locally to avoid repeated API calls

## Quick Links

- **[Quickstart](quickstart.md)** - Get started in 5 minutes
- **[CLI Reference](reference/cli.md)** - Complete command documentation
- **[How It Works](concepts/how-it-works.md)** - Understanding the validation process
- **[Editorial Conventions](concepts/editorial-conventions.md)** - Using brackets and ellipsis

## Tutorials

- [Getting Started (CLI)](notebooks/01_getting_started.ipynb) - Validate quotes from the command line
- [Advanced Usage (CLI)](notebooks/02_advanced_usage.ipynb) - Batch processing with LinkML schemas
- [Python API](notebooks/03_python_api.ipynb) - Programmatic usage for custom applications
