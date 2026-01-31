"""PMID (PubMed ID) reference source.

Fetches publication content from PubMed/NCBI using the Entrez API.

Examples:
    >>> from linkml_reference_validator.etl.sources.pmid import PMIDSource
    >>> PMIDSource.prefix()
    'PMID'
    >>> PMIDSource.can_handle("PMID:12345678")
    True
"""

import logging
import re
import time
from typing import Any, Optional

from Bio import Entrez  # type: ignore
from bs4 import BeautifulSoup  # type: ignore
import requests  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)


@ReferenceSourceRegistry.register
class PMIDSource(ReferenceSource):
    """Fetch references from PubMed using PMID.

    Uses the NCBI Entrez API to fetch publication metadata and content.

    Examples:
        >>> source = PMIDSource()
        >>> source.prefix()
        'PMID'
        >>> source.can_handle("PMID:12345678")
        True
        >>> source.can_handle("PMID 12345678")
        True
    """

    @classmethod
    def prefix(cls) -> str:
        """Return 'PMID' prefix.

        Examples:
            >>> PMIDSource.prefix()
            'PMID'
        """
        return "PMID"

    @classmethod
    def can_handle(cls, reference_id: str) -> bool:
        """Check if this is a PMID reference.

        Handles formats:
        - PMID:12345678
        - PMID 12345678
        - Plain digits (assumed to be PMID)

        Examples:
            >>> PMIDSource.can_handle("PMID:12345678")
            True
            >>> PMIDSource.can_handle("PMID 12345678")
            True
            >>> PMIDSource.can_handle("12345678")
            True
            >>> PMIDSource.can_handle("DOI:10.1234/test")
            False
        """
        reference_id = reference_id.strip()
        # Check for PMID prefix
        if re.match(r"^PMID[:\s]", reference_id, re.IGNORECASE):
            return True
        # Plain digits are assumed to be PMIDs
        if reference_id.isdigit():
            return True
        return False

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch a publication from PubMed by PMID.

        Args:
            identifier: PubMed ID (without prefix)
            config: Configuration including rate limiting and email

        Returns:
            ReferenceContent if successful, None otherwise

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> config = ReferenceValidationConfig()
            >>> source = PMIDSource()
            >>> # Would fetch in real usage:
            >>> # ref = source.fetch("12345678", config)
        """
        pmid = identifier.strip()
        Entrez.email = config.email  # type: ignore

        time.sleep(config.rate_limit_delay)

        # External API call - handle network/API errors
        try:
            handle = Entrez.esummary(db="pubmed", id=pmid)
            records = Entrez.read(handle)
            handle.close()
        except Exception as e:
            logger.warning(f"Failed to fetch PMID:{pmid} from NCBI: {e}")
            return None

        if not records:
            logger.warning(f"No records found for PMID:{pmid}")
            return None

        record = records[0] if isinstance(records, list) else records

        if not isinstance(record, dict):
            logger.warning(
                "Unexpected record format for PMID:%s: %s", pmid, type(record))
            return None

        record_dict: dict[str, Any] = record

        # Convert Entrez StringElement objects to plain strings
        title = str(record_dict.get("Title", ""))
        authors = self._parse_authors(record_dict.get("AuthorList", []))
        journal = str(record_dict.get("Source", ""))
        pub_date = record_dict.get("PubDate", "")
        year = str(pub_date)[:4] if pub_date else ""
        doi = str(record_dict.get("DOI", "")) if record_dict.get("DOI") else ""

        abstract = self._fetch_abstract(pmid, config)
        full_text, content_type = self._fetch_pmc_fulltext(pmid, config)
        keywords = self._fetch_mesh_terms(pmid, config)

        if full_text:
            content: Optional[str] = f"{abstract}\n\n{full_text}" if abstract else full_text
        else:
            content = abstract
            content_type = "abstract_only" if abstract else "unavailable"

        return ReferenceContent(
            reference_id=f"PMID:{pmid}",
            title=title,
            content=content,
            content_type=content_type,
            authors=authors,
            journal=journal,
            year=year,
            doi=doi,
            keywords=keywords,
        )

    def _parse_authors(self, author_list: list) -> list[str]:
        """Parse author list from Entrez record.

        Args:
            author_list: List of author names from Entrez

        Returns:
            List of formatted author names

        Examples:
            >>> source = PMIDSource()
            >>> source._parse_authors(["Smith J", "Doe A"])
            ['Smith J', 'Doe A']
        """
        return [str(author) for author in author_list if author]

    def _fetch_abstract(
        self, pmid: str, config: ReferenceValidationConfig
    ) -> Optional[str]:
        """Fetch abstract for a PMID.

        Args:
            pmid: PubMed ID
            config: Configuration for rate limiting

        Returns:
            Abstract text if available
        """
        time.sleep(config.rate_limit_delay)

        handle = Entrez.efetch(db="pubmed", id=pmid,
                               rettype="abstract", retmode="text")
        abstract_text = handle.read()
        handle.close()

        if abstract_text and len(abstract_text) > 50:
            return str(abstract_text)

        return None

    def _fetch_mesh_terms(
        self, pmid: str, config: ReferenceValidationConfig
    ) -> Optional[list[str]]:
        """Fetch MeSH terms for a PMID from PubMed XML.

        Args:
            pmid: PubMed ID
            config: Configuration for rate limiting

        Returns:
            List of MeSH terms if available

        Examples:
            >>> source = PMIDSource()
            >>> # Would return MeSH terms like:
            >>> # ['Adaptation, Physiological/genetics', 'Climate Change', ...]
        """
        time.sleep(config.rate_limit_delay)

        handle = Entrez.efetch(db="pubmed", id=pmid,
                               rettype="xml", retmode="xml")
        xml_content = handle.read()
        handle.close()

        if isinstance(xml_content, bytes):
            xml_content = xml_content.decode("utf-8")

        soup = BeautifulSoup(xml_content, "xml")
        mesh_list = soup.find("MeshHeadingList")

        if not mesh_list:
            return None

        terms = []
        for heading in mesh_list.find_all("MeshHeading"):
            descriptor = heading.find("DescriptorName")
            if descriptor:
                term = descriptor.get_text()
                # Include qualifiers if present (e.g., "genetics", "metabolism")
                qualifiers = heading.find_all("QualifierName")
                if qualifiers:
                    qualifier_texts = [q.get_text() for q in qualifiers]
                    term = f"{term}/{', '.join(qualifier_texts)}"
                terms.append(term)

        return terms if terms else None

    def _fetch_pmc_fulltext(
        self, pmid: str, config: ReferenceValidationConfig
    ) -> tuple[Optional[str], str]:
        """Attempt to fetch full text from PMC.

        Args:
            pmid: PubMed ID
            config: Configuration for rate limiting

        Returns:
            Tuple of (full_text, content_type)
        """
        pmcid = self._get_pmcid(pmid, config)
        if not pmcid:
            return None, "no_pmc"

        full_text = self._fetch_pmc_xml(pmcid, config)
        if full_text and len(full_text) > 1000:
            return full_text, "full_text_xml"

        full_text = self._fetch_pmc_html(pmcid, config)
        if full_text and len(full_text) > 1000:
            return full_text, "full_text_html"

        return None, "pmc_restricted"

    def _get_pmcid(self, pmid: str, config: ReferenceValidationConfig) -> Optional[str]:
        """Get PMC ID for a PubMed ID.

        Args:
            pmid: PubMed ID
            config: Configuration for rate limiting

        Returns:
            PMC ID if available
        """
        time.sleep(config.rate_limit_delay)

        try:
            handle = Entrez.elink(
                dbfrom="pubmed", db="pmc", id=pmid, linkname="pubmed_pmc"
            )
        except Exception as exc:
            logger.warning("Failed to link PMID:%s to PMC: %s", pmid, exc)
            return None

        try:
            result = Entrez.read(handle)
        except Exception as exc:
            logger.warning(
                "Failed to read PMC link for PMID:%s: %s", pmid, exc)
            return None
        finally:
            handle.close()

        if result and result[0].get("LinkSetDb"):
            links = result[0]["LinkSetDb"][0].get("Link", [])
            if links:
                return links[0]["Id"]

        return None

    def _fetch_pmc_xml(
        self, pmcid: str, config: ReferenceValidationConfig
    ) -> Optional[str]:
        """Fetch full text from PMC XML API.

        Args:
            pmcid: PMC ID
            config: Configuration for rate limiting

        Returns:
            Extracted text from XML
        """
        time.sleep(config.rate_limit_delay)

        handle = Entrez.efetch(
            db="pmc", id=pmcid, rettype="xml", retmode="xml")
        xml_content = handle.read()
        handle.close()

        if isinstance(xml_content, bytes):
            xml_content = xml_content.decode("utf-8")

        if "cannot be obtained" in xml_content.lower() or "restricted" in xml_content.lower():
            return None

        soup = BeautifulSoup(xml_content, "xml")
        body = soup.find("body")

        if body:
            paragraphs = body.find_all("p")
            if paragraphs:
                text = "\n\n".join(p.get_text() for p in paragraphs)
                return text

        return None

    def _fetch_pmc_html(
        self, pmcid: str, config: ReferenceValidationConfig
    ) -> Optional[str]:
        """Fetch full text from PMC HTML as fallback.

        Args:
            pmcid: PMC ID
            config: Configuration for rate limiting

        Returns:
            Extracted text from HTML
        """
        time.sleep(config.rate_limit_delay)

        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"

        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, "html.parser")
        article_body = soup.find("div", class_="article-body") or soup.find(
            "div", class_="tsec"
        )

        if article_body:
            paragraphs = article_body.find_all("p")
            if paragraphs:
                text = "\n\n".join(p.get_text() for p in paragraphs)
                return text

        return None
