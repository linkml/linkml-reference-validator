# Adding a Custom Reference Source

This guide shows how to add support for new reference types. There are two approaches:

1. **YAML Configuration** (recommended) - Define sources via config files, no Python required
2. **Python Plugin** - Create a custom Python class for complex sources

## YAML Configuration (Recommended)

For sources that expose a JSON API, you can define them entirely through YAML configuration.
No Python code required, no pull requests needed.

### Understanding the Config Files

The validator uses **two separate config files**:

| File | Purpose |
|------|---------|
| `.linkml-reference-validator.yaml` | Main config: cache settings, skip_prefixes, rate limiting |
| `.linkml-reference-validator-sources.yaml` | Custom sources: JSON API definitions |

### Quick Start

Create a file named `.linkml-reference-validator-sources.yaml` in your project root:

```yaml
sources:
  MGNIFY:
    url_template: "https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}"
    fields:
      title: "$.data.attributes.study-name"
      content: "$.data.attributes.study-abstract"
    id_patterns:
      - "^MGYS\\d+$"
```

Now you can validate MGnify references:

```bash
linkml-reference-validator validate text \
  "The American Gut Project" \
  MGNIFY:MGYS00000596
```

### Configuration File Locations

Sources are loaded from these locations (in order of priority):

1. `~/.config/linkml-reference-validator/sources/*.yaml` (user-level)
2. `.linkml-reference-validator-sources.yaml` (project-level)
3. `sources:` section in your main config file

### Source Configuration Fields

| Field | Required | Description |
|-------|----------|-------------|
| `url_template` | Yes | API URL with `{id}` placeholder |
| `fields` | Yes | JSONPath expressions mapping to title, content, etc. |
| `id_patterns` | No | Regex patterns for bare ID matching |
| `headers` | No | HTTP headers (supports `${ENV_VAR}` interpolation) |
| `store_raw_response` | No | Store full API response in metadata |

### Field Mappings

