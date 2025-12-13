"""Fetching and caching of references from various sources."""

import logging
import re
import time
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML  # type: ignore
from Bio import Entrez  # type: ignore
from bs4 import BeautifulSoup  # type: ignore
import requests  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig

logger = logging.getLogger(__name__)


class ReferenceFetcher:
    """Fetch and cache references from various sources.

    Currently supports:
    - PMID (PubMed IDs)
    - DOI (Digital Object Identifiers via Crossref API)

    Future support planned for:
    - URLs
    - Other databases

    Examples:
        >>> config = ReferenceValidationConfig()
        >>> fetcher = ReferenceFetcher(config)
        >>> # This would fetch from NCBI in real usage
        >>> # ref = fetcher.fetch("PMID:12345678")
    """

    def __init__(self, config: ReferenceValidationConfig):
        """Initialize the reference fetcher.

        Args:
            config: Configuration for fetching and caching

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher.config.email
            'linkml-reference-validator@example.com'
        """
        self.config = config
        self._cache: dict[str, ReferenceContent] = {}
        Entrez.email = config.email  # type: ignore

    def fetch(self, reference_id: str, force_refresh: bool = False) -> Optional[ReferenceContent]:
        """Fetch a reference by ID.

        Supports various ID formats:
        - PMID:12345678
        - DOI:10.xxxx/yyyy
        - URL:https://... (future)

        Args:
            reference_id: The reference identifier
            force_refresh: If True, bypass cache and fetch fresh

        Returns:
            ReferenceContent if found, None otherwise

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> # Would fetch in real usage:
            >>> # ref = fetcher.fetch("PMID:12345678")
        """
        if not force_refresh and reference_id in self._cache:
            return self._cache[reference_id]

        if not force_refresh:
            cached = self._load_from_disk(reference_id)
            if cached:
                self._cache[reference_id] = cached
                return cached

        prefix, identifier = self._parse_reference_id(reference_id)

        if prefix == "PMID":
            content = self._fetch_pmid(identifier)
        elif prefix == "DOI":
            content = self._fetch_doi(identifier)
        elif prefix == "URL":
            content = self._fetch_url(identifier)
        else:
            logger.warning(f"Unsupported reference type: {prefix}")
            return None

        if content:
            self._cache[reference_id] = content
            self._save_to_disk(content)

        return content

    def _parse_reference_id(self, reference_id: str) -> tuple[str, str]:
        """Parse a reference ID into prefix and identifier.

        Args:
            reference_id: Reference ID like "PMID:12345678" or URL

        Returns:
            Tuple of (prefix, identifier)

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._parse_reference_id("PMID:12345678")
            ('PMID', '12345678')
            >>> fetcher._parse_reference_id("PMID 12345678")
            ('PMID', '12345678')
            >>> fetcher._parse_reference_id("12345678")
            ('PMID', '12345678')
            >>> fetcher._parse_reference_id("URL:https://example.com/book/chapter1")
            ('URL', 'https://example.com/book/chapter1')
            >>> fetcher._parse_reference_id("https://example.com/direct")
            ('URL', 'https://example.com/direct')
        """
        stripped = reference_id.strip()
        
        # Check if it's a direct URL (starts with http or https)
        if stripped.startswith(('http://', 'https://')):
            return "URL", stripped
            
        # Standard prefix:identifier format
        match = re.match(r"^([A-Za-z_]+)[:\s]+(.+)$", stripped)
        if match:
            return match.group(1).upper(), match.group(2).strip()
            
        # Plain numeric ID defaults to PMID
        if stripped.isdigit():
            return "PMID", stripped
            
        return "UNKNOWN", stripped

    def _fetch_pmid(self, pmid: str) -> Optional[ReferenceContent]:
        """Fetch a publication from PubMed by PMID.

        Args:
            pmid: PubMed ID (without prefix)

        Returns:
            ReferenceContent if successful, None otherwise
        """
        time.sleep(self.config.rate_limit_delay)

        try:
            handle = Entrez.esummary(db="pubmed", id=pmid)
            records = Entrez.read(handle)
            handle.close()

            if not records:
                logger.warning(f"No records found for PMID:{pmid}")
                return None

            record = records[0] if isinstance(records, list) else records

            title = record.get("Title", "")
            authors = self._parse_authors(record.get("AuthorList", []))
            journal = record.get("Source", "")
            year = record.get("PubDate", "")[:4] if record.get("PubDate") else ""
            doi = record.get("DOI", "")

            abstract = self._fetch_abstract(pmid)
            full_text, content_type = self._fetch_pmc_fulltext(pmid)

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
            )

        except Exception as e:
            logger.error(f"Error fetching PMID:{pmid}: {e}")
            return None

    def _fetch_doi(self, doi: str) -> Optional[ReferenceContent]:
        """Fetch a publication from Crossref by DOI.

        Uses the Crossref API (https://api.crossref.org) to fetch metadata
        for a DOI.

        Args:
            doi: Digital Object Identifier (without prefix)

        Returns:
            ReferenceContent if successful, None otherwise

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> # Would fetch in real usage:
            >>> # ref = fetcher._fetch_doi("10.1234/test")
        """
        time.sleep(self.config.rate_limit_delay)

        url = f"https://api.crossref.org/works/{doi}"
        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{self.config.email})",
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

    def _fetch_url(self, url: str) -> Optional[ReferenceContent]:
        """Fetch content from a URL.

        Fetches web content, extracts title and converts HTML to text.
        Intended for static pages like book chapters.

        Args:
            url: The URL to fetch

        Returns:
            ReferenceContent if successful, None otherwise

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> # Would fetch in real usage:
            >>> # ref = fetcher._fetch_url("https://example.com/book/chapter1")
        """
        time.sleep(self.config.rate_limit_delay)

        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{self.config.email})",
        }

        try:
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code != 200:
                logger.warning(f"Failed to fetch URL:{url} - status {response.status_code}")
                return None

            soup = BeautifulSoup(response.text, "html.parser")

            # Extract title
            title_tag = soup.find("title")
            title = title_tag.get_text().strip() if title_tag else None

            # Convert HTML to text
            # Remove script and style elements
            for script in soup(["script", "style", "nav", "header", "footer"]):
                script.decompose()

            # Get text content
            content = soup.get_text()

            # Clean up text - normalize whitespace
            lines = (line.strip() for line in content.splitlines())
            content = "\n".join(line for line in lines if line)

            return ReferenceContent(
                reference_id=f"URL:{url}",
                title=title,
                content=content if content else None,
                content_type="html_converted",
            )

        except Exception as e:
            logger.error(f"Error fetching URL:{url}: {e}")
            return None

    def _parse_crossref_authors(self, authors: list) -> list[str]:
        """Parse author list from Crossref response.

        Args:
            authors: List of author dicts from Crossref

        Returns:
            List of formatted author names

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._parse_crossref_authors([{"given": "John", "family": "Smith"}])
            ['John Smith']
            >>> fetcher._parse_crossref_authors([{"family": "Smith"}])
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
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._extract_crossref_year({"published-print": {"date-parts": [[2024, 1, 15]]}})
            '2024'
            >>> fetcher._extract_crossref_year({"published-online": {"date-parts": [[2023]]}})
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
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._clean_abstract("<jats:p>Test abstract.</jats:p>")
            'Test abstract.'
        """
        if not abstract:
            return ""
        soup = BeautifulSoup(abstract, "html.parser")
        return soup.get_text().strip()

    def _parse_authors(self, author_list: list) -> list[str]:
        """Parse author list from Entrez record.

        Args:
            author_list: List of author names from Entrez

        Returns:
            List of formatted author names

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._parse_authors(["Smith J", "Doe A"])
            ['Smith J', 'Doe A']
        """
        return [str(author) for author in author_list if author]

    def _fetch_abstract(self, pmid: str) -> Optional[str]:
        """Fetch abstract for a PMID.

        Args:
            pmid: PubMed ID

        Returns:
            Abstract text if available
        """
        time.sleep(self.config.rate_limit_delay)

        handle = Entrez.efetch(db="pubmed", id=pmid, rettype="abstract", retmode="text")
        abstract_text = handle.read()
        handle.close()

        if abstract_text and len(abstract_text) > 50:
            return str(abstract_text)

        return None

    def _fetch_pmc_fulltext(self, pmid: str) -> tuple[Optional[str], str]:
        """Attempt to fetch full text from PMC.

        Args:
            pmid: PubMed ID

        Returns:
            Tuple of (full_text, content_type)
        """
        pmcid = self._get_pmcid(pmid)
        if not pmcid:
            return None, "no_pmc"

        full_text = self._fetch_pmc_xml(pmcid)
        if full_text and len(full_text) > 1000:
            return full_text, "full_text_xml"

        full_text = self._fetch_pmc_html(pmcid)
        if full_text and len(full_text) > 1000:
            return full_text, "full_text_html"

        return None, "pmc_restricted"

    def _get_pmcid(self, pmid: str) -> Optional[str]:
        """Get PMC ID for a PubMed ID.

        Args:
            pmid: PubMed ID

        Returns:
            PMC ID if available
        """
        time.sleep(self.config.rate_limit_delay)

        handle = Entrez.elink(dbfrom="pubmed", db="pmc", id=pmid, linkname="pubmed_pmc")
        result = Entrez.read(handle)
        handle.close()

        if result and result[0].get("LinkSetDb"):
            links = result[0]["LinkSetDb"][0].get("Link", [])
            if links:
                return links[0]["Id"]

        return None

    def _fetch_pmc_xml(self, pmcid: str) -> Optional[str]:
        """Fetch full text from PMC XML API.

        Args:
            pmcid: PMC ID

        Returns:
            Extracted text from XML
        """
        time.sleep(self.config.rate_limit_delay)

        handle = Entrez.efetch(db="pmc", id=pmcid, rettype="xml", retmode="xml")
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

    def _fetch_pmc_html(self, pmcid: str) -> Optional[str]:
        """Fetch full text from PMC HTML as fallback.

        Args:
            pmcid: PMC ID

        Returns:
            Extracted text from HTML
        """
        time.sleep(self.config.rate_limit_delay)

        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"

        response = requests.get(url, timeout=30)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.content, "html.parser")
        article_body = soup.find("div", class_="article-body") or soup.find("div", class_="tsec")

        if article_body:
            paragraphs = article_body.find_all("p")
            if paragraphs:
                text = "\n\n".join(p.get_text() for p in paragraphs)
                return text

        return None

    def _get_cache_path(self, reference_id: str) -> Path:
        """Get the cache file path for a reference.

        Args:
            reference_id: Reference identifier

        Returns:
            Path to cache file

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> path = fetcher._get_cache_path("PMID:12345678")
            >>> path.name
            'PMID_12345678.md'
            >>> path = fetcher._get_cache_path("URL:https://example.com/book/chapter1")
            >>> path.name
            'URL_https___example.com_book_chapter1.md'
        """
        safe_id = reference_id.replace(":", "_").replace("/", "_").replace("?", "_").replace("=", "_")
        cache_dir = self.config.get_cache_dir()
        return cache_dir / f"{safe_id}.md"

    def _quote_yaml_value(self, value: str) -> str:
        """Quote a YAML value if it contains special characters.

        YAML has many special characters that need quoting, including:
        - [ ] { } : , # & * ? | - < > = ! % @ `
        - Leading/trailing spaces
        - Values that look like booleans, nulls, or numbers

        Args:
            value: The string value to potentially quote

        Returns:
            The value, quoted if necessary

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._quote_yaml_value("[Cholera].")
            '"[Cholera]."'
            >>> fetcher._quote_yaml_value("Normal title")
            'Normal title'
            >>> fetcher._quote_yaml_value("Title: with colon")
            '"Title: with colon"'
        """
        # Characters that require quoting in YAML values
        special_chars = '[]{}:,#&*?|<>=!%@`"\'\\'
        needs_quote = False

        # Check for special characters
        for char in special_chars:
            if char in value:
                needs_quote = True
                break

        # Check for leading/trailing whitespace
        if value != value.strip():
            needs_quote = True

        # Check for values that YAML might misinterpret
        lower_value = value.lower()
        if lower_value in ('true', 'false', 'yes', 'no', 'on', 'off', 'null', '~'):
            needs_quote = True

        if needs_quote:
            # Escape any existing double quotes and wrap in double quotes
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            return f'"{escaped}"'

        return value

    def _save_to_disk(self, reference: ReferenceContent) -> None:
        """Save reference content to disk cache as markdown with YAML frontmatter.

        Args:
            reference: Reference content to save
        """
        cache_path = self._get_cache_path(reference.reference_id)

        lines = []
        lines.append("---")
        lines.append(f"reference_id: {reference.reference_id}")
        if reference.title:
            lines.append(f"title: {self._quote_yaml_value(reference.title)}")
        if reference.authors:
            lines.append("authors:")
            for author in reference.authors:
                lines.append(f"- {self._quote_yaml_value(author)}")
        if reference.journal:
            lines.append(f"journal: {self._quote_yaml_value(reference.journal)}")
        if reference.year:
            lines.append(f"year: '{reference.year}'")
        if reference.doi:
            lines.append(f"doi: {reference.doi}")
        lines.append(f"content_type: {reference.content_type}")
        lines.append("---")
        lines.append("")

        if reference.title:
            lines.append(f"# {reference.title}")
            if reference.authors:
                lines.append(f"**Authors:** {', '.join(reference.authors)}")
            if reference.journal:
                journal_info = reference.journal
                if reference.year:
                    journal_info += f" ({reference.year})"
                lines.append(f"**Journal:** {journal_info}")
            if reference.doi:
                lines.append(f"**DOI:** [{reference.doi}](https://doi.org/{reference.doi})")
            lines.append("")
            lines.append("## Content")
            lines.append("")

        if reference.content:
            lines.append(reference.content)

        cache_path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Cached {reference.reference_id} to {cache_path}")

    def _load_from_disk(self, reference_id: str) -> Optional[ReferenceContent]:
        """Load reference content from disk cache.

        Supports both new markdown format with YAML frontmatter and legacy text format.

        Args:
            reference_id: Reference identifier

        Returns:
            ReferenceContent if cached, None otherwise
        """
        cache_path = self._get_cache_path(reference_id)

        if not cache_path.exists():
            legacy_path = cache_path.with_suffix(".txt")
            if legacy_path.exists():
                cache_path = legacy_path
            else:
                return None

        content_text = cache_path.read_text(encoding="utf-8")

        if content_text.startswith("---"):
            return self._load_markdown_format(content_text, reference_id)
        else:
            return self._load_legacy_format(content_text, reference_id)

    def _load_markdown_format(self, content_text: str, reference_id: str) -> Optional[ReferenceContent]:
        """Load reference from markdown format with YAML frontmatter.

        Args:
            content_text: File contents
            reference_id: Reference identifier

        Returns:
            ReferenceContent if successful, None otherwise
        """
        parts = content_text.split("---", 2)
        if len(parts) < 3:
            logger.warning(f"Invalid markdown format for {reference_id}")
            return None

        yaml_parser = YAML(typ="safe")
        frontmatter = yaml_parser.load(parts[1])
        body = parts[2].strip()

        content = self._extract_content_from_markdown(body)

        authors = frontmatter.get("authors")
        if authors and isinstance(authors, list):
            authors = authors
        elif authors:
            authors = [authors]
        else:
            authors = None

        return ReferenceContent(
            reference_id=frontmatter.get("reference_id", reference_id),
            title=frontmatter.get("title"),
            content=content,
            content_type=frontmatter.get("content_type", "unknown"),
            authors=authors,
            journal=frontmatter.get("journal"),
            year=str(frontmatter.get("year")) if frontmatter.get("year") else None,
            doi=frontmatter.get("doi"),
        )

    def _extract_content_from_markdown(self, body: str) -> str:
        """Extract the actual content from markdown body.

        Removes the title, authors, journal, and DOI headers to get just the content.

        Args:
            body: Markdown body text

        Returns:
            Extracted content
        """
        lines = body.split("\n")
        content_start = 0

        for i, line in enumerate(lines):
            if line.strip().startswith("## Content"):
                content_start = i + 1
                break

        if content_start > 0:
            content_lines = lines[content_start:]
            while content_lines and not content_lines[0].strip():
                content_lines.pop(0)
            return "\n".join(content_lines)

        return body

    def _load_legacy_format(self, content_text: str, reference_id: str) -> Optional[ReferenceContent]:
        """Load reference from legacy text format.

        Args:
            content_text: File contents
            reference_id: Reference identifier

        Returns:
            ReferenceContent if successful, None otherwise
        """
        lines = content_text.split("\n")

        metadata = {}
        content_start = 0

        for i, line in enumerate(lines):
            if not line.strip():
                content_start = i + 1
                break
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()

        content = "\n".join(lines[content_start:]).strip() if content_start < len(lines) else None

        authors = metadata.get("Authors", "").split(", ") if metadata.get("Authors") else None

        return ReferenceContent(
            reference_id=metadata.get("ID", reference_id),
            title=metadata.get("Title"),
            content=content,
            content_type=metadata.get("ContentType", "unknown"),
            authors=authors,
            journal=metadata.get("Journal"),
            year=metadata.get("Year"),
            doi=metadata.get("DOI"),
        )
