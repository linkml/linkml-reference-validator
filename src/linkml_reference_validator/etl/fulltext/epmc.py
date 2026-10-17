"""Europe PMC full-text provider.

Fetches full-text XML for open access articles from the Europe PMC API.
This complements EuropePMCPreprintProvider, which handles preprints only.
"""

import logging
import time
from typing import Optional

import requests  # type: ignore
from bs4 import BeautifulSoup  # type: ignore

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)
from linkml_reference_validator.etl.extract import MIN_FULLTEXT_CHARS

logger = logging.getLogger(__name__)

EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPEPMC_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{id}/fullTextXML"


@FullTextProviderRegistry.register
class EuropePMCFullTextProvider(FullTextProvider):
    """Fetch full-text XML for open access articles from Europe PMC.

    Queries the Europe PMC search API to find open access articles by PMID,
    then fetches full-text XML when available. This provider handles regular
    OA articles; preprints are handled by EuropePMCPreprintProvider.

    Examples:
        >>> EuropePMCFullTextProvider.name()
        'epmc'
    """

    @classmethod
    def name(cls) -> str:
        return "epmc"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        if not ids.pmid:
            return None

        time.sleep(config.rate_limit_delay)

        params = {
            "query": f"EXT_ID:{ids.pmid} AND SRC:MED",
            "format": "json",
            "resultType": "core",
            "pageSize": "1",
            "email": config.email,
        }

        try:
            response = requests.get(EUROPEPMC_SEARCH_URL, params=params, timeout=30)
        except requests.RequestException as exc:
            logger.debug(f"Europe PMC search failed for PMID:{ids.pmid}: {exc}")
            return None

        if response.status_code != 200:
            logger.debug(f"Europe PMC returned {response.status_code} for PMID:{ids.pmid}")
            return None

        try:
            data = response.json()
        except ValueError:
            logger.debug(f"Invalid JSON from Europe PMC for PMID:{ids.pmid}")
            return None

        result = self._find_oa_result(data)
        if not result:
            return None

        pmcid = result.get("pmcid")
        if not pmcid:
            logger.debug(f"No PMCID in Europe PMC result for PMID:{ids.pmid}")
            return None

        text = self._fetch_fulltext_xml(pmcid, config)
        if not text or len(text) < MIN_FULLTEXT_CHARS:
            return None

        return FullTextLocation(
            text=text,
            format_hint="text",
            oa_status="green",
            license=result.get("license"),
            provider="epmc",
        )

    def _find_oa_result(self, data: dict) -> Optional[dict]:
        """Find an open access result from search response.

        Args:
            data: Europe PMC search response JSON

        Returns:
            First OA result dict, or None
        """
        results = data.get("resultList", {}).get("result", [])
        for result in results:
            if not isinstance(result, dict):
                continue
            if result.get("isOpenAccess") == "Y":
                return result
        return None

    def _fetch_fulltext_xml(
        self, pmcid: str, config: ReferenceValidationConfig
    ) -> Optional[str]:
        """Fetch and extract text from Europe PMC fullTextXML endpoint.

        Args:
            pmcid: PMC ID (with or without PMC prefix)
            config: Configuration for rate limiting

        Returns:
            Extracted body text, or None
        """
        pmcid_clean = pmcid.replace("PMC", "")
        url = EUROPEPMC_FULLTEXT_URL.format(source="PMC", id=pmcid_clean)

        time.sleep(config.rate_limit_delay)

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.debug(f"Europe PMC fulltext fetch failed for {pmcid}: {exc}")
            return None

        if response.status_code != 200:
            logger.debug(f"Europe PMC fulltext returned {response.status_code} for {pmcid}")
            return None

        return self._extract_body_text(response.text)

    def _extract_body_text(self, xml_content: str) -> Optional[str]:
        """Extract body paragraphs from JATS XML.

        Args:
            xml_content: JATS XML content

        Returns:
            Concatenated paragraph text, or None

        Examples:
            >>> provider = EuropePMCFullTextProvider()
            >>> xml = '<article><body><sec><p>Text here.</p></sec></body></article>'
            >>> provider._extract_body_text(xml)
            'Text here.'
        """
        try:
            soup = BeautifulSoup(xml_content, "xml")
        except Exception as exc:
            logger.debug(f"Failed to parse Europe PMC XML: {exc}")
            return None

        body = soup.find("body")
        if not body:
            return None

        paragraphs = body.find_all("p")
        if not paragraphs:
            return None

        texts = []
        for p in paragraphs:
            text = p.get_text().strip()
            if text:
                texts.append(text)

        return "\n\n".join(texts) if texts else None
