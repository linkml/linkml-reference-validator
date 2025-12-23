# Adding a New Reference Source

The validator uses a plugin architecture that makes it easy to add support for new reference types. This guide shows how to create a custom reference source.

## Overview

Each reference source is a Python class that:

1. Inherits from `ReferenceSource`
2. Implements `prefix()` and `fetch()` methods
3. Registers itself with the `ReferenceSourceRegistry`

## Entrez Summary Sources (Recommended for NCBI IDs)

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

## Step 1: Create the Source Class

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

## Step 2: Implement the `fetch()` Method

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

## Step 3: Handle Errors Gracefully

Since you're interfacing with external systems, wrap API calls in try/except:

```python
def fetch(self, identifier: str, config: ReferenceValidationConfig) -> Optional[ReferenceContent]:
    try:
        response = requests.get(url, timeout=30)
        # ... process response
    except Exception as e:
        logger.warning(f"Failed to fetch arxiv:{identifier}: {e}")
        return None
```

## Step 4: Register the Source

The `@ReferenceSourceRegistry.register` decorator automatically registers your source when the module is imported.

Add the import to `src/linkml_reference_validator/etl/sources/__init__.py`:

```python
from linkml_reference_validator.etl.sources.arxiv import ArxivSource

__all__ = [
    # ... existing exports
    "ArxivSource",
]
```

## Step 5: Write Tests

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

## Optional: Custom `can_handle()` Method

The default `can_handle()` checks if the reference starts with your prefix. Override it for custom matching:

```python
@classmethod
def can_handle(cls, reference_id: str) -> bool:
    """Handle arxiv: references and bare arXiv IDs."""
    ref = reference_id.strip()
    # Match prefix
    if ref.lower().startswith("arxiv:"):
        return True
    # Match bare arXiv ID pattern (e.g., 2301.07041)
    import re
    return bool(re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", ref))
```

## Complete Example

Here's a complete implementation for a hypothetical "WikiData" source:

```python
# src/linkml_reference_validator/etl/sources/wikidata.py
"""WikiData reference source."""

import logging
import time
from typing import Optional

import requests

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)


@ReferenceSourceRegistry.register
class WikidataSource(ReferenceSource):
    """Fetch reference content from WikiData items."""

    @classmethod
    def prefix(cls) -> str:
        return "wikidata"

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        qid = identifier.strip().upper()
        if not qid.startswith("Q"):
            qid = f"Q{qid}"

        time.sleep(config.rate_limit_delay)

        url = f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json"

        try:
            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch wikidata:{qid}")
                return None

            data = response.json()
            entity = data["entities"].get(qid, {})

            # Extract label and description
            labels = entity.get("labels", {})
            descriptions = entity.get("descriptions", {})

            title = labels.get("en", {}).get("value", qid)
            description = descriptions.get("en", {}).get("value", "")

            return ReferenceContent(
                reference_id=f"wikidata:{qid}",
                title=title,
                content=description,
                content_type="wikidata_description",
            )

        except Exception as e:
            logger.warning(f"Error fetching wikidata:{qid}: {e}")
            return None
```

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

## Tips

- **Rate limiting**: Always respect `config.rate_limit_delay` between API calls
- **Error handling**: Return `None` on failures, don't raise exceptions
- **Logging**: Use `logger.warning()` for failures to aid debugging
- **Caching**: The `ReferenceFetcher` handles caching automatically - your source just needs to fetch
- **Testing**: Mock external API calls in tests to avoid network dependencies
