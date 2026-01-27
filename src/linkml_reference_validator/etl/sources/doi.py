"""DOI (Digital Object Identifier) reference source.

Fetches publication metadata from Crossref API, with fallback to DataCite
for DOIs not found in Crossref (e.g., Zenodo, Figshare, Dryad).

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

from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
    SupplementaryFile,
)
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)


@ReferenceSourceRegistry.register
class DOISource(ReferenceSource):
    """Fetch references from Crossref using DOI, with DataCite fallback.

    Uses the Crossref API (https://api.crossref.org) to fetch publication metadata.
    Falls back to DataCite API (https://api.datacite.org) for DOIs not found in
    Crossref (e.g., Zenodo, Figshare, Dryad DOIs).

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
        """Fetch a publication by DOI from Crossref, falling back to DataCite.

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

        # Try Crossref first
        result = self._fetch_from_crossref(doi, config)
        if result:
            return result

        # Fall back to DataCite (handles Zenodo, Figshare, Dryad, etc.)
        return self._fetch_from_datacite(doi, config)

    def _fetch_from_crossref(
        self, doi: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch from Crossref API.

        Args:
            doi: DOI string (without prefix)
            config: Configuration including rate limiting and email

        Returns:
            ReferenceContent if successful, None otherwise
        """
        url = f"https://api.crossref.org/works/{doi}"
        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
        }

        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.debug(f"Crossref returned {response.status_code} for DOI:{doi}, will try DataCite")
            return None

        data = response.json()
        if data.get("status") != "ok":
            logger.debug(f"Crossref API error for DOI:{doi}, will try DataCite")
            return None

        message = data.get("message", {})

        title_list = message.get("title", [])
        title = title_list[0] if title_list else ""

        authors = self._parse_crossref_authors(message.get("author", []))

        container_title = message.get("container-title", [])
        journal = container_title[0] if container_title else ""

        year = self._extract_crossref_year(message)

        abstract = self._clean_abstract(message.get("abstract", ""))

        # Extract keywords/subjects from Crossref
        keywords = self._parse_crossref_subjects(message.get("subject", []))

        return ReferenceContent(
            reference_id=f"DOI:{doi}",
            title=title,
            content=abstract if abstract else None,
            content_type="abstract_only" if abstract else "unavailable",
            authors=authors,
            journal=journal,
            year=year,
            doi=doi,
            keywords=keywords,
        )

    def _fetch_from_datacite(
        self, doi: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch from DataCite API (handles Zenodo, Figshare, Dryad, etc.).

        Also fetches supplementary file metadata from repository-specific APIs
        when available (e.g., Zenodo API for Zenodo DOIs).

        Args:
            doi: DOI string (without prefix)
            config: Configuration including rate limiting and email

        Returns:
            ReferenceContent if successful, None otherwise
        """
        url = f"https://api.datacite.org/dois/{doi}"
        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
            "Accept": "application/json",
        }

        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Failed to fetch DOI:{doi} from both Crossref and DataCite")
            return None

        data = response.json()
        attributes = data.get("data", {}).get("attributes", {})

        # Extract title
        titles = attributes.get("titles", [])
        title = titles[0].get("title", "") if titles else ""

        # Extract authors
        authors = self._parse_datacite_creators(attributes.get("creators", []))

        # Extract year
        year = str(attributes.get("publicationYear", ""))

        # Extract abstract from descriptions
        abstract = ""
        for desc in attributes.get("descriptions", []):
            if desc.get("descriptionType") == "Abstract":
                abstract = desc.get("description", "")
                break

        # Publisher as journal equivalent
        publisher = attributes.get("publisher", "")

        # Extract keywords/subjects
        keywords = self._parse_datacite_subjects(attributes.get("subjects", []))

        # Fetch supplementary files from repository-specific APIs
        supplementary_files = self._fetch_repository_files(doi, config)

        return ReferenceContent(
            reference_id=f"DOI:{doi}",
            title=title,
            content=abstract if abstract else None,
            content_type="abstract_only" if abstract else "unavailable",
            authors=authors,
            journal=publisher,
            year=year,
            doi=doi,
            keywords=keywords,
            supplementary_files=supplementary_files,
        )

    def _detect_repository(self, doi: str) -> Optional[str]:
        """Detect repository from DOI prefix.

        Args:
            doi: DOI string (without prefix)

        Returns:
            Repository name if detected, None otherwise

        Examples:
            >>> source = DOISource()
            >>> source._detect_repository("10.5281/zenodo.7961621")
            'zenodo'
            >>> source._detect_repository("10.1038/s41586-024-12345") is None
            True
        """
        # Zenodo DOIs: 10.5281/zenodo.{record_id}
        if doi.startswith("10.5281/zenodo."):
            return "zenodo"
        # Can add more repositories here:
        # Figshare: 10.6084/m9.figshare.{id}
        # Dryad: 10.5061/dryad.{id}
        return None

    def _extract_zenodo_record_id(self, doi: str) -> Optional[str]:
        """Extract Zenodo record ID from DOI.

        Args:
            doi: DOI string (without prefix)

        Returns:
            Record ID if Zenodo DOI, None otherwise

        Examples:
            >>> source = DOISource()
            >>> source._extract_zenodo_record_id("10.5281/zenodo.7961621")
            '7961621'
            >>> source._extract_zenodo_record_id("10.1038/s41586-024-12345") is None
            True
        """
        if doi.startswith("10.5281/zenodo."):
            return doi.split("zenodo.")[1]
        return None

    def _fetch_repository_files(
        self, doi: str, config: ReferenceValidationConfig
    ) -> Optional[list[SupplementaryFile]]:
        """Fetch supplementary file metadata from repository-specific APIs.

        Args:
            doi: DOI string (without prefix)
            config: Configuration

        Returns:
            List of SupplementaryFile objects, or None if no files or unsupported repo
        """
        repository = self._detect_repository(doi)
        if repository == "zenodo":
            record_id = self._extract_zenodo_record_id(doi)
            if record_id:
                return self._fetch_zenodo_files(record_id, config)
        # Add more repository handlers here as needed
        return None

    def _fetch_zenodo_files(
        self, record_id: str, config: ReferenceValidationConfig
    ) -> Optional[list[SupplementaryFile]]:
        """Fetch file metadata from Zenodo API.

        Args:
            record_id: Zenodo record ID
            config: Configuration

        Returns:
            List of SupplementaryFile objects, or None if fetch fails
        """
        url = f"https://zenodo.org/api/records/{record_id}"
        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
            "Accept": "application/json",
        }

        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code != 200:
            logger.debug(f"Failed to fetch Zenodo files for record {record_id}")
            return None

        data = response.json()
        files_data = data.get("files", [])

        if not files_data:
            return None

        files = []
        for f in files_data:
            download_url = f.get("links", {}).get("self")
            files.append(
                SupplementaryFile(
                    filename=f.get("key", ""),
                    download_url=download_url,
                    size_bytes=f.get("size"),
                    checksum=f.get("checksum"),
                )
            )

        return files if files else None

    def _parse_datacite_creators(self, creators: list) -> list[str]:
        """Parse creator list from DataCite response.

        Args:
            creators: List of creator dicts from DataCite

        Returns:
            List of formatted author names

        Examples:
            >>> source = DOISource()
            >>> source._parse_datacite_creators([{"name": "Mungall, Christopher"}])
            ['Mungall, Christopher']
            >>> source._parse_datacite_creators([{"givenName": "John", "familyName": "Smith"}])
            ['John Smith']
        """
        result = []
        for creator in creators:
            # DataCite may have full name or given/family
            name = creator.get("name")
            if not name:
                given = creator.get("givenName", "")
                family = creator.get("familyName", "")
                if given and family:
                    name = f"{given} {family}"
                elif family:
                    name = family
                elif given:
                    name = given
            if name:
                result.append(name)
        return result

    def _parse_datacite_subjects(self, subjects: list) -> Optional[list[str]]:
        """Parse subjects/keywords from DataCite response.

        Args:
            subjects: List of subject dicts from DataCite

        Returns:
            List of subject strings, or None if empty

        Examples:
            >>> source = DOISource()
            >>> source._parse_datacite_subjects([{"subject": "Climate Change"}])
            ['Climate Change']
            >>> source._parse_datacite_subjects([]) is None
            True
        """
        if not subjects:
            return None
        result = []
        for subj in subjects:
            if isinstance(subj, dict):
                text = subj.get("subject")
                if text:
                    result.append(text)
            elif isinstance(subj, str):
                result.append(subj)
        return result if result else None

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

    def _parse_crossref_subjects(self, subjects: list) -> Optional[list[str]]:
        """Parse subjects/keywords from Crossref response.

        Args:
            subjects: List of subject strings from Crossref

        Returns:
            List of subject strings, or None if empty

        Examples:
            >>> source = DOISource()
            >>> source._parse_crossref_subjects(["General Chemistry", "Biochemistry"])
            ['General Chemistry', 'Biochemistry']
            >>> source._parse_crossref_subjects([]) is None
            True
        """
        if not subjects:
            return None
        result = [str(s) for s in subjects if s]
        return result if result else None

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
