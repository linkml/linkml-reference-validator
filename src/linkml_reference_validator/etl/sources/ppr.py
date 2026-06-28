"""Preprint (Europe PMC ``SRC:PPR``) reference source.

Resolves a preprint by its Europe PMC preprint id (``PPR:PPR123456``) to metadata
via the Europe PMC REST search API. The ``SRC:PPR`` universe is the preprint
firehose: DOI-bearing but without PMIDs, so these records are not reachable
through the normal PMID path. Records resolved here are always marked as
preprints (``is_preprint`` / ``peer_review_status``) so downstream knowledge bases
can apply "not sole support" policies.

Preprint *full text* is fetched separately by the ``epmc_preprint`` full-text
provider (via the DOI/PPR id crosswalk); this source only supplies metadata and
the abstract.

Examples:
    >>> from linkml_reference_validator.etl.sources.ppr import PPRSource
    >>> PPRSource.prefix()
    'PPR'
    >>> PPRSource.can_handle("PPR:PPR123456")
    True
    >>> PPRSource.can_handle("DOI:10.1101/x")
    False
"""

import logging
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)

_EPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


@ReferenceSourceRegistry.register
class PPRSource(ReferenceSource):
    """Fetch preprint metadata from Europe PMC by ``SRC:PPR`` id.

    Examples:
        >>> source = PPRSource()
        >>> source.prefix()
        'PPR'
    """

    @classmethod
    def prefix(cls) -> str:
        """Return 'PPR' prefix.

        Examples:
            >>> PPRSource.prefix()
            'PPR'
        """
        return "PPR"

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch preprint metadata for a Europe PMC preprint id.

        Args:
            identifier: Preprint id (with or without the leading ``PPR``).
            config: Configuration including rate limiting and email.

        Returns:
            ReferenceContent marked as a preprint, or None if not found.
        """
        ppr_id = self._normalize_id(identifier)
        time.sleep(config.rate_limit_delay)

        params = {
            "query": f"EXT_ID:{ppr_id} AND SRC:PPR",
            "format": "json",
            "resultType": "core",
            "pageSize": "1",
            "email": config.email,
        }
        # External system boundary: a network blip or a non-JSON body must yield a
        # graceful skip (None) for this one reference, as the PMID and
        # ClinicalTrials sources do, rather than aborting the whole validation run.
        try:
            response = requests.get(_EPMC_SEARCH_URL, params=params, timeout=30)
            if response.status_code != 200:
                logger.warning(f"Europe PMC returned {response.status_code} for PPR:{ppr_id}")
                return None
            data = response.json()
        except Exception as exc:
            logger.warning(f"Failed to fetch PPR:{ppr_id} from Europe PMC: {exc}")
            return None

        result = self._first_ppr_result(data)
        if result is None:
            logger.warning(f"No Europe PMC preprint found for PPR:{ppr_id}")
            return None

        abstract = result.get("abstractText") or None
        doi = result.get("doi") or None
        year = str(result.get("pubYear")) if result.get("pubYear") else None

        return ReferenceContent(
            reference_id=f"PPR:{ppr_id}",
            title=result.get("title") or None,
            content=abstract,
            content_type="abstract_only" if abstract else "unavailable",
            authors=self._parse_authors(result.get("authorString")),
            journal=self._extract_journal(result),
            year=year,
            doi=doi,
            is_preprint=True,
            peer_review_status="preprint",
        )

    def _normalize_id(self, identifier: str) -> str:
        """Normalize a preprint id to Europe PMC's ``PPR`` form.

        Examples:
            >>> source = PPRSource()
            >>> source._normalize_id("PPR123456")
            'PPR123456'
            >>> source._normalize_id("123456")
            'PPR123456'
            >>> source._normalize_id("ppr123456")
            'PPR123456'
        """
        stripped = identifier.strip()
        if stripped.upper().startswith("PPR"):
            return "PPR" + stripped[3:]
        return f"PPR{stripped}"

    def _first_ppr_result(self, data: dict) -> Optional[dict]:
        """Return the first ``SRC:PPR`` result, or None."""
        results = data.get("resultList", {}).get("result", [])
        for result in results:
            if isinstance(result, dict) and result.get("source") == "PPR":
                return result
        return None

    def _parse_authors(self, author_string: Optional[str]) -> Optional[list[str]]:
        """Split a Europe PMC ``authorString`` into individual names.

        Examples:
            >>> source = PPRSource()
            >>> source._parse_authors("Smith J, Doe A.")
            ['Smith J', 'Doe A']
            >>> source._parse_authors(None) is None
            True
        """
        if not author_string:
            return None
        names = [name.strip().rstrip(".").strip() for name in author_string.split(",")]
        names = [name for name in names if name]
        return names or None

    def _extract_journal(self, result: dict) -> Optional[str]:
        """Extract the hosting server name (e.g. bioRxiv) from journalInfo."""
        journal = result.get("journalInfo", {}).get("journal", {}).get("title")
        return journal or None
