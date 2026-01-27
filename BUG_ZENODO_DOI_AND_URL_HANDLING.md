# Bug Report: Zenodo DOIs and bare HTTPS URLs not handled

## Summary

Two related bugs prevent fetching Zenodo DOIs and bare HTTPS URLs:

1. **Zenodo DOIs return 404**: DOIs like `DOI:10.5281/zenodo.17993529` fail because the DOI source only queries Crossref, but Zenodo DOIs are registered with DataCite.

2. **Bare HTTPS URLs not recognized**: URLs like `https://doi.org/10.5281/zenodo.17993529` fail because the prefix parser extracts `https` as the prefix, which gets uppercased to `HTTPS` and doesn't match any source.

## Reproduction

```bash
# Both of these fail:
linkml-reference-validator lookup --no-cache https://doi.org/10.5281/zenodo.17993529
# Output: No source found for reference type: HTTPS://doi.org/10.5281/zenodo.17993529

linkml-reference-validator lookup --no-cache DOI:10.5281/zenodo.17993529
# Output: Failed to fetch DOI:10.5281/zenodo.17993529 - status 404
```

## Root Cause Analysis

### Bug 1: URL Prefix Handling

In `src/linkml_reference_validator/etl/reference_fetcher.py`:

```python
# Line 141 - regex parses https://example.com as:
#   prefix = "https"
#   identifier = "//example.com"
match = re.match(r"^([A-Za-z_]+)[:\s]+(.+)$", stripped)

# Lines 174-178 - prefix normalization uppercases non-file/url prefixes:
def _normalize_prefix(self, prefix: str) -> str:
    if prefix.lower() in ("file", "url"):
        return prefix.lower()
    return prefix.upper()  # "https" becomes "HTTPS"
```

No source is registered for `HTTPS:`, so lookup fails.

### Bug 2: Crossref-only DOI Resolution

In `src/linkml_reference_validator/etl/sources/doi.py`:

```python
# Line 72 - only queries Crossref API
url = f"https://api.crossref.org/works/{doi}"
```

Zenodo DOIs (prefix `10.5281/zenodo.*`) are registered with **DataCite**, not Crossref. Crossref returns 404 for these DOIs.

## Solution

### Fix 1: Handle bare HTTP/HTTPS URLs

In `reference_fetcher.py`, add detection for bare URLs before the prefix regex matching:

```python
def _parse_reference_id(self, reference_id: str) -> tuple[str, str]:
    stripped = reference_id.strip()

    # NEW: Handle bare URLs (http:// or https://)
    if stripped.lower().startswith(("http://", "https://")):
        return "url", stripped

    # Existing prefix:identifier parsing...
    match = re.match(r"^([A-Za-z_]+)[:\s]+(.+)$", stripped)
    # ... rest of method
```

### Fix 2: Add DataCite fallback for DOIs

In `doi.py`, try Crossref first, then fall back to DataCite if 404:

