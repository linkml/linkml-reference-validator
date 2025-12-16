"""DOI (Digital Object Identifier) reference source.

Fetches publication metadata from Crossref API.

Examples:
    >>> from linkml_reference_validator.etl.sources.doi import DOISource
    >>> DOISource.prefix()
    'DOI'
    >>> DOISource.can_handle("DOI:10.1234/test")
    True
"""

import logging
import time
from typing import Optional

from bs4 import BeautifulSoup  # type: ignore
import requests  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)


@ReferenceSourceRegistry.register
class DOISource(ReferenceSource):
    """Fetch references from Crossref using DOI.

    Uses the Crossref API (https://api.crossref.org) to fetch publication metadata.

    Examples:
        >>> source = DOISource()
        >>> source.prefix()
        'DOI'
        >>> source.can_handle("DOI:10.1234/test")
        True
    """

    @classmethod
    def prefix(cls) -> str:
        """Return 'DOI' prefix.

        Examples:
            >>> DOISource.prefix()
            'DOI'
        """
        return "DOI"

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch a publication from Crossref by DOI.

        Args:
            identifier: DOI (without prefix)
            config: Configuration including rate limiting and email

        Returns:
            ReferenceContent if successful, None otherwise

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> config = ReferenceValidationConfig()
            >>> source = DOISource()
            >>> # Would fetch in real usage:
            >>> # ref = source.fetch("10.1234/test", config)
        """
        doi = identifier.strip()
        time.sleep(config.rate_limit_delay)

        url = f"https://api.crossref.org/works/{doi}"
        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
        }

        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Failed to fetch DOI:{doi} - status {response.status_code}")
            return None

        data = response.json()
        if data.get("status") != "ok":
            logger.warning(f"Crossref API error for DOI:{doi}")
            return None

        message = data.get("message", {})

        title_list = message.get("title", [])
        title = title_list[0] if title_list else ""

        authors = self._parse_crossref_authors(message.get("author", []))

        container_title = message.get("container-title", [])
        journal = container_title[0] if container_title else ""

        year = self._extract_crossref_year(message)

        abstract = self._clean_abstract(message.get("abstract", ""))

        return ReferenceContent(
            reference_id=f"DOI:{doi}",
            title=title,
            content=abstract if abstract else None,
            content_type="abstract_only" if abstract else "unavailable",
            authors=authors,
            journal=journal,
            year=year,
            doi=doi,
        )

    def _parse_crossref_authors(self, authors: list) -> list[str]:
        """Parse author list from Crossref response.

        Args:
            authors: List of author dicts from Crossref

        Returns:
            List of formatted author names

        Examples:
            >>> source = DOISource()
            >>> source._parse_crossref_authors([{"given": "John", "family": "Smith"}])
            ['John Smith']
            >>> source._parse_crossref_authors([{"family": "Smith"}])
            ['Smith']
        """
        result = []
        for author in authors:
            given = author.get("given", "")
            family = author.get("family", "")
            if given and family:
                result.append(f"{given} {family}")
            elif family:
                result.append(family)
            elif given:
                result.append(given)
        return result

    def _extract_crossref_year(self, message: dict) -> str:
        """Extract publication year from Crossref message.

        Tries multiple date fields in order of preference.

        Args:
            message: Crossref message dict

        Returns:
            Year as string, or empty string if not found

        Examples:
            >>> source = DOISource()
            >>> source._extract_crossref_year({"published-print": {"date-parts": [[2024, 1, 15]]}})
            '2024'
            >>> source._extract_crossref_year({"published-online": {"date-parts": [[2023]]}})
            '2023'
        """
        for date_field in ["published-print", "published-online", "created", "issued"]:
            date_info = message.get(date_field, {})
            date_parts = date_info.get("date-parts", [[]])
            if date_parts and date_parts[0]:
                return str(date_parts[0][0])
        return ""

    def _clean_abstract(self, abstract: str) -> str:
        """Clean JATS/XML markup from abstract text.

        Args:
            abstract: Abstract text potentially containing JATS markup

        Returns:
            Clean abstract text

        Examples:
            >>> source = DOISource()
            >>> source._clean_abstract("<jats:p>Test abstract.</jats:p>")
            'Test abstract.'
        """
        if not abstract:
            return ""
        soup = BeautifulSoup(abstract, "html.parser")
        return soup.get_text().strip()
