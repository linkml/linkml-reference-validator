"""Fetching and caching of references from various sources.

This module provides the main ReferenceFetcher class that coordinates
fetching from various sources (PMID, DOI, file, URL) using a plugin architecture.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources import ReferenceSourceRegistry

logger = logging.getLogger(__name__)


class ReferenceFetcher:
    """Fetch and cache references from various sources.

    Uses a plugin architecture to support multiple reference types:
    - PMID (PubMed IDs)
    - DOI (Digital Object Identifiers via Crossref API)
    - file (local files)
    - url (web URLs)

    Examples:
        >>> config = ReferenceValidationConfig()
        >>> fetcher = ReferenceFetcher(config)
        >>> # This would fetch from NCBI in real usage
        >>> # ref = fetcher.fetch("PMID:12345678")

        >>> # Local file support
        >>> # ref = fetcher.fetch("file:./research/notes.md")

        >>> # URL support
        >>> # ref = fetcher.fetch("url:https://example.com/paper.html")
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

    def fetch(
        self, reference_id: str, force_refresh: bool = False
    ) -> Optional[ReferenceContent]:
        """Fetch a reference by ID.

        Supports various ID formats:
        - PMID:12345678
        - DOI:10.xxxx/yyyy
        - file:./path/to/file.md
        - url:https://example.com

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
            >>> # ref = fetcher.fetch("file:./notes.md")
        """
        normalized_reference_id = self._normalize_reference_id(reference_id)

        # Check memory cache
        if not force_refresh and normalized_reference_id in self._cache:
            return self._cache[normalized_reference_id]

        # Check disk cache
        if not force_refresh:
            cached = self._load_from_disk(normalized_reference_id)
            if cached:
                self._cache[normalized_reference_id] = cached
                return cached

        # Find appropriate source using registry
        source_class = ReferenceSourceRegistry.get_source(normalized_reference_id)
        if not source_class:
            logger.warning(f"No source found for reference type: {normalized_reference_id}")
            return None

        # Parse identifier and fetch
        _, identifier = self._parse_reference_id(normalized_reference_id)
        source = source_class()
        content = source.fetch(identifier, self.config)

        if content:
            self._cache[normalized_reference_id] = content
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
            >>> fetcher._parse_reference_id("file:./test.md")
            ('file', './test.md')
            >>> fetcher._parse_reference_id("url:https://example.com/page")
            ('url', 'https://example.com/page')
            >>> config = ReferenceValidationConfig(reference_prefix_map={"geo": "GEO"})
            >>> ReferenceFetcher(config)._parse_reference_id("geo:GSE12345")
            ('GEO', 'GSE12345')
        """
        stripped = reference_id.strip()

        # Standard prefix:identifier format
        match = re.match(r"^([A-Za-z_]+)[:\s]+(.+)$", stripped)
        if match:
            prefix = match.group(1)
            # Preserve case for file/url, uppercase for others
            prefix = self._normalize_prefix(prefix)
            prefix = self._apply_prefix_map(prefix)
            return prefix, match.group(2).strip()
        if reference_id.strip().isdigit():
            return "PMID", reference_id.strip()
        return "UNKNOWN", reference_id

    def _normalize_reference_id(self, reference_id: str) -> str:
        """Normalize reference IDs using configured prefix aliases."""
        prefix, identifier = self._parse_reference_id(reference_id)
        if prefix == "UNKNOWN":
            return reference_id.strip()
        return f"{prefix}:{identifier}"

    def _normalize_prefix(self, prefix: str) -> str:
        """Normalize prefix casing with special handling for file/url."""
        if prefix.lower() in ("file", "url"):
            return prefix.lower()
        return prefix.upper()

    def _apply_prefix_map(self, prefix: str) -> str:
        """Apply configured prefix aliases."""
        prefix_map = self._normalized_prefix_map()
        return prefix_map.get(prefix, prefix)

    def _normalized_prefix_map(self) -> dict[str, str]:
        """Return a case-normalized prefix map."""
        normalized: dict[str, str] = {}
        for key, value in self.config.reference_prefix_map.items():
            normalized[self._normalize_prefix(key)] = self._normalize_prefix(value)
        return normalized

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
            >>> path = fetcher._get_cache_path("url:https://example.com/book/chapter1")
            >>> path.name
            'url_https___example.com_book_chapter1.md'
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
        if lower_value in ("true", "false", "yes", "no", "on", "off", "null", "~"):
            needs_quote = True

        if needs_quote:
            # Escape any existing double quotes and wrap in double quotes
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
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
                lines.append(
                    f"**DOI:** [{reference.doi}](https://doi.org/{reference.doi})"
                )
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

    def _load_markdown_format(
        self, content_text: str, reference_id: str
    ) -> Optional[ReferenceContent]:
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

    def _load_legacy_format(
        self, content_text: str, reference_id: str
    ) -> Optional[ReferenceContent]:
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

        content = (
            "\n".join(lines[content_start:]).strip()
            if content_start < len(lines)
            else None
        )

        authors = (
            metadata.get("Authors", "").split(", ") if metadata.get("Authors") else None
        )

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
