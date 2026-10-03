"""BioC XML full-text provider.

Fetches structured full text from the NCBI BioNLP BioC API, which provides
clean paragraph-level text for articles in the PMC Open Access subset.
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

BIOC_URL = "https://www.ncbi.nlm.nih.gov/research/bionlp/RESTful/pmcoa.cgi/BioC_xml/{pmid}/ascii"


@FullTextProviderRegistry.register
class BioCFullTextProvider(FullTextProvider):
    """Fetch full text via the NCBI BioNLP BioC XML API.

    The BioC API provides structured, clean paragraph text for articles in
    the PMC Open Access subset. It returns text with passage-level structure
    (title, abstract, body sections) without inline markup.

    Examples:
        >>> BioCFullTextProvider.name()
        'bioc'
    """

    @classmethod
    def name(cls) -> str:
        return "bioc"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        if not ids.pmid:
            return None

        time.sleep(config.rate_limit_delay)

        url = BIOC_URL.format(pmid=ids.pmid)
        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.debug(f"BioC request failed for PMID:{ids.pmid}: {exc}")
            return None

        if response.status_code == 404:
            logger.debug(f"PMID:{ids.pmid} not in PMC Open Access subset")
            return None
        if response.status_code != 200:
            logger.debug(f"BioC returned {response.status_code} for PMID:{ids.pmid}")
            return None

        text = self._extract_text(response.text)
        if not text or len(text) < MIN_FULLTEXT_CHARS:
            logger.debug(f"BioC returned insufficient text for PMID:{ids.pmid}")
            return None

        return FullTextLocation(
            text=text,
            format_hint="text",
            oa_status="green",
            provider="bioc",
        )

    def _extract_text(self, xml_content: str) -> Optional[str]:
        """Extract paragraph text from BioC XML.

        Args:
            xml_content: BioC XML response

        Returns:
            Concatenated passage text, or None if parsing fails

        Examples:
            >>> provider = BioCFullTextProvider()
            >>> xml = '''<collection><document>
            ...   <passage><text>Introduction text.</text></passage>
            ...   <passage><text>Methods section.</text></passage>
            ... </document></collection>'''
            >>> provider._extract_text(xml)
            'Introduction text.\\n\\nMethods section.'
        """
        try:
            soup = BeautifulSoup(xml_content, "xml")
        except Exception as exc:
            logger.debug(f"Failed to parse BioC XML: {exc}")
            return None

        passages = soup.find_all("passage")
        if not passages:
            return None

        texts = []
        for passage in passages:
            text_elem = passage.find("text")
            if text_elem and text_elem.string:
                text = text_elem.string.strip()
                if text:
                    texts.append(text)

        return "\n\n".join(texts) if texts else None
