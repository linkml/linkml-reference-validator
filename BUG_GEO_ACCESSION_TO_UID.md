# Bug: GEOSource fails to fetch GEO datasets

## Summary

The `GEOSource` class in `linkml_reference_validator/etl/sources/entrez.py` cannot fetch GEO dataset metadata because it passes GSE accessions directly to `esummary`, but the GDS Entrez database requires numeric UIDs.

## Error Observed

```
WARNING:linkml_reference_validator.etl.sources.entrez:Failed to fetch Entrez summary for GEO:GSE67472: Invalid uid GSE67472 at position= 0
```

## Root Cause

The `EntrezSummarySource.fetch()` method calls:

```python
handle = Entrez.esummary(db=self.ENTREZ_DB, id=identifier)
```

For GEO, this becomes `esummary(db='gds', id='GSE67472')`, but the GDS database doesn't accept accession numbers as IDs - it requires numeric UIDs like `200067472`.

## Proof of Concept

```python
from Bio import Entrez
Entrez.email = 'test@example.com'

# This FAILS - accession not accepted as UID
handle = Entrez.esummary(db='gds', id='GSE67472')
# Error: Invalid uid GSE67472 at position=0

# This WORKS - use esearch first to get UID
handle = Entrez.esearch(db='gds', term='GSE67472[Accession]')
result = Entrez.read(handle)
handle.close()
# result['IdList'] = ['200067472', ...]

uid = result['IdList'][0]  # '200067472'

handle = Entrez.esummary(db='gds', id=uid)
summary = Entrez.read(handle)
handle.close()
print(summary[0].get('title'))
# Output: "Airway epithelial gene expression in asthma versus healthy controls"
```

## Proposed Fix

Override `fetch()` in `GEOSource` to add an `esearch` step that converts accessions to UIDs:

```python
@ReferenceSourceRegistry.register
class GEOSource(EntrezSummarySource):
    """Fetch GEO series and dataset summaries from Entrez."""

    PREFIX = "GEO"
    ENTREZ_DB = "gds"
    TITLE_FIELDS = ("title", "description", "summary")
    CONTENT_FIELDS = ("summary", "description", "title")
    ID_PATTERNS = (r"^GSE\d+$", r"^GDS\d+$")

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch GEO dataset metadata, converting accession to UID first."""
        Entrez.email = config.email
        time.sleep(config.rate_limit_delay)

        # Convert accession to UID via esearch
        uid = self._accession_to_uid(identifier)
        if not uid:
            logger.warning(f"Could not find GDS UID for {identifier}")
            return None

        # Now fetch summary with numeric UID
        handle = None
        try:
            handle = Entrez.esummary(db=self.ENTREZ_DB, id=uid)
            records = Entrez.read(handle)
        except Exception as exc:
            logger.warning(f"Failed to fetch Entrez summary for {self.prefix()}:{identifier}: {exc}")
            return None
        finally:
            if handle is not None:
                handle.close()

        record = self._extract_record(records)
        if not record:
            logger.warning(f"No Entrez summary found for {self.prefix()}:{identifier}")
            return None

        title = self._get_first_field_value(record, self.TITLE_FIELDS)
        content = self._get_first_field_value(record, self.CONTENT_FIELDS)
        content_type = "summary" if content else "unavailable"

        return ReferenceContent(
            reference_id=f"{self.prefix()}:{identifier}",
            title=title,
            content=content,
            content_type=content_type,
            metadata={"entrez_db": self.ENTREZ_DB, "entrez_uid": uid},
        )

    def _accession_to_uid(self, accession: str) -> Optional[str]:
        """Convert a GEO accession (GSE/GDS) to its Entrez UID."""
        handle = None
        try:
            handle = Entrez.esearch(db=self.ENTREZ_DB, term=f"{accession}[Accession]")
            result = Entrez.read(handle)
            if result.get("IdList"):
                return result["IdList"][0]
        except Exception as exc:
            logger.warning(f"esearch failed for {accession}: {exc}")
        finally:
            if handle is not None:
                handle.close()
        return None
```

## Testing

After the fix, validation should catch title mismatches like:

```yaml
# In kb/disorders/Asthma.yaml
datasets:
  - accession: geo:GSE67472
    title: xxxAirway epithelial gene expression in asthma versus healthy controls  # Wrong!
```

Expected validation error:
```
[ERROR] Title mismatch for geo:GSE67472
  Expected: "Airway epithelial gene expression in asthma versus healthy controls"
  Found: "xxxAirway epithelial gene expression in asthma versus healthy controls"
```
