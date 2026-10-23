"""Europe PMC full-text provider.

Fetches full-text XML for open access articles from the Europe PMC API.
This complements EuropePMCPreprintProvider, which handles preprints only.
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
from linkml_reference_validator.etl.extract import MIN_FULLTEXT_CHARS
from linkml_reference_validator.etl.extract.xml import XMLExtractor
from linkml_reference_validator.etl.fulltext.pmc import TransientFullTextError

logger = logging.getLogger(__name__)

EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
#: Addressed by the prefixed PMCID (``PMC3257301``). The ``/{source}/{id}/``
#: form is for the references and citations endpoints; here it 404s.
EUROPEPMC_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML"


@FullTextProviderRegistry.register
class EuropePMCFullTextProvider(FullTextProvider):
    """Fetch full-text XML for open access articles from Europe PMC.

    Queries the Europe PMC search API to find open access articles by PMID,
    then fetches full-text XML when available. This provider handles regular
    OA articles; preprints are handled by EuropePMCPreprintProvider.

    The JATS is the same as the ``pmc`` provider's, fetched from Europe PMC
    rather than NCBI, so ``epmc`` adds little after ``pmc`` in the chain. Its
    use is as a second route to the same articles when NCBI is unavailable or
    rate-limiting, or in place of ``pmc`` for users who would rather not
    depend on Entrez.

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
        """Return the article's Europe PMC full text, or None if it has none.

        Args:
            ids: Identifiers of the reference; only the PMID is used
            config: Configuration for rate limiting and the contact email

        Returns:
            A text location carrying the search result's licence, or None when
            there is no PMID, the article is not open access or has no PMCID,
            Europe PMC has no fullTextXML for it, or the text is below the floor

        Raises:
            TransientFullTextError: Europe PMC answered with a status or body
                that says nothing about the article
            requests.RequestException: A request itself failed

        Examples:
            >>> config = ReferenceValidationConfig(rate_limit_delay=0.0)
            >>> EuropePMCFullTextProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config) is None
            True
        """
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

        # A RequestException is left to the chain, whose had_error handling
        # keeps the record retryable, as in epmc_preprint.
        response = requests.get(EUROPEPMC_SEARCH_URL, params=params, timeout=30)

        if response.status_code != 200:
            # A search miss is an empty resultList on a 200, so any other
            # status is the service failing, not an answer about the article.
            raise TransientFullTextError(
                f"Europe PMC search returned {response.status_code} for PMID:{ids.pmid}"
            )

        try:  # external system boundary
            data = response.json()
        except ValueError as exc:
            # A 200 that is not JSON is the service's HTML maintenance or error
            # page, which says nothing about the article.
            raise TransientFullTextError(
                f"Europe PMC search returned a non-JSON body for PMID:{ids.pmid}"
            ) from exc

        result = self._find_oa_result(data)
        if not result:
            return None

        pmcid = result.get("pmcid")
        if not pmcid:
            logger.debug(f"No PMCID in Europe PMC result for PMID:{ids.pmid}")
            return None

        text = self._fetch_fulltext_xml(pmcid, config)
        if not text or len(text) <= MIN_FULLTEXT_CHARS:
            return None

        return FullTextLocation(
            text=text,
            format_hint="xml",
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

        Examples:
            >>> provider = EuropePMCFullTextProvider()
            >>> data = {"resultList": {"result": [
            ...     {"pmid": "1", "isOpenAccess": "N"},
            ...     {"pmid": "2", "isOpenAccess": "Y", "pmcid": "PMC2"},
            ... ]}}
            >>> provider._find_oa_result(data)["pmcid"]
            'PMC2'
            >>> provider._find_oa_result({"resultList": {"result": []}}) is None
            True
            >>> provider._find_oa_result({}) is None
            True
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
            Body text from the shared JATS extractor, or None
        """
        if not pmcid.upper().startswith("PMC"):
            pmcid = f"PMC{pmcid}"
        url = EUROPEPMC_FULLTEXT_URL.format(pmcid=pmcid)

        time.sleep(config.rate_limit_delay)

        response = requests.get(url, timeout=30)

        if response.status_code == 404:
            logger.debug(f"Europe PMC has no fullTextXML for {pmcid}")
            return None
        if response.status_code != 200:
            # The search already called this article open access with a PMCID,
            # so a failure here is treated as transient and retried next run.
            raise TransientFullTextError(
                f"Europe PMC fullTextXML returned {response.status_code} for {pmcid}"
            )

        # Bytes, not response.text: requests guesses ISO-8859-1 for XML served
        # without a charset, whereas the parser reads the XML declaration.
        return XMLExtractor().extract(response.content, content_type="application/xml")
