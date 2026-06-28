"""Fetching and caching of references from various sources.

This module provides the main ReferenceFetcher class that coordinates
fetching from various sources (PMID, DOI, file, URL) using a plugin architecture.
"""

import logging
import re
from pathlib import Path
from typing import Optional

from ruamel.yaml import YAML  # type: ignore

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceContent,
    ReferenceValidationConfig,
    SupplementaryFile,
)
from linkml_reference_validator.etl.sources import ReferenceSourceRegistry
from linkml_reference_validator.etl.acquire import ContentAcquirer, resolve_format, sniff_format
from linkml_reference_validator.etl.identifiers import build_identifiers
from linkml_reference_validator.etl.extract import Extractor, ExtractorRegistry  # noqa: F401  (registers extractors)
from linkml_reference_validator.etl.extract.pdf import PDFExtractor
import linkml_reference_validator.etl.fulltext  # noqa: F401  (registers providers)
from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
from linkml_reference_validator.etl.fulltext.loader import register_custom_full_text_providers

logger = logging.getLogger(__name__)


NEEDS_FULL_TEXT_TYPES = {
    "abstract_only",
    "unavailable",
    "no_pmc",
    "pmc_restricted",
    "summary",
}

# Global floor for "did we actually get full text, or just a few stray characters?"
# Individual providers may set a stricter floor (e.g. PMC uses 2x this in pmc.py,
# since a PMC XML/HTML hit under ~1k chars is almost always a stub, not the body).
MIN_FULL_TEXT_CHARS = 500