```python
def fetch(
    self, identifier: str, config: ReferenceValidationConfig
) -> Optional[ReferenceContent]:
    doi = identifier.strip()
    time.sleep(config.rate_limit_delay)

    # Try Crossref first
    result = self._fetch_from_crossref(doi, config)
    if result:
        return result

    # Fall back to DataCite (handles Zenodo, Figshare, etc.)
    return self._fetch_from_datacite(doi, config)

def _fetch_from_crossref(self, doi: str, config: ReferenceValidationConfig) -> Optional[ReferenceContent]:
    """Fetch from Crossref API."""
    url = f"https://api.crossref.org/works/{doi}"
    headers = {
        "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
    }

    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code != 200:
        logger.debug(f"Crossref returned {response.status_code} for DOI:{doi}, will try DataCite")
        return None

    data = response.json()
    if data.get("status") != "ok":
        return None

    message = data.get("message", {})
    return self._parse_crossref_response(doi, message)

def _fetch_from_datacite(self, doi: str, config: ReferenceValidationConfig) -> Optional[ReferenceContent]:
    """Fetch from DataCite API (handles Zenodo, Figshare, Dryad, etc.)."""
    url = f"https://api.datacite.org/dois/{doi}"
    headers = {
        "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
        "Accept": "application/json",
    }

    response = requests.get(url, headers=headers, timeout=30)
    if response.status_code != 200:
        logger.warning(f"Failed to fetch DOI:{doi} from both Crossref and DataCite")
        return None

    data = response.json()
    attributes = data.get("data", {}).get("attributes", {})

    # Extract title
    titles = attributes.get("titles", [])
    title = titles[0].get("title", "") if titles else ""

    # Extract authors
    authors = self._parse_datacite_creators(attributes.get("creators", []))

    # Extract year
    year = str(attributes.get("publicationYear", ""))

    # Extract abstract from descriptions
    abstract = ""
    for desc in attributes.get("descriptions", []):
        if desc.get("descriptionType") == "Abstract":
            abstract = desc.get("description", "")
            break

    # Publisher as journal equivalent
    publisher = attributes.get("publisher", "")

    return ReferenceContent(
        reference_id=f"DOI:{doi}",
        title=title,
        content=abstract if abstract else None,
        content_type="abstract_only" if abstract else "unavailable",
        authors=authors,
        journal=publisher,
        year=year,
        doi=doi,
    )

def _parse_datacite_creators(self, creators: list) -> list[str]:
    """Parse creator list from DataCite response."""
    result = []
    for creator in creators:
        # DataCite may have full name or given/family
        name = creator.get("name")
        if not name:
            given = creator.get("givenName", "")
            family = creator.get("familyName", "")
            if given and family:
                name = f"{given} {family}"
            elif family:
                name = family
            elif given:
                name = given
        if name:
            result.append(name)
    return result
```

## DataCite API Response Structure

The DataCite API at `https://api.datacite.org/dois/{doi}` returns:

```json
{
  "data": {
    "attributes": {
      "doi": "10.5281/zenodo.17993529",
      "titles": [{"title": "Gene Ontology Curators AI Workshop (Part 1)"}],
      "creators": [
        {
          "name": "Mungall, Christopher",
          "givenName": "Christopher",
          "familyName": "Mungall",
          "affiliation": [{"name": "Lawrence Berkeley National Laboratory"}]
        }
      ],
      "publicationYear": 2025,
      "publisher": "Zenodo",
      "descriptions": [
        {
          "description": "Workshop aims to equip curators with...",
          "descriptionType": "Abstract"
        }
      ]
    }
  }
}
```

## Test Cases

Add tests for both fixes:

```python
@pytest.mark.integration
def test_zenodo_doi():
    """Test that Zenodo DOIs are fetched via DataCite."""
    config = ReferenceValidationConfig()
    fetcher = ReferenceFetcher(config)
    ref = fetcher.fetch("DOI:10.5281/zenodo.17993529", force_refresh=True)
    assert ref is not None
    assert "Gene Ontology" in ref.title
    assert ref.year == "2025"

@pytest.mark.integration
def test_bare_https_url():
    """Test that bare HTTPS URLs are handled."""
    config = ReferenceValidationConfig()
    fetcher = ReferenceFetcher(config)
    ref = fetcher.fetch("https://example.com", force_refresh=True)
    assert ref is not None
    assert ref.reference_id == "url:https://example.com"

def test_parse_bare_url():
    """Test URL parsing for bare HTTP/HTTPS URLs."""
    config = ReferenceValidationConfig()
    fetcher = ReferenceFetcher(config)

    assert fetcher._parse_reference_id("https://example.com") == ("url", "https://example.com")
    assert fetcher._parse_reference_id("http://example.com/path") == ("url", "http://example.com/path")
    assert fetcher._parse_reference_id("url:https://example.com") == ("url", "https://example.com")
```

## Files to Modify

1. `src/linkml_reference_validator/etl/reference_fetcher.py` - Add bare URL detection
2. `src/linkml_reference_validator/etl/sources/doi.py` - Add DataCite fallback
3. `tests/test_reference_fetcher.py` - Add unit tests
4. `tests/test_doi_source.py` or similar - Add integration tests

## Verification

After fixes, these should work:

```bash
linkml-reference-validator lookup DOI:10.5281/zenodo.17993529
linkml-reference-validator lookup https://doi.org/10.5281/zenodo.17993529
linkml-reference-validator lookup https://zenodo.org/records/17993529
```
