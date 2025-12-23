"""Entrez summary-based reference sources.

Provides a shared base class for NCBI Entrez E-utilities summary endpoints.

Examples:
    >>> from linkml_reference_validator.etl.sources.entrez import GEOSource
    >>> GEOSource.prefix()
    'GEO'
    >>> GEOSource.can_handle("geo:GSE12345")
    True
"""

import logging
import re
import time
from typing import Any, Optional

from Bio import Entrez  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)


class EntrezSummarySource(ReferenceSource):
    """Base class for Entrez summary-based sources.

    Subclasses define the Entrez database and field mappings for title/content.

    Examples:
        >>> class ExampleSource(EntrezSummarySource):
        ...     PREFIX = "EXAMPLE"
        ...     ENTREZ_DB = "example_db"
        ...     TITLE_FIELDS = ("title",)
        ...     CONTENT_FIELDS = ("summary",)
        >>> ExampleSource.prefix()
        'EXAMPLE'
    """

    PREFIX: str = ""
    ENTREZ_DB: str = ""
    TITLE_FIELDS: tuple[str, ...] = ()
    CONTENT_FIELDS: tuple[str, ...] = ()
    ID_PATTERNS: tuple[str, ...] = ()

    @classmethod
    def prefix(cls) -> str:
        """Return the prefix this source handles.

        Examples:
            >>> class ExampleSource(EntrezSummarySource):
            ...     PREFIX = "EXAMPLE"
            ...     ENTREZ_DB = "example_db"
            ...     TITLE_FIELDS = ("title",)
            ...     CONTENT_FIELDS = ("summary",)
            >>> ExampleSource.prefix()
            'EXAMPLE'
        """
        return cls.PREFIX

    @classmethod
    def can_handle(cls, reference_id: str) -> bool:
        """Check if this source can handle the given reference ID.

        Supports prefixed references and optional raw accessions.

        Examples:
            >>> class ExampleSource(EntrezSummarySource):
            ...     PREFIX = "EXAMPLE"
            ...     ENTREZ_DB = "example_db"
            ...     TITLE_FIELDS = ("title",)
            ...     CONTENT_FIELDS = ("summary",)
            ...     ID_PATTERNS = (r"^EX\\d+$",)
            >>> ExampleSource.can_handle("EXAMPLE:EX123")
            True
            >>> ExampleSource.can_handle("EX123")
            True
        """
        if super().can_handle(reference_id):
            return True
        if cls.ID_PATTERNS:
            for pattern in cls.ID_PATTERNS:
                if re.match(pattern, reference_id, re.IGNORECASE):
                    return True
        return False

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch a summary record from an Entrez database.

        Args:
            identifier: Identifier or accession
            config: Configuration including rate limiting and email

        Returns:
            ReferenceContent if successful, None otherwise
        """
        if not self.ENTREZ_DB:
            logger.warning("EntrezSummarySource missing ENTREZ_DB configuration")
            return None

        Entrez.email = config.email  # type: ignore
        time.sleep(config.rate_limit_delay)

        handle = None
        try:
            handle = Entrez.esummary(db=self.ENTREZ_DB, id=identifier)
            records = Entrez.read(handle)
        except Exception as exc:
            logger.warning(
                f"Failed to fetch Entrez summary for {self.prefix()}:{identifier}: {exc}"
            )
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
            metadata={"entrez_db": self.ENTREZ_DB},
        )

    def _extract_record(self, records: Any) -> Optional[dict[str, Any]]:
        """Extract the first summary record from Entrez results."""
        if isinstance(records, list):
            if records:
                return records[0]
            return None

        if isinstance(records, dict):
            docset = records.get("DocumentSummarySet")
            if isinstance(docset, dict):
                docs = docset.get("DocumentSummary")
                if isinstance(docs, list) and docs:
                    return docs[0]
                if isinstance(docs, dict):
                    return docs
            return records

        return None

    def _get_first_field_value(
        self, record: dict[str, Any], field_names: tuple[str, ...]
    ) -> Optional[str]:
        """Return the first non-empty value from a record for the given fields."""
        if not field_names:
            return None

        normalized_keys = {key.lower(): key for key in record.keys()}
        for name in field_names:
            record_key = normalized_keys.get(name.lower(), name)
            value = record.get(record_key)
            text = self._normalize_text(value)
            if text:
                return text

        return None

    def _normalize_text(self, value: Any) -> Optional[str]:
        """Normalize summary field values into a string."""
        if value is None:
            return None
        if isinstance(value, (list, tuple)):
            items = [str(item) for item in value if item]
            return "; ".join(items) if items else None
        text = str(value).strip()
        return text if text else None


@ReferenceSourceRegistry.register
class GEOSource(EntrezSummarySource):
    """Fetch GEO series and dataset summaries from Entrez.

    Examples:
        >>> GEOSource.prefix()
        'GEO'
        >>> GEOSource.can_handle("geo:GSE12345")
        True
    """

    PREFIX = "GEO"
    ENTREZ_DB = "gds"
    TITLE_FIELDS = ("title", "description", "summary")
    CONTENT_FIELDS = ("summary", "description", "title")
    ID_PATTERNS = (r"^GSE\\d+$", r"^GDS\\d+$")


@ReferenceSourceRegistry.register
class BioProjectSource(EntrezSummarySource):
    """Fetch BioProject summaries from Entrez.

    Examples:
        >>> BioProjectSource.prefix()
        'BIOPROJECT'
        >>> BioProjectSource.can_handle("bioproject:PRJNA000001")
        True
    """

    PREFIX = "BIOPROJECT"
    ENTREZ_DB = "bioproject"
    TITLE_FIELDS = ("Project_Title", "Project_Name", "title")
    CONTENT_FIELDS = ("Project_Description", "Description", "title")
    ID_PATTERNS = (r"^PRJ[EDN][A-Z]?\\d+$",)


@ReferenceSourceRegistry.register
class BioSampleSource(EntrezSummarySource):
    """Fetch BioSample summaries from Entrez.

    Examples:
        >>> BioSampleSource.prefix()
        'BIOSAMPLE'
        >>> BioSampleSource.can_handle("biosample:SAMN00000001")
        True
    """

    PREFIX = "BIOSAMPLE"
    ENTREZ_DB = "biosample"
    TITLE_FIELDS = ("Title", "title", "Description")
    CONTENT_FIELDS = ("Description", "Title", "title")
    ID_PATTERNS = (r"^SAM[END]\\d+$",)
