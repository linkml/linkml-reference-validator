"""PMC full-text provider.

Resolves a PMC ID (from a PMID if needed) and returns the article body text,
fetched from the PMC XML API (with an HTML fallback) and extracted via XMLExtractor.
"""

import logging
import time
from typing import Optional, Union

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
from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.extract import MIN_FULLTEXT_CHARS
from linkml_reference_validator.etl.extract.xml import XMLExtractor

logger = logging.getLogger(__name__)


class TransientFullTextError(RuntimeError):
    """A provider failed for a reason that says nothing about the article.

    ``_enrich_with_full_text`` already treats a raised exception as
    ``had_error``, which keeps the record retryable. Raising this rather than
    returning ``None`` is how a provider says "ask me again" instead of "there
    is nothing here".
    """


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

        xml_source = self._fetch_pmc_xml_source(pmcid, config)
        if xml_source:
            text = XMLExtractor().extract(xml_source, content_type="application/xml")
            # The shared floor, not a local threshold - see MIN_FULLTEXT_CHARS
            # in extract/xml.py, which carries the reasoning. On the HTML
            # fallback below it is the only stub defence there is.
            if text and len(text) > MIN_FULLTEXT_CHARS:
                return FullTextLocation(
                    text=text, format_hint="xml", oa_status="green", provider="pmc"
                )

        html_text = self._fetch_pmc_html(pmcid, config)
        if html_text and len(html_text) > MIN_FULLTEXT_CHARS:
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
            # An elink outage is not "this PMID has no PMC copy"; see the note
            # in _fetch_pmc_html for why that distinction has to survive.
            raise TransientFullTextError(
                f"Could not link PMID:{pmid} to PMC: {exc}"
            ) from exc

        if isinstance(result, list) and result and isinstance(result[0], dict):
            link_set_db = result[0].get("LinkSetDb", [])
            if isinstance(link_set_db, list) and link_set_db:
                links = link_set_db[0].get("Link", [])
                if isinstance(links, list) and links:
                    first_link = links[0]
                    if isinstance(first_link, dict) and "Id" in first_link:
                        return str(first_link["Id"])
        return None

    def _fetch_pmc_xml_source(
        self, pmcid: str, config: ReferenceValidationConfig
    ) -> Optional[Union[bytes, str]]:
        """Fetch raw PMC XML for a PMC ID, exactly as Entrez returned it.

        Returned unconverted: Entrez hands back str, and encoding it to UTF-8
        would leave any ISO-8859-1 declaration in front of UTF-8 bytes for the
        parser to believe, turning "François" into "FranÃ§ois". XMLExtractor
        accepts either form and gets both right.
        """
        time.sleep(config.rate_limit_delay)
        handle = Entrez.efetch(db="pmc", id=pmcid, rettype="xml", retmode="xml")
        xml_content = handle.read()
        handle.close()
        return xml_content

    def _fetch_pmc_html(self, pmcid: str, config: ReferenceValidationConfig) -> Optional[str]:
        """Fetch full text from the PMC HTML page as a fallback.

        This is the one page fetch the OA providers' "a landing page is not full
        text" rule does not cover, and what makes it safe is the requirement
        below: text is returned only from a ``div.article-body`` or ``div.tsec``.
        A bot-check interstitial -- which PMC serves on an HTTP 200, so no status
        check sees it -- carries neither, so this yields ``None`` rather than
        caching the page. The ``oa_url`` fallback that was removed had no such
        structural test; it accepted whatever came back.
        """
        time.sleep(config.rate_limit_delay)
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"
        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            # Not an absence. PMC answers a rate-limited client with 429, and
            # returning ``None`` here would let the chain record that this
            # article has no full text -- the defect this release is about, in
            # the host whose interstitial is its evidence. Raise so the chain's
            # existing ``had_error`` path keeps the record retryable.
            raise TransientFullTextError(
                f"PMC returned {response.status_code} for PMC{pmcid}"
            )

        soup = BeautifulSoup(response.content, "html.parser")
        article_body = soup.find("div", class_="article-body") or soup.find("div", class_="tsec")
        if article_body:
            # The region is selected here, but the text comes out of the shared
            # extractor rather than a private copy of the paragraph walk, so
            # this path gets its <br> handling and block-boundary fallback
            # instead of quietly drifting from it.
            return HTMLExtractor().extract_scope(article_body)
        return None
