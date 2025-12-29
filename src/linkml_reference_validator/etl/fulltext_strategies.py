"""Enhanced fulltext retrieval strategies.

This module provides multiple strategies for fetching fulltext content
from scientific publications, including:
- BioC XML API (NCBI BioNLP)
- Europe PMC
- Unpaywall (open access papers via DOI)
- Identifier conversion utilities (DOI <-> PMID <-> PMCID)

Examples:
    >>> from linkml_reference_validator.etl.fulltext_strategies import FulltextFetcher
    >>> fetcher = FulltextFetcher(email="user@example.com")
    >>> # result = fetcher.fetch_fulltext_for_pmid("12345678")
    >>> # result = fetcher.fetch_fulltext_for_doi("10.1234/example")
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

import requests  # type: ignore
from bs4 import BeautifulSoup  # type: ignore

logger = logging.getLogger(__name__)

# API URLs
BIOC_URL = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmid}/ascii"
EUROPEPMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPEPMC_FULLTEXT_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/{source}/{id}/fullTextXML"
UNPAYWALL_URL = "https://api.unpaywall.org/v2/{doi}"
NCBI_IDCONV_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"
NCBI_ESUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"


@dataclass
class FulltextResult:
    """Result from a fulltext retrieval attempt.

    Attributes:
        content: The fulltext content if found
        source: The source that provided the content (bioc, europepmc, unpaywall)
        content_type: Type of content (full_text_bioc, full_text_europepmc, etc.)
        success: Whether the retrieval was successful
        error_message: Error message if retrieval failed
        metadata: Additional metadata from the source

    Examples:
        >>> result = FulltextResult(
        ...     content="Full article text here.",
        ...     source="bioc",
        ...     content_type="full_text_bioc",
        ...     success=True,
        ... )
        >>> result.success
        True
        >>> result.source
        'bioc'
    """

    content: Optional[str] = None
    source: str = "unknown"
    content_type: str = "unknown"
    success: bool = True
    error_message: Optional[str] = None
    metadata: dict = field(default_factory=dict)


class FulltextStrategy(ABC):
    """Abstract base class for fulltext retrieval strategies.

    Subclasses must implement the fetch method to retrieve fulltext
    content from their respective sources.

    Examples:
        >>> class MyStrategy(FulltextStrategy):
        ...     def fetch(self, identifier):
        ...         return FulltextResult(content="test", source="my_source")
        >>> strategy = MyStrategy()
        >>> strategy.name
        'MyStrategy'
    """

    @property
    def name(self) -> str:
        """Return the strategy name."""
        return self.__class__.__name__

    @abstractmethod
    def fetch(self, identifier: str, rate_limit_delay: float = 0.5) -> FulltextResult:
        """Fetch fulltext for the given identifier.

        Args:
            identifier: The identifier to fetch (PMID, DOI, etc.)
            rate_limit_delay: Delay between API requests

        Returns:
            FulltextResult with content if successful
        """
        ...


class BioCStrategy(FulltextStrategy):
    """Fetch fulltext using NCBI BioC XML API.

    The BioC API provides structured fulltext for articles in the
    PubMed Central Open Access subset. This is often the most reliable
    source for clean fulltext.

    Examples:
        >>> strategy = BioCStrategy()
        >>> url = strategy._build_url("12345678")
        >>> "12345678" in url
        True
        >>> "BioC_xml" in url
        True
    """

    def _build_url(self, pmid: str) -> str:
        """Build the BioC API URL for a PMID.

        Args:
            pmid: The PubMed ID

        Returns:
            The API URL

        Examples:
            >>> strategy = BioCStrategy()
            >>> url = strategy._build_url("12345")
            >>> "12345" in url and "BioC_xml" in url
            True
        """
        return BIOC_URL.format(pmid=pmid)

    def fetch(self, identifier: str, rate_limit_delay: float = 0.5) -> FulltextResult:
        """Fetch fulltext from BioC API.

        Args:
            identifier: PMID to fetch
            rate_limit_delay: Delay before request

        Returns:
            FulltextResult with fulltext if available
        """
        pmid = identifier.strip()
        if ":" in pmid:
            pmid = pmid.split(":")[-1]

        time.sleep(rate_limit_delay)
        url = self._build_url(pmid)

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"BioC request failed for PMID:{pmid}: {e}")
            return FulltextResult(
                success=False,
                source="bioc",
                content_type="unavailable",
                error_message=str(e),
            )

        if response.status_code != 200:
            logger.debug(f"BioC not available for PMID:{pmid} (status {response.status_code})")
            return FulltextResult(
                success=False,
                source="bioc",
                content_type="unavailable",
                error_message=f"HTTP {response.status_code}",
            )

        # Parse BioC XML
        soup = BeautifulSoup(response.text, "xml")
        text_sections = [text_tag.get_text() for text_tag in soup.find_all("text")]

        if not text_sections:
            return FulltextResult(
                success=False,
                source="bioc",
                content_type="unavailable",
                error_message="No text sections found in BioC response",
            )

        full_text = "\n\n".join(text_sections).strip()

        if len(full_text) < 500:
            return FulltextResult(
                success=False,
                source="bioc",
                content_type="unavailable",
                error_message="BioC response too short",
            )

        return FulltextResult(
            content=full_text,
            source="bioc",
            content_type="full_text_bioc",
            success=True,
        )


class EuropePMCStrategy(FulltextStrategy):
    """Fetch fulltext from Europe PMC.

    Europe PMC provides fulltext for many open access articles,
    including some not available in the US PubMed Central.

    Examples:
        >>> strategy = EuropePMCStrategy()
        >>> url = strategy._build_search_url("12345678")
        >>> "europepmc" in url
        True
    """

    def _build_search_url(self, pmid: str) -> str:
        """Build Europe PMC search URL for a PMID.

        Args:
            pmid: The PubMed ID

        Returns:
            The search API URL
        """
        return f"{EUROPEPMC_SEARCH_URL}?query=ext_id:{pmid}&format=json"

    def _build_fulltext_url(self, pmcid: str) -> str:
        """Build Europe PMC fulltext URL for a PMCID.

        Args:
            pmcid: The PMC ID (with or without PMC prefix)

        Returns:
            The fulltext API URL
        """
        # Strip PMC prefix if present
        pmc_id = pmcid.replace("PMC", "")
        return EUROPEPMC_FULLTEXT_URL.format(source="PMC", id=pmc_id)

    def fetch(self, identifier: str, rate_limit_delay: float = 0.5) -> FulltextResult:
        """Fetch fulltext from Europe PMC.

        Args:
            identifier: PMID to fetch
            rate_limit_delay: Delay before request

        Returns:
            FulltextResult with fulltext if available
        """
        pmid = identifier.strip()
        if ":" in pmid:
            pmid = pmid.split(":")[-1]

        time.sleep(rate_limit_delay)

        # First, search for the article to get PMCID
        search_url = self._build_search_url(pmid)
        try:
            response = requests.get(search_url, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"Europe PMC search failed for PMID:{pmid}: {e}")
            return FulltextResult(
                success=False,
                source="europepmc",
                content_type="unavailable",
                error_message=str(e),
            )

        if response.status_code != 200:
            return FulltextResult(
                success=False,
                source="europepmc",
                content_type="unavailable",
                error_message=f"Search HTTP {response.status_code}",
            )

        data = response.json()
        results = data.get("resultList", {}).get("result", [])

        if not results:
            return FulltextResult(
                success=False,
                source="europepmc",
                content_type="unavailable",
                error_message="Article not found in Europe PMC",
            )

        article = results[0]
        pmcid = article.get("pmcid")
        is_oa = article.get("isOpenAccess") == "Y"

        if not pmcid or not is_oa:
            return FulltextResult(
                success=False,
                source="europepmc",
                content_type="unavailable",
                error_message="Article not open access or no PMC ID",
            )

        # Fetch the fulltext XML
        time.sleep(rate_limit_delay)
        fulltext_url = self._build_fulltext_url(pmcid)

        try:
            ft_response = requests.get(fulltext_url, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"Europe PMC fulltext fetch failed: {e}")
            return FulltextResult(
                success=False,
                source="europepmc",
                content_type="unavailable",
                error_message=str(e),
            )

        if ft_response.status_code != 200:
            return FulltextResult(
                success=False,
                source="europepmc",
                content_type="unavailable",
                error_message=f"Fulltext HTTP {ft_response.status_code}",
            )

        # Parse the fulltext XML
        soup = BeautifulSoup(ft_response.text, "xml")
        body = soup.find("body")

        if body:
            paragraphs = body.find_all("p")
            if paragraphs:
                text = "\n\n".join(p.get_text() for p in paragraphs)
                if len(text) > 500:
                    return FulltextResult(
                        content=text,
                        source="europepmc",
                        content_type="full_text_europepmc",
                        success=True,
                        metadata={"pmcid": pmcid},
                    )

        return FulltextResult(
            success=False,
            source="europepmc",
            content_type="unavailable",
            error_message="Could not extract text from Europe PMC XML",
        )


class UnpaywallStrategy(FulltextStrategy):
    """Fetch open access papers via Unpaywall API.

    Unpaywall provides access to legal open access versions of papers.
    Requires a valid email address for API access.

    Examples:
        >>> strategy = UnpaywallStrategy(email="test@example.com")
        >>> url = strategy._build_url("10.1234/example")
        >>> "api.unpaywall.org" in url
        True
    """

    def __init__(self, email: str = "linkml-reference-validator@example.com"):
        """Initialize with email for API access.

        Args:
            email: Email address for Unpaywall API
        """
        self.email = email

    def _build_url(self, doi: str) -> str:
        """Build Unpaywall API URL for a DOI.

        Args:
            doi: The DOI

        Returns:
            The API URL

        Examples:
            >>> strategy = UnpaywallStrategy(email="test@example.com")
            >>> url = strategy._build_url("10.1234/test")
            >>> "10.1234/test" in url and "test@example.com" in url
            True
        """
        return f"{UNPAYWALL_URL.format(doi=doi)}?email={self.email}"

    def fetch(self, identifier: str, rate_limit_delay: float = 0.5) -> FulltextResult:
        """Fetch open access info from Unpaywall.

        Note: This does not fetch the actual fulltext, but provides
        information about where to find open access versions.

        Args:
            identifier: DOI to look up
            rate_limit_delay: Delay before request

        Returns:
            FulltextResult with OA location info
        """
        doi = identifier.strip()
        if doi.lower().startswith("doi:"):
            doi = doi[4:]

        time.sleep(rate_limit_delay)
        url = self._build_url(doi)

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"Unpaywall request failed for DOI:{doi}: {e}")
            return FulltextResult(
                success=False,
                source="unpaywall",
                content_type="unavailable",
                error_message=str(e),
            )

        if response.status_code != 200:
            return FulltextResult(
                success=False,
                source="unpaywall",
                content_type="unavailable",
                error_message=f"HTTP {response.status_code}",
            )

        data = response.json()
        is_oa = data.get("is_oa", False)

        if not is_oa:
            return FulltextResult(
                success=False,
                source="unpaywall",
                content_type="unavailable",
                error_message="Article is not open access",
            )

        best_location = data.get("best_oa_location", {}) or {}
        pdf_url = best_location.get("url_for_pdf") or best_location.get("url")
        oa_locations = data.get("oa_locations", [])

        # Look for PMC source in OA locations
        pmcid = None
        for loc in oa_locations:
            pmh_id = loc.get("pmh_id", "")
            if "pubmedcentral" in pmh_id.lower():
                # Extract PMC ID from pmh_id like "oai:pubmedcentral.nih.gov:123456"
                parts = pmh_id.split(":")
                if len(parts) >= 3:
                    pmcid = f"PMC{parts[-1]}"
                break

        return FulltextResult(
            content=None,  # Unpaywall doesn't provide content directly
            source="unpaywall",
            content_type="oa_location",
            success=True,
            metadata={
                "is_oa": True,
                "pdf_url": pdf_url,
                "pmcid": pmcid,
                "license": best_location.get("license"),
                "version": best_location.get("version"),
            },
        )


class IdentifierConverter:
    """Convert between DOI, PMID, and PMCID identifiers.

    Uses NCBI ID Converter and E-utilities APIs.

    Examples:
        >>> converter = IdentifierConverter()
        >>> # pmid = converter.doi_to_pmid("10.1234/example")
        >>> # doi = converter.pmid_to_doi("12345678")
    """

    def __init__(self, email: str = "linkml-reference-validator@example.com"):
        """Initialize with email for NCBI API.

        Args:
            email: Email for NCBI API access
        """
        self.email = email

    def doi_to_pmid(self, doi: str, rate_limit_delay: float = 0.5) -> Optional[str]:
        """Convert DOI to PMID.

        Args:
            doi: The DOI to convert
            rate_limit_delay: Delay before request

        Returns:
            PMID if found, None otherwise

        Examples:
            >>> converter = IdentifierConverter()
            >>> # This would make an API call in real usage
            >>> # pmid = converter.doi_to_pmid("10.1234/example")
        """
        if doi.lower().startswith("doi:"):
            doi = doi[4:]

        time.sleep(rate_limit_delay)
        url = f"{NCBI_IDCONV_URL}?ids={doi}&format=json"

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"ID conversion failed for DOI:{doi}: {e}")
            return None

        if response.status_code != 200:
            return None

        data = response.json()
        records = data.get("records", [])

        if records:
            return records[0].get("pmid")
        return None

    def pmid_to_doi(self, pmid: str, rate_limit_delay: float = 0.5) -> Optional[str]:
        """Convert PMID to DOI.

        Args:
            pmid: The PMID to convert
            rate_limit_delay: Delay before request

        Returns:
            DOI if found, None otherwise
        """
        if ":" in pmid:
            pmid = pmid.split(":")[-1]

        time.sleep(rate_limit_delay)
        url = f"{NCBI_ESUMMARY_URL}?db=pubmed&id={pmid}&retmode=json"

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"PMID to DOI conversion failed for {pmid}: {e}")
            return None

        if response.status_code != 200:
            return None

        data = response.json()

        try:
            article_info = data["result"][str(pmid)]
            for aid in article_info.get("articleids", []):
                if aid.get("idtype") == "doi":
                    return aid.get("value")
            # Check elocationid as fallback
            elocationid = article_info.get("elocationid", "")
            if elocationid.startswith("10."):
                return elocationid
        except KeyError:
            pass

        return None

    def pmid_to_pmcid(self, pmid: str, rate_limit_delay: float = 0.5) -> Optional[str]:
        """Convert PMID to PMCID.

        Args:
            pmid: The PMID to convert
            rate_limit_delay: Delay before request

        Returns:
            PMCID if found, None otherwise
        """
        if ":" in pmid:
            pmid = pmid.split(":")[-1]

        time.sleep(rate_limit_delay)
        url = f"{NCBI_IDCONV_URL}?ids={pmid}&format=json"

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"PMID to PMCID conversion failed for {pmid}: {e}")
            return None

        if response.status_code != 200:
            return None

        data = response.json()
        records = data.get("records", [])

        if records:
            return records[0].get("pmcid")
        return None

    def pmcid_to_pmid(self, pmcid: str, rate_limit_delay: float = 0.5) -> Optional[str]:
        """Convert PMCID to PMID.

        Args:
            pmcid: The PMCID to convert (with or without PMC prefix)
            rate_limit_delay: Delay before request

        Returns:
            PMID if found, None otherwise
        """
        # Strip PMC prefix if present
        pmc_id = pmcid.replace("PMC", "").replace("pmc", "")
        if ":" in pmc_id:
            pmc_id = pmc_id.split(":")[-1]

        time.sleep(rate_limit_delay)
        url = f"{NCBI_ESUMMARY_URL}?db=pmc&id={pmc_id}&retmode=json"

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as e:
            logger.warning(f"PMCID to PMID conversion failed for {pmcid}: {e}")
            return None

        if response.status_code != 200:
            return None

        data = response.json()

        try:
            uids = data["result"]["uids"]
            if uids:
                uid = uids[0]
                article_ids = data["result"][uid].get("articleids", [])
                for item in article_ids:
                    if item.get("idtype") == "pmid":
                        return item.get("value")
        except KeyError:
            pass

        return None


class FulltextFetcher:
    """Orchestrates multiple fulltext strategies with fallback.

    Tries strategies in order until one succeeds.

    Examples:
        >>> fetcher = FulltextFetcher(email="test@example.com")
        >>> # result = fetcher.fetch_fulltext_for_pmid("12345678")
        >>> # result = fetcher.fetch_fulltext_for_doi("10.1234/example")
    """

    def __init__(
        self,
        email: str = "linkml-reference-validator@example.com",
        rate_limit_delay: float = 0.5,
    ):
        """Initialize the fetcher with strategies.

        Args:
            email: Email for API access
            rate_limit_delay: Delay between requests
        """
        self.email = email
        self.rate_limit_delay = rate_limit_delay
        self.converter = IdentifierConverter(email=email)

        # Strategies in priority order for PMIDs
        self.pmid_strategies: list[FulltextStrategy] = [
            BioCStrategy(),
            EuropePMCStrategy(),
        ]

        self.unpaywall = UnpaywallStrategy(email=email)

    def fetch_fulltext_for_pmid(self, pmid: str) -> FulltextResult:
        """Fetch fulltext for a PMID using all strategies.

        Tries strategies in order:
        1. BioC XML API
        2. Europe PMC

        Args:
            pmid: The PubMed ID

        Returns:
            FulltextResult from the first successful strategy
        """
        for strategy in self.pmid_strategies:
            result = strategy.fetch(pmid, self.rate_limit_delay)
            if result.success and result.content:
                logger.info(f"Fetched fulltext for PMID:{pmid} via {strategy.name}")
                return result

        # All strategies failed
        return FulltextResult(
            success=False,
            source="none",
            content_type="unavailable",
            error_message="No fulltext available from any source",
        )

    def fetch_fulltext_for_doi(self, doi: str) -> FulltextResult:
        """Fetch fulltext for a DOI.

        Tries to convert DOI to PMID first, then uses PMID strategies.
        Falls back to Unpaywall for OA location.

        Args:
            doi: The DOI

        Returns:
            FulltextResult
        """
        # Try to convert DOI to PMID
        pmid = self.converter.doi_to_pmid(doi, self.rate_limit_delay)

        if pmid:
            result = self.fetch_fulltext_for_pmid(pmid)
            if result.success:
                return result

        # Try Unpaywall for OA location
        unpaywall_result = self.unpaywall.fetch(doi, self.rate_limit_delay)
        if unpaywall_result.success:
            # If Unpaywall found a PMCID, try to fetch that
            pmcid = unpaywall_result.metadata.get("pmcid")
            if pmcid:
                pmid_from_pmc = self.converter.pmcid_to_pmid(pmcid, self.rate_limit_delay)
                if pmid_from_pmc:
                    result = self.fetch_fulltext_for_pmid(pmid_from_pmc)
                    if result.success:
                        return result

            # Return the Unpaywall result with OA location info
            return unpaywall_result

        return FulltextResult(
            success=False,
            source="none",
            content_type="unavailable",
            error_message="No fulltext available from any source",
        )
