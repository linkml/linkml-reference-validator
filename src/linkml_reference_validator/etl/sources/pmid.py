"""PMID (PubMed ID) reference source.

Fetches publication content from PubMed/NCBI using the Entrez API.

Examples:
    >>> from linkml_reference_validator.etl.sources.pmid import PMIDSource
    >>> PMIDSource.prefix()
    'PMID'
    >>> PMIDSource.can_handle("PMID:12345678")
    True
"""

from collections.abc import Callable
from http.client import HTTPException
from io import BytesIO
import logging
import re
import time
from typing import Any, Optional
from urllib.error import HTTPError, URLError

from Bio import Entrez  # type: ignore
from bs4 import BeautifulSoup  # type: ignore
import requests  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.extract import MIN_FULLTEXT_CHARS
from linkml_reference_validator.etl.extract.xml import XMLExtractor
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

        summary = self._read_entrez(
            lambda: Entrez.esummary(db="pubmed", id=pmid), pmid, config
        )
        if summary is None:
            return None

        # Parse only complete responses: a truncated stream can otherwise look
        # like malformed XML to Entrez.read instead of a transport failure.
        try:
            records = Entrez.read(BytesIO(summary))
        except (ValueError, RuntimeError) as exc:
            logger.warning("Failed to parse PMID:%s summary: %s", pmid, exc)
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
        if article_xml is None:
            # A failed refresh must not overwrite useful cached text with just
            # summary metadata. None also enables ReferenceFetcher's stale fallback.
            return None
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

    @staticmethod
    def _render_abstract_sections(element: Any) -> Optional[str]:
        """Join an abstract element's ``AbstractText`` nodes into prose.

        Structured abstracts label each section (e.g. ``Label="METHODS"``); the
        label is preserved as a ``"METHODS:"`` prefix and sections are joined by
        blank lines, mirroring how PubMed renders them as text.

        Args:
            element: An ``Abstract`` or ``OtherAbstract`` node

        Returns:
            The joined prose, or None if the element carries no text

        Examples:
            >>> from bs4 import BeautifulSoup
            >>> xml = '''<Abstract>
            ...   <AbstractText Label="METHODS">We ran a trial.</AbstractText>
            ...   <AbstractText Label="RESULTS">It worked.</AbstractText>
            ... </Abstract>'''
            >>> element = BeautifulSoup(xml, "xml").find("Abstract")
            >>> PMIDSource._render_abstract_sections(element)
            'METHODS: We ran a trial.\\n\\nRESULTS: It worked.'
        """
        sections = []
        for node in element.find_all("AbstractText"):
            text = node.get_text().strip()
            if not text:
                continue
            label = node.get("Label")
            sections.append(f"{label}: {text}" if label else text)

        joined = "\n\n".join(sections)
        return joined if joined else None

    def _parse_abstract(self, soup: BeautifulSoup) -> Optional[str]:
        """Parse the abstract from a PubMed article XML document.

        Reads ``Abstract`` when the record has one. Otherwise falls back to
        ``OtherAbstract``, which is where PubMed keeps abstracts contributed by
        other indexing programs -- ``PIP``, ``KIE``, ``NASA``, ``AIDS`` -- mostly
        on pre-1990 records. Those are genuine abstracts, and reading only
        ``Abstract`` reports no content at all for such a record, which on a
        refresh deletes the text a cache entry already held (issue #88).

        ``OtherAbstract`` also carries translations, so an English one is
        preferred; a translated abstract is still used when it is the only text
        available, because reporting nothing would blank the entry.

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
            >>> xml = '''<OtherAbstract Type="PIP" Language="eng">
            ...   <AbstractText>An indexer's summary.</AbstractText>
            ... </OtherAbstract>'''
            >>> PMIDSource()._parse_abstract(BeautifulSoup(xml, "xml"))
            "An indexer's summary."
        """
        abstract = soup.find("Abstract")
        if abstract:
            rendered = self._render_abstract_sections(abstract)
            if rendered:
                return rendered

        others = soup.find_all("OtherAbstract")
        if not others:
            return None

        # Prefer English; OtherAbstract is also where translations live, and a
        # French rendering would stop an English snippet matching its source.
        # `Language` is #IMPLIED with an `eng` default in the PubMed DTD, so an
        # attribute-less node is English rather than an unknown translation.
        def _is_english(node: Any) -> bool:
            language = node.get("Language")
            if isinstance(language, list):  # bs4 may split a multi-valued attr
                language = language[0] if language else None
            return str(language or "eng").strip().lower() in ("eng", "en")

        english: list[Any] = []
        rest: list[Any] = []
        for node in others:
            (english if _is_english(node) else rest).append(node)

        for node in english + rest:
            rendered = self._render_abstract_sections(node)
            if rendered:
                return rendered

        return None

    def _read_entrez(
        self,
        open_handle: Callable[[], Any],
        pmid: str,
        config: ReferenceValidationConfig,
    ) -> Optional[bytes]:
        """Read a complete response, retrying transport failures up to three attempts.

        Entrez already retries HTTP/URL errors during opening (three attempts by
        default, with its own delays). Do not restart that exhausted retry loop.
        Socket/TLS failures and HTTP framing errors escape Entrez's loop, so
        retry those here with 2 and 4 second backoff. A mixed sequence can make
        at most ``3 * Entrez.max_tries`` requests; no process-global Entrez retry
        settings are changed. Parsing happens after this transport-only boundary.

        Args:
            open_handle: Open a new Entrez response for each attempt.
            pmid: PubMed identifier for diagnostics.
            config: Configuration for rate limiting.

        Returns:
            Complete response bytes, or None when the request fails.
        """
        for attempt in range(3):
            time.sleep(config.rate_limit_delay)
            handle = None
            try:
                try:
                    handle = open_handle()
                except URLError as exc:
                    # Includes HTTPError. Entrez has already applied its retry
                    # policy; retrying here would multiply outage waits.
                    if isinstance(exc, HTTPError):
                        exc.close()
                    logger.warning("Failed to open PMID:%s from NCBI: %s", pmid, exc)
                    return None
                return handle.read()
            except (OSError, HTTPException) as exc:
                logger.warning(
                    "NCBI transport failure for PMID:%s (attempt %s/3): %s",
                    pmid, attempt + 1, exc,
                )
            finally:
                if handle is not None:
                    handle.close()
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
        return None

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
        xml_content = self._read_entrez(
            lambda: Entrez.efetch(db="pubmed", id=pmid, rettype="xml", retmode="xml"),
            pmid,
            config,
        )

        if not xml_content:
            return None

        # Passed through as returned, for the same reason _fetch_pmc_xml does:
        # decoding bytes here assumes UTF-8 and raises on a record declaring
        # another encoding, taking the MeSH terms and publication types with
        # it. BeautifulSoup honours the declaration for bytes and fixes it up
        # for str.
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

        # The shared floor, not a local threshold: see MIN_FULLTEXT_CHARS in
        # extract/xml.py, which carries the reasoning. On the HTML fallback
        # below it is the only stub defence there is.
        full_text = self._fetch_pmc_xml(pmcid, config)
        if full_text and len(full_text) > MIN_FULLTEXT_CHARS:
            return full_text, "full_text_xml"

        full_text = self._fetch_pmc_html(pmcid, config)
        if full_text and len(full_text) > MIN_FULLTEXT_CHARS:
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

        # Handed on as-is. Entrez returns str, and re-encoding it to UTF-8
        # would leave any ISO-8859-1 declaration in place for the parser to
        # believe, turning "François" into "FranÃ§ois". BeautifulSoup fixes up
        # the declaration itself when given str.
        #
        # Delegated to the shared extractor so body parsing and PMC
        # placeholder detection cannot drift from the rest of the ETL layer.
        # This module used to carry its own copy, which discarded any article
        # whose markup mentioned "restricted" anywhere at all.
        return XMLExtractor().extract(xml_content)

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
        # Shared with the PMC full-text provider: the container moved from a
        # ``div`` to a ``section`` and changed class, so both call sites went
        # blind at once (dismech#12672).
        from linkml_reference_validator.etl.fulltext.pmc import _find_pmc_article_body

        article_body = _find_pmc_article_body(soup)

        if article_body:
            # Region selected here, text extracted by the shared extractor, for
            # the same reason _fetch_pmc_xml delegates: a private paragraph
            # walk drifts from the rest of the ETL layer and misses its fixes.
            return HTMLExtractor().extract_scope(article_body)

        return None