Use JSONPath expressions (using [jsonpath-ng](https://github.com/h2non/jsonpath-ng) syntax) to extract fields from the API response:

```yaml
sources:
  EXAMPLE:
    url_template: "https://api.example.com/items/{id}"
    fields:
      title: "$.name"           # Simple field
      content: "$.description"   # Abstract/description
      year: "$.published_date"   # Optional: publication year
      authors: "$.authors[0].name"  # Optional: author info
```

Standard field names: `title`, `content`, `year`, `authors`, `journal`, `doi`

### JSONPath Examples

Common JSONPath patterns:

| Pattern | Description |
|---------|-------------|
| `$.title` | Top-level field |
| `$.data.attributes.name` | Nested field |
| `$.items[0]` | First array element |
| `$.results[*].name` | All names in array |

### ID Pattern Matching

Use `id_patterns` to match bare IDs (without prefix):

```yaml
sources:
  MGNIFY:
    url_template: "https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}"
    fields:
      title: "$.data.attributes.study-name"
      content: "$.data.attributes.study-abstract"
    id_patterns:
      - "^MGYS\\d+$"    # Matches MGYS00000596
      - "^MGY[A-Z]\\d+$"  # Matches MGYA123456
```

With this config, both formats work:
```bash
# With prefix
linkml-reference-validator validate text "quote" MGNIFY:MGYS00000596

# Bare ID (matched by pattern)
linkml-reference-validator validate text "quote" MGYS00000596
```

### Authentication

For APIs requiring authentication, use environment variables:

```yaml
sources:
  PRIVATE_API:
    url_template: "https://api.example.com/records/{id}"
    fields:
      title: "$.title"
      content: "$.body"
    headers:
      Authorization: "Bearer ${API_TOKEN}"
      X-API-Key: "${API_KEY}"
```

Set the environment variable before running:
```bash
export API_TOKEN="your-secret-token"
linkml-reference-validator validate text "quote" PRIVATE_API:123
```

### Storing Raw Response

Enable `store_raw_response` to capture the full API response in metadata:

```yaml
sources:
  MGNIFY:
    url_template: "https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}"
    fields:
      title: "$.data.attributes.study-name"
      content: "$.data.attributes.study-abstract"
    store_raw_response: true
```

The raw response is saved in the cache file's metadata for later inspection.

### Complete Example: MGnify

Here's a complete configuration for MGnify (EBI Metagenomics):

```yaml
# .linkml-reference-validator-sources.yaml
sources:
  MGNIFY:
    url_template: "https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}"
    id_patterns:
      - "^MGYS\\d+$"
    fields:
      title: "$.data.attributes.study-name"
      content: "$.data.attributes.study-abstract"
    headers:
      Accept: "application/json"
    store_raw_response: true
```

Test it:
```bash
# Cache the reference
linkml-reference-validator cache reference MGNIFY:MGYS00000596

# Validate a quote
linkml-reference-validator validate text \
  "The American Gut project is the largest crowdsourced citizen science project" \
  MGNIFY:MGYS00000596
```

### Complete Example: BioStudies

```yaml
sources:
  BIOSTUDIES:
    url_template: "https://www.ebi.ac.uk/biostudies/api/v1/studies/{id}"
    id_patterns:
      - "^S-[A-Z]+\\d+$"
    fields:
      title: "$.title"
      content: "$.description"
```

### Complete Setup: Both Config Files

Here's a typical project setup showing both config files working together.
The pattern is: **skip what you can't support, configure what you can**.

**`.linkml-reference-validator.yaml`** (main config):
```yaml
# Main validation settings
cache_dir: references_cache
rate_limit_delay: 0.5

# Skip prefixes that have no API or aren't needed
skip_prefixes:
  - SRA        # No abstract API available
  - ARRAYEXPRESS  # Deprecated, use BioStudies

# Note: Once you add a custom source for a prefix (like MGNIFY below),
# remove it from skip_prefixes - validation will now work properly.
```

**`.linkml-reference-validator-sources.yaml`** (custom sources):
```yaml
# Custom JSON API sources
sources:
  MGNIFY:
    url_template: "https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}"
    id_patterns:
      - "^MGYS\\d+$"
    fields:
      title: "$.data.attributes.study-name"
      content: "$.data.attributes.study-abstract"

  BIOSTUDIES:
    url_template: "https://www.ebi.ac.uk/biostudies/api/v1/studies/{id}"
    id_patterns:
      - "^S-[A-Z]+\\d+$"
    fields:
      title: "$.title"
      content: "$.description"
```

With this setup:
- `PMID:12345` - Uses built-in PubMed source
- `MGNIFY:MGYS00000596` - Uses your custom MGnify source
- `SRA:SRP123456` - Skipped (returns valid with INFO message)

### Finding the Right JSONPath

To figure out the correct JSONPath for a new API:

1. Fetch the API response directly:
   ```bash
   curl -s "https://api.example.com/items/123" | jq .
   ```

2. Identify the fields you need (title, description/abstract)

3. Write the JSONPath:
   - `$.fieldname` for top-level fields
   - `$.parent.child` for nested fields
   - `$.array[0]` for array elements

---

## Python Plugin (Advanced)

For sources requiring custom logic (XML parsing, multiple API calls, etc.), create a Python plugin.

### Overview

Each reference source is a Python class that:

1. Inherits from `ReferenceSource`
2. Implements `prefix()` and `fetch()` methods
3. Registers itself with the `ReferenceSourceRegistry`

### Entrez Summary Sources (Recommended for NCBI IDs)

If your source is backed by NCBI Entrez, prefer the built-in `EntrezSummarySource`
base class. It provides shared rate limiting, email configuration, and summary parsing.

```python
# src/linkml_reference_validator/etl/sources/my_entrez.py
"""Entrez summary source example."""

from linkml_reference_validator.etl.sources.entrez import EntrezSummarySource
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry


@ReferenceSourceRegistry.register
class ExampleEntrezSource(EntrezSummarySource):
    """Fetch summaries from an Entrez database."""

    PREFIX = "EXAMPLE"
    ENTREZ_DB = "example_db"
    TITLE_FIELDS = ("title", "name")
    CONTENT_FIELDS = ("summary", "description")
    ID_PATTERNS = (r"^EX\\d+$",)
```

`TITLE_FIELDS` and `CONTENT_FIELDS` are checked in order, and the first non-empty value
is used for the `ReferenceContent`.

### Step 1: Create the Source Class

Create a new file in `src/linkml_reference_validator/etl/sources/`:

```python
# src/linkml_reference_validator/etl/sources/arxiv.py
"""arXiv reference source."""

import logging
from typing import Optional

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)


@ReferenceSourceRegistry.register
class ArxivSource(ReferenceSource):
    """Fetch references from arXiv."""

    @classmethod
    def prefix(cls) -> str:
        """Return the prefix this source handles."""
        return "arxiv"

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch a paper from arXiv.

        Args:
            identifier: arXiv ID (e.g., '2301.07041')
            config: Configuration for fetching

        Returns:
            ReferenceContent if successful, None otherwise
        """
        # Your implementation here
        # Fetch from arXiv API, parse response, return ReferenceContent
        ...
```

### Step 2: Implement the `fetch()` Method

The `fetch()` method should:

1. Accept an identifier (without the prefix)
2. Fetch content from the external source
3. Return a `ReferenceContent` object or `None` on failure

```python
def fetch(
    self, identifier: str, config: ReferenceValidationConfig
) -> Optional[ReferenceContent]:
    """Fetch a paper from arXiv."""
    import requests
    import time

    arxiv_id = identifier.strip()

    # Respect rate limiting
    time.sleep(config.rate_limit_delay)

    # Fetch from arXiv API
    url = f"http://export.arxiv.org/api/query?id_list={arxiv_id}"
    response = requests.get(url, timeout=30)

    if response.status_code != 200:
        logger.warning(f"Failed to fetch arxiv:{arxiv_id}")
        return None

    # Parse the response (arXiv returns Atom XML)
    title, authors, abstract = self._parse_arxiv_response(response.text)

    return ReferenceContent(
        reference_id=f"arxiv:{arxiv_id}",
        title=title,
        content=abstract,
        content_type="abstract_only",
        authors=authors,
    )
```

### Step 3: Register the Source

Add the import to `src/linkml_reference_validator/etl/sources/__init__.py`:

```python
from linkml_reference_validator.etl.sources.arxiv import ArxivSource

__all__ = [
    # ... existing exports
    "ArxivSource",
]
```

### Step 4: Write Tests

Create tests in `tests/test_sources.py`:

```python
class TestArxivSource:
    """Tests for ArxivSource."""

    @pytest.fixture
    def source(self):
        return ArxivSource()

    def test_prefix(self, source):
        assert source.prefix() == "arxiv"

    def test_can_handle(self, source):
        assert source.can_handle("arxiv:2301.07041")
        assert not source.can_handle("PMID:12345")

    @patch("linkml_reference_validator.etl.sources.arxiv.requests.get")
    def test_fetch(self, mock_get, source, config):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """..."""  # Mock arXiv XML
        mock_get.return_value = mock_response

        result = source.fetch("2301.07041", config)

        assert result is not None
        assert result.reference_id == "arxiv:2301.07041"
```

---

## Reference: ReferenceContent Fields

The `ReferenceContent` model has these fields:

| Field | Type | Description |
|-------|------|-------------|
| `reference_id` | `str` | Full reference ID with prefix (e.g., `arxiv:2301.07041`) |
| `title` | `Optional[str]` | Title of the reference |
| `content` | `Optional[str]` | Main text content for validation |
| `content_type` | `str` | Type indicator (e.g., `abstract_only`, `full_text`) |
| `authors` | `Optional[list[str]]` | List of author names |
| `journal` | `Optional[str]` | Journal/venue name |
| `year` | `Optional[str]` | Publication year |
| `doi` | `Optional[str]` | DOI if available |
| `metadata` | `dict` | Additional metadata (raw API response, etc.) |

## Tips

- **Rate limiting**: Always respect `config.rate_limit_delay` between API calls
- **Error handling**: Return `None` on failures, don't raise exceptions
- **Logging**: Use `logger.warning()` for failures to aid debugging
- **Caching**: The `ReferenceFetcher` handles caching automatically - your source just needs to fetch
- **Testing**: Mock external API calls in tests to avoid network dependencies
