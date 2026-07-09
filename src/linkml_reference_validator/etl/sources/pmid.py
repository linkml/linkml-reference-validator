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
from linkml_reference_validator.etl.sources.utils import (
    extract_extra_fields,
    format_extra_fields_for_content,
)

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

        # A single efetch of the article XML backs the abstract, MeSH terms,
        # and publication types, so we don't round-trip to NCBI three times.
        article_xml = self._fetch_pubmed_xml(pmid, config)
        abstract = self._parse_abstract(article_xml) if article_xml else None
        keywords = self._parse_mesh_terms(article_xml) if article_xml else None
        publication_types = (
            self._parse_publication_types(article_xml) if article_xml else None
        )

        content: Optional[str] = abstract
        content_type = "abstract_only" if abstract else "unavailable"

        metadata: dict = {}
        extra = extract_extra_fields(
            record_dict, config.source_extra_fields.get("PMID", {})
        )
        if extra:
            content = (content or "") + "\n\n" + format_extra_fields_for_content(extra)
            metadata["extra_fields_captured"] = list(extra.keys())

        if (content or "").strip() and content_type == "unavailable":
            content_type = "summary"

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
            publication_types=publication_types,
            metadata=metadata,
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

    def _parse_abstract(self, soup: BeautifulSoup) -> Optional[str]:
        """Parse the abstract from a PubMed article XML document.

        Reconstructs the abstract prose from ``Abstract/AbstractText`` nodes.
        Structured abstracts label each section (e.g. ``Label="METHODS"``);
        the label is preserved as a ``"METHODS:"`` prefix and sections are
        joined by blank lines, mirroring how PubMed renders them as text.

        Args:
            soup: Parsed PubMed article XML

        Returns:
            Abstract text if available, otherwise None

        Examples:
            >>> from bs4 import BeautifulSoup
            >>> xml = '''<Abstract>
            ...   <AbstractText Label="METHODS">We ran a trial.</AbstractText>
            ...   <AbstractText Label="RESULTS">It worked.</AbstractText>
            ... </Abstract>'''
            >>> PMIDSource()._parse_abstract(BeautifulSoup(xml, "xml"))
            'METHODS: We ran a trial.\\n\\nRESULTS: It worked.'
            >>> xml = '<Abstract><AbstractText>A summary.</AbstractText></Abstract>'
            >>> PMIDSource()._parse_abstract(BeautifulSoup(xml, "xml"))
            'A summary.'
        """
        abstract = soup.find("Abstract")

        if not abstract:
            return None

        sections = []
        for node in abstract.find_all("AbstractText"):
            text = node.get_text().strip()
            if not text:
                continue
            label = node.get("Label")
            sections.append(f"{label}: {text}" if label else text)

        joined = "\n\n".join(sections)
        return joined if joined else None

    def _fetch_pubmed_xml(
        self, pmid: str, config: ReferenceValidationConfig
    ) -> Optional[BeautifulSoup]:
        """Fetch and parse the PubMed article XML for a PMID.

        A single efetch call backs both MeSH terms and publication types, so we
        don't round-trip to NCBI twice for the same document.

        Args:
            pmid: PubMed ID
            config: Configuration for rate limiting

        Returns:
            Parsed BeautifulSoup document, or None if nothing was returned
        """
        time.sleep(config.rate_limit_delay)

        handle = Entrez.efetch(db="pubmed", id=pmid,
                               rettype="xml", retmode="xml")
        xml_content = handle.read()
        handle.close()

        if isinstance(xml_content, bytes):
            xml_content = xml_content.decode("utf-8")

        if not xml_content:
            return None

        return BeautifulSoup(xml_content, "xml")

    def _parse_mesh_terms(self, soup: BeautifulSoup) -> Optional[list[str]]:
        """Parse MeSH terms from a PubMed article XML document.

        Args:
            soup: Parsed PubMed article XML

        Returns:
            List of MeSH terms if available

        Examples:
            >>> from bs4 import BeautifulSoup
            >>> xml = '''<MeshHeadingList><MeshHeading>
            ...   <DescriptorName>Climate Change</DescriptorName>
            ... </MeshHeading></MeshHeadingList>'''
            >>> PMIDSource()._parse_mesh_terms(BeautifulSoup(xml, "xml"))
            ['Climate Change']
        """
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

    def _parse_publication_types(
        self, soup: BeautifulSoup
    ) -> Optional[list[str]]:
        """Parse PublicationTypeList from a PubMed article XML document.

        Publication types are MeSH publication-type descriptors
        (https://www.nlm.nih.gov/mesh/pubtypes.html) that classify the source,
        e.g. "Case Reports", "Clinical Trial", "Review". Nearly every record
        carries the generic "Journal Article" type; it is retained as-is.

        Args:
            soup: Parsed PubMed article XML

        Returns:
            List of publication type labels if available

        Examples:
            >>> from bs4 import BeautifulSoup
            >>> xml = '''<PublicationTypeList>
            ...   <PublicationType UI="D016428">Journal Article</PublicationType>
            ...   <PublicationType UI="D002363">Case Reports</PublicationType>
            ... </PublicationTypeList>'''
            >>> PMIDSource()._parse_publication_types(BeautifulSoup(xml, "xml"))
            ['Journal Article', 'Case Reports']
        """
        type_list = soup.find("PublicationTypeList")

        if not type_list:
            return None

        types = [
            text
            for pt in type_list.find_all("PublicationType")
            if (text := pt.get_text().strip())
        ]

        return types if types else None

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

        if isinstance(result, list) and result and isinstance(result[0], dict):
            link_set_db = result[0].get("LinkSetDb", [])
            if isinstance(link_set_db, list) and link_set_db:
                links = link_set_db[0].get("Link", [])
                if isinstance(links, list) and links:
                    first_link = links[0]
                    if isinstance(first_link, dict) and "Id" in first_link:
                        return str(first_link["Id"])

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
