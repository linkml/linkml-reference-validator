"""Europe PMC preprint full-text provider.

Preprints (Europe PMC ``SRC:PPR`` records) are not served by the PMC
``fullTextXML`` endpoint and their bodies are absent from PMC even when a PMCID
exists. The one route that reliably serves a preprint body is the Europe PMC
``fulltextRepo`` PDF: every ``SRC:PPR AND HAS_FT:Y`` core record carries a direct
``/fulltextRepo?pprId=...`` PDF URL in its ``fullTextUrlList``.

This provider resolves that URL from a DOI (or a ``SRC:PPR`` id) and returns it as
a ``FullTextLocation``. The downstream acquire/extract machinery validates the
``%PDF-`` magic bytes (a minority of records return a stale-filename error blob),
so an HTML/error response is rejected rather than fed to the PDF parser.
"""

import logging
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)

logger = logging.getLogger(__name__)

_EPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


@FullTextProviderRegistry.register
class EuropePMCPreprintProvider(FullTextProvider):
    """Locate preprint full text via the Europe PMC fulltextRepo PDF route.

    Examples:
        >>> EuropePMCPreprintProvider.name()
        'epmc_preprint'
    """

    @classmethod
    def name(cls) -> str:
        return "epmc_preprint"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        # Skip the Europe PMC round-trip for records the metadata source already
        # confirmed are peer-reviewed (is_preprint False). A None ("unknown", e.g.
        # a PMID or DataCite record) is still attempted.
        if ids.is_preprint is False:
            return None

        query = self._build_query(ids)
        if query is None:
            return None

        time.sleep(config.rate_limit_delay)
        params = {
            "query": query,
            "format": "json",
            "resultType": "core",
            "pageSize": "1",
            "email": config.email,
        }
        response = requests.get(_EPMC_SEARCH_URL, params=params, timeout=30)
        if response.status_code != 200:
            logger.debug(f"Europe PMC search returned {response.status_code} for {query}")
            return None

        result = self._first_ppr_result(response.json())
        if result is None:
            return None

        pdf_url = self._extract_pdf_url(result)
        if not pdf_url:
            return None

        return FullTextLocation(
            url=pdf_url,
            format_hint="pdf",
            oa_status="green",
            license=result.get("license"),
            version="preprint",
            provider="epmc_preprint",
        )

    def _build_query(self, ids: ReferenceIdentifiers) -> Optional[str]:
        """Build a Europe PMC query restricted to the preprint source.

        Examples:
            >>> p = EuropePMCPreprintProvider()
            >>> p._build_query(ReferenceIdentifiers(doi="10.1101/x"))
            'DOI:"10.1101/x" AND SRC:PPR'
            >>> p._build_query(ReferenceIdentifiers(pprid="PPR42"))
            'EXT_ID:PPR42 AND SRC:PPR'
            >>> p._build_query(ReferenceIdentifiers(pmid="123")) is None
            True
        """
        if ids.doi:
            return f'DOI:"{ids.doi}" AND SRC:PPR'
        if ids.pprid:
            return f"EXT_ID:{ids.pprid} AND SRC:PPR"
        return None

    def _first_ppr_result(self, data: dict) -> Optional[dict]:
        """Return the first ``SRC:PPR`` result, or None.

        Restricting to ``source == "PPR"`` guards against a peer-reviewed record
        sharing the DOI namespace being mistaken for a preprint.
        """
        results = data.get("resultList", {}).get("result", [])
        for result in results:
            if isinstance(result, dict) and result.get("source") == "PPR":
                return result
        return None

    def _extract_pdf_url(self, result: dict) -> Optional[str]:
        """Find the fulltextRepo PDF URL for a preprint core record.

        Returns the ``documentStyle == "pdf"`` entry from ``fullTextUrlList`` (the
        Europe PMC ``fulltextRepo`` PDF). The full URL must be taken verbatim from
        the record: the working endpoint includes a per-record ``fileName`` query
        parameter that cannot be reconstructed from the preprint id alone (a
        ``fileName``-less request 500s), so a record without a usable PDF entry
        yields no location rather than a guessed URL.
        """
        full_text_urls = result.get("fullTextUrlList", {}).get("fullTextUrl", [])
        for entry in full_text_urls:
            if not isinstance(entry, dict):
                continue
            url = entry.get("url")
            if not url:
                continue
            if entry.get("documentStyle") == "pdf" or "fulltextRepo" in url:
                return url

        return None
