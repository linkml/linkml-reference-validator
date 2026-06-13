"""PMC full-text provider.

Resolves a PMC ID (from a PMID if needed) and returns the article body text,
fetched from the PMC XML API (with an HTML fallback) and extracted via XMLExtractor.
"""

import logging
import time
from typing import Optional

from Bio import Entrez  # type: ignore
from bs4 import BeautifulSoup  # type: ignore
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
from linkml_reference_validator.etl.extract.xml import XMLExtractor

logger = logging.getLogger(__name__)

_MIN_PMC_FULLTEXT_CHARS = 1000


@FullTextProviderRegistry.register
class PMCFullTextProvider(FullTextProvider):
    """Provide PMC full text for a reference identified by PMID/PMCID.

    Examples:
        >>> PMCFullTextProvider.name()
        'pmc'
    """

    @classmethod
    def name(cls) -> str:
        return "pmc"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        if not ids.pmcid and not ids.pmid:
            return None

        pmcid = ids.pmcid or self._resolve_pmcid(ids.pmid, config)
        if not pmcid:
            return None

        Entrez.email = config.email  # type: ignore

        xml_bytes = self._fetch_pmc_xml_bytes(pmcid, config)
        if xml_bytes:
            text = XMLExtractor().extract(xml_bytes, content_type="application/xml")
            if text and len(text) > _MIN_PMC_FULLTEXT_CHARS:
                return FullTextLocation(
                    text=text, format_hint="xml", oa_status="green", provider="pmc"
                )

        html_text = self._fetch_pmc_html(pmcid, config)
        if html_text and len(html_text) > _MIN_PMC_FULLTEXT_CHARS:
            return FullTextLocation(
                text=html_text, format_hint="html", oa_status="green", provider="pmc"
            )

        return None

    def _resolve_pmcid(self, pmid: Optional[str], config: ReferenceValidationConfig) -> Optional[str]:
        """Resolve a PMC ID from a PMID via Entrez elink."""
        if not pmid:
            return None
        Entrez.email = config.email  # type: ignore
        time.sleep(config.rate_limit_delay)

        try:
            handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid, linkname="pubmed_pmc")
            result = Entrez.read(handle)
            handle.close()
        except Exception as exc:  # external system boundary
            logger.warning("Failed to link PMID:%s to PMC: %s", pmid, exc)
            return None

        if isinstance(result, list) and result and isinstance(result[0], dict):
            link_set_db = result[0].get("LinkSetDb", [])
            if isinstance(link_set_db, list) and link_set_db:
                links = link_set_db[0].get("Link", [])
                if isinstance(links, list) and links:
                    first_link = links[0]
                    if isinstance(first_link, dict) and "Id" in first_link:
                        return str(first_link["Id"])
        return None

    def _fetch_pmc_xml_bytes(self, pmcid: str, config: ReferenceValidationConfig) -> Optional[bytes]:
        """Fetch raw PMC XML bytes for a PMC ID."""
        time.sleep(config.rate_limit_delay)
        handle = Entrez.efetch(db="pmc", id=pmcid, rettype="xml", retmode="xml")
        xml_content = handle.read()
        handle.close()
        if isinstance(xml_content, str):
            xml_content = xml_content.encode("utf-8")
        return xml_content

    def _fetch_pmc_html(self, pmcid: str, config: ReferenceValidationConfig) -> Optional[str]:
        """Fetch full text from the PMC HTML page as a fallback."""
        time.sleep(config.rate_limit_delay)
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, "html.parser")
        article_body = soup.find("div", class_="article-body") or soup.find("div", class_="tsec")
        if article_body:
            paragraphs = article_body.find_all("p")
            if paragraphs:
                return "\n\n".join(p.get_text() for p in paragraphs)
        return None