_FORMAT_TO_CONTENT_TYPE = {
    "pdf": "full_text_pdf",
    "html": "full_text_html",
    "xml": "full_text_xml",
    "text": "full_text",
}


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
        self._acquirer = ContentAcquirer()
        # Build the PDF extractor once: this validates config.pdf_backend up front
        # (an unknown backend raises here, at init, rather than mid-fetch) and avoids
        # re-instantiating the backend on every download.
        self._pdf_extractor = PDFExtractor(backend=config.pdf_backend)
        register_custom_full_text_providers(config.full_text_providers_file)

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
        normalized_reference_id = self.normalize_reference_id(reference_id)

        # Check memory cache
        if not force_refresh and normalized_reference_id in self._cache:
            return self._cache[normalized_reference_id]

        # Check disk cache
        if not force_refresh:
            cached = self._load_from_disk(normalized_reference_id)
            if cached:
                # A record cached as abstract_only may predate full-text support, or
                # reflect a prior transient failure. Give the chain one more chance
                # per process if it was never cleanly attempted.
                cached = self._maybe_retry_full_text(cached)
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

        if content and self.config.fetch_full_text and self._needs_full_text(content):
            content = self._enrich_with_full_text(content)

        if content:
            self._cache[normalized_reference_id] = content
            self._save_to_disk(content)

        return content

    def _needs_full_text(self, content: ReferenceContent) -> bool:
        """Return True if the content lacks full text and the chain should run.

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> from linkml_reference_validator.models import ReferenceContent
            >>> fetcher._needs_full_text(
            ...     ReferenceContent(reference_id="DOI:1", content_type="abstract_only")
            ... )
            True
            >>> fetcher._needs_full_text(
            ...     ReferenceContent(reference_id="DOI:1", content_type="full_text_xml")
            ... )
            False
        """
        return content.content_type in NEEDS_FULL_TEXT_TYPES

    def _maybe_retry_full_text(self, content: ReferenceContent) -> ReferenceContent:
        """Re-run the full-text chain for a cached record that never cleanly tried.

        Leaves a record alone once it already has full text, when full-text fetching
        is disabled, or when a prior clean run already concluded none is available
        (``full_text_attempted``). When a retry changes the record it is re-saved so
        the result persists. This is what lets a one-off provider outage recover on a
        later run instead of being cached as permanent absence (PR #48 review #1).
        """
        if (
            not self.config.fetch_full_text
            or not self._needs_full_text(content)
            or content.full_text_attempted
        ):
            return content

        before = (content.content, content.content_type, content.full_text_attempted)
        content = self._enrich_with_full_text(content)
        after = (content.content, content.content_type, content.full_text_attempted)
        if after != before:
            self._save_to_disk(content)
        return content

    def _enrich_with_full_text(self, content: ReferenceContent) -> ReferenceContent:
        """Walk the provider chain; merge the first usable full text into content.

        If no provider yields usable full text but the chain was consulted without a
        transient error, mark ``full_text_attempted`` so the record is not re-queried
        on every later run. A provider/download error leaves the flag unset so a
        subsequent run retries (PR #48 review #1).
        """
        ids = build_identifiers(content)
        abstract = content.content
        had_error = False

        for provider_name in self.config.full_text_providers:
            provider = FullTextProviderRegistry.get(provider_name)
            if provider is None:
                logger.debug(f"Full-text provider not registered: {provider_name}")
                continue

            try:  # external system boundary: a provider failure must not abort the chain
                location = provider.locate(ids, self.config)
            except Exception as exc:
                logger.warning(f"Provider '{provider_name}' failed for {content.reference_id}: {exc}")
                had_error = True
                continue

            if location is None:
                continue

            text, fmt, pdf_bytes, error = self._materialize(location)
            if error:
                had_error = True
            if not text or len(text.strip()) < MIN_FULL_TEXT_CHARS:
                continue

            content.content = f"{abstract}\n\n{text}" if abstract else text
            content.content_type = _FORMAT_TO_CONTENT_TYPE.get(fmt or "text", "full_text")
            content.full_text_provider = location.provider or provider_name
            content.full_text_url = location.url
            content.oa_status = location.oa_status
            content.license = location.license
            content.full_text_attempted = True
            if pdf_bytes is not None and self.config.download_pdfs:
                content.local_pdf_path = self._save_pdf(content.reference_id, pdf_bytes)
            return content

        # No usable full text: only record a definitive attempt if nothing went wrong,
        # so a transient failure stays retryable on the next run.
        if not had_error:
            content.full_text_attempted = True
        return content

    def _materialize(
        self, location: FullTextLocation
    ) -> tuple[Optional[str], Optional[str], Optional[bytes], bool]:
        """Turn a FullTextLocation into ``(text, format, pdf_bytes_if_any, error)``.

        ``error`` is True only when a download or extraction *raised* — a transient
        condition worth retrying — not when the resource was merely absent or unusable.
        """
        if location.text:
            return location.text, location.format_hint or "text", None, False

        if not location.url:
            return None, None, None, False

        try:  # external system boundary
            data, content_type = self._acquirer.fetch_bytes(location.url, self.config)
        except Exception as exc:
            logger.warning(f"Download failed for {location.url}: {exc}")
            return None, None, None, True

        if data is None:
            return None, None, None, False

        # Trust the actual bytes over the server content-type / provider hint: a
        # url_for_pdf that really returns an HTML landing page must not reach pypdf.
        fmt = sniff_format(data) or resolve_format(content_type, location.url, location.format_hint)
        if fmt is None:
            return None, None, None, False

        extractor: Optional[Extractor]
        if fmt == "pdf":
            extractor = self._pdf_extractor
        else:
            extractor = ExtractorRegistry.get(fmt)
        if extractor is None:
            return None, fmt, None, False

        try:  # external system boundary: parsing arbitrary downloaded bytes
            text = extractor.extract(data, content_type=content_type)
        except Exception as exc:
            logger.warning(f"Extraction failed for {location.url}: {exc}")
            return None, fmt, None, True

        pdf_bytes = data if fmt == "pdf" else None
        return text, fmt, pdf_bytes, False

    def _save_pdf(self, reference_id: str, data: bytes) -> str:
        """Persist a downloaded PDF and return its path relative to the cache dir."""
        safe_id = (
            reference_id.replace(":", "_").replace("/", "_").replace("?", "_").replace("=", "_")
        )
        files_dir = self.config.get_files_cache_dir()
        pdf_path = files_dir / f"{safe_id}.pdf"
        pdf_path.write_bytes(data)
        return str(pdf_path.relative_to(self.config.cache_dir))

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
            >>> fetcher._parse_reference_id("https://example.com/page")
            ('url', 'https://example.com/page')
            >>> fetcher._parse_reference_id("http://example.com")
            ('url', 'http://example.com')
            >>> config = ReferenceValidationConfig(reference_prefix_map={"geo": "GEO"})
            >>> ReferenceFetcher(config)._parse_reference_id("geo:GSE12345")
            ('GEO', 'GSE12345')
        """
        stripped = reference_id.strip()

        # Handle bare HTTP/HTTPS URLs (before the prefix:identifier parsing)
        if stripped.lower().startswith(("http://", "https://")):
            return "url", stripped

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

    def normalize_reference_id(self, reference_id: str) -> str:
        """Normalize reference IDs using configured prefix aliases.

        Args:
            reference_id: Raw reference ID (e.g., "pmid:12345678", "PMID 12345678")

        Returns:
            Normalized reference ID (e.g., "PMID:12345678")

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher.normalize_reference_id("pmid:12345678")
            'PMID:12345678'
            >>> fetcher.normalize_reference_id("PMID 12345678")
            'PMID:12345678'
        """
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

    def get_cache_path(self, reference_id: str) -> Path:
        """Get the cache file path for a reference.

        Args:
            reference_id: Reference identifier

        Returns:
            Path to cache file

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> path = fetcher.get_cache_path("PMID:12345678")
            >>> path.name
            'PMID_12345678.md'
            >>> path = fetcher.get_cache_path("url:https://example.com/book/chapter1")
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
        cache_path = self.get_cache_path(reference.reference_id)

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
        if reference.keywords:
            lines.append("keywords:")
            for keyword in reference.keywords:
                lines.append(f"- {self._quote_yaml_value(keyword)}")
        lines.append(f"content_type: {reference.content_type}")
        if reference.is_preprint is not None:
            lines.append(f"is_preprint: {str(reference.is_preprint).lower()}")
        if reference.peer_review_status:
            lines.append(f"peer_review_status: {reference.peer_review_status}")
        if reference.full_text_attempted:
            lines.append("full_text_attempted: true")
        if reference.full_text_provider:
            lines.append(f"full_text_provider: {reference.full_text_provider}")
        if reference.full_text_url:
            lines.append(f"full_text_url: {self._quote_yaml_value(reference.full_text_url)}")
        if reference.oa_status:
            lines.append(f"oa_status: {reference.oa_status}")
        if reference.license:
            lines.append(f"license: {self._quote_yaml_value(reference.license)}")
        if reference.local_pdf_path:
            lines.append(f"local_pdf_path: {self._quote_yaml_value(reference.local_pdf_path)}")
        if reference.metadata and "extra_fields_captured" in reference.metadata:
            extra_fields = reference.metadata.get("extra_fields_captured")
            if isinstance(extra_fields, list):
                lines.append("extra_fields_captured:")
                for field_name in extra_fields:
                    if isinstance(field_name, str):
                        lines.append(f"- {self._quote_yaml_value(field_name)}")
                    else:
                        logger.warning(
                            "Skipping non-string item in extra_fields_captured: %r (type %s)",
                            field_name,
                            type(field_name).__name__,
                        )
        if reference.supplementary_files:
            lines.append("supplementary_files:")
            for sf in reference.supplementary_files:
                lines.append(f"  - filename: {self._quote_yaml_value(sf.filename)}")
                if sf.download_url:
                    lines.append(f"    download_url: {self._quote_yaml_value(sf.download_url)}")
                if sf.content_type:
                    lines.append(f"    content_type: {sf.content_type}")
                if sf.size_bytes is not None:
                    lines.append(f"    size_bytes: {sf.size_bytes}")
                if sf.checksum:
                    lines.append(f"    checksum: {sf.checksum}")
                if sf.description:
                    lines.append(f"    description: {self._quote_yaml_value(sf.description)}")
                if sf.local_path:
                    lines.append(f"    local_path: {self._quote_yaml_value(sf.local_path)}")
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
        cache_path = self.get_cache_path(reference_id)

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

        keywords = frontmatter.get("keywords")
        if keywords and isinstance(keywords, list):
            keywords = keywords
        elif keywords:
            keywords = [keywords]
        else:
            keywords = None

        # Parse supplementary files
        supplementary_files = self._parse_supplementary_files(
            frontmatter.get("supplementary_files")
        )

        metadata: dict = {}
        if "extra_fields_captured" in frontmatter:
            metadata["extra_fields_captured"] = frontmatter["extra_fields_captured"]

        return ReferenceContent(
            reference_id=frontmatter.get("reference_id", reference_id),
            title=frontmatter.get("title"),
            content=content,
            content_type=frontmatter.get("content_type", "unknown"),
            authors=authors,
            journal=frontmatter.get("journal"),
            year=str(frontmatter.get("year")) if frontmatter.get("year") else None,
            doi=frontmatter.get("doi"),
            keywords=keywords,
            supplementary_files=supplementary_files,
            metadata=metadata,
            full_text_provider=frontmatter.get("full_text_provider"),
            full_text_url=frontmatter.get("full_text_url"),
            oa_status=frontmatter.get("oa_status"),
            license=frontmatter.get("license"),
            local_pdf_path=frontmatter.get("local_pdf_path"),
            is_preprint=frontmatter.get("is_preprint"),
            peer_review_status=frontmatter.get("peer_review_status"),
            full_text_attempted=bool(frontmatter.get("full_text_attempted", False)),
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

    def _parse_supplementary_files(
        self, files_data: Optional[list]
    ) -> Optional[list[SupplementaryFile]]:
        """Parse supplementary files from YAML frontmatter data.

        Args:
            files_data: List of file dicts from YAML frontmatter

        Returns:
            List of SupplementaryFile objects, or None if no files

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._parse_supplementary_files(None) is None
            True
            >>> fetcher._parse_supplementary_files([]) is None
            True
            >>> files = fetcher._parse_supplementary_files([
            ...     {"filename": "test.pdf", "size_bytes": 1000}
            ... ])
            >>> len(files)
            1
            >>> files[0].filename
            'test.pdf'
        """
        if not files_data:
            return None

        files = []
        for f in files_data:
            if not isinstance(f, dict):
                continue
            filename = f.get("filename")
            if not filename:
                continue
            files.append(
                SupplementaryFile(
                    filename=filename,
                    download_url=f.get("download_url"),
                    content_type=f.get("content_type"),
                    size_bytes=f.get("size_bytes"),
                    checksum=f.get("checksum"),
                    description=f.get("description"),
                    local_path=f.get("local_path"),
                )
            )

        return files if files else None

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
