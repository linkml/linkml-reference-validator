"""Local file reference source.

Reads content from local files (markdown, text, HTML, SVG).

Examples:
    >>> from linkml_reference_validator.etl.sources.file import FileSource
    >>> FileSource.prefix()
    'file'
    >>> FileSource.can_handle("file:./notes.md")
    True
"""

import logging
import re
from pathlib import Path
from typing import Optional

from linkml_reference_validator.etl.acquire import resolve_format
from linkml_reference_validator.etl.extract import ExtractorRegistry
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)


@ReferenceSourceRegistry.register
class FileSource(ReferenceSource):
    """Fetch reference content from local files.

    Supports markdown (.md), plain text (.txt), HTML (.html) and SVG (.svg)
    files. Content is read as-is without parsing (HTML entities preserved),
    except for SVG: a figure is matched against the text it renders, read by
    :class:`~linkml_reference_validator.etl.extract.svg.SVGExtractor`, so a
    quote cannot pass against markup, attributes or hidden text. An SVG with
    no rendered text, or whose rendered text cannot be determined, is
    ``unavailable``.

    Path resolution:
    - Absolute paths work directly
    - Relative paths use reference_base_dir from config if set, otherwise CWD

    Examples:
        >>> source = FileSource()
        >>> source.prefix()
        'file'
        >>> source.can_handle("file:./notes.md")
        True
    """

    @classmethod
    def prefix(cls) -> str:
        """Return 'file' prefix.

        Examples:
            >>> FileSource.prefix()
            'file'
        """
        return "file"

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Read content from a local file.

        Args:
            identifier: File path (without 'file:' prefix)
            config: Configuration including reference_base_dir

        Returns:
            ReferenceContent if file exists and is readable, None otherwise

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> config = ReferenceValidationConfig()
            >>> source = FileSource()
            >>> # Would read file in real usage:
            >>> # ref = source.fetch("./notes.md", config)
        """
        file_path = self._resolve_path(identifier, config)

        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None

        if not file_path.is_file():
            logger.warning(f"Not a file: {file_path}")
            return None

        if resolve_format(None, file_path.name, None) == "svg":
            return self._fetch_svg(file_path)

        content = file_path.read_text(encoding="utf-8")
        title = self._extract_title(content, file_path)

        return ReferenceContent(
            reference_id=f"file:{file_path}",
            title=title,
            content=content,
            content_type="local_file",
        )

    def _fetch_svg(self, file_path: Path) -> ReferenceContent:
        """Read an SVG figure as the text it renders, one line per label.

        Examples:
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as d:
            ...     figure = Path(d) / "fig.svg"
            ...     _ = figure.write_text(
            ...         '<svg xmlns="http://www.w3.org/2000/svg">'
            ...         '<desc>Hidden</desc><text>PTEN</text></svg>')
            ...     ref = FileSource()._fetch_svg(figure)
            >>> (ref.content, ref.content_type, ref.title)
            ('PTEN', 'local_svg', 'fig.svg')
        """
        extractor = ExtractorRegistry.get("svg")
        assert extractor is not None, "SVGExtractor is registered on import"
        text = extractor.extract(file_path.read_bytes(), content_type="image/svg+xml")
        return ReferenceContent(
            reference_id=f"file:{file_path}",
            title=file_path.name,
            content=text,
            content_type="local_svg" if text else "unavailable",
        )

    def _resolve_path(self, identifier: str, config: ReferenceValidationConfig) -> Path:
        """Resolve a file path from identifier.

        - Absolute paths are used directly
        - Relative paths use reference_base_dir if set, otherwise CWD

        Args:
            identifier: File path string
            config: Configuration with optional reference_base_dir

        Returns:
            Resolved Path object

        Examples:
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> source = FileSource()
            >>> config = ReferenceValidationConfig()
            >>> # Absolute path stays absolute
            >>> p = source._resolve_path("/tmp/test.md", config)
            >>> p.is_absolute()
            True
        """
        path = Path(identifier)

        # Absolute paths are used directly
        if path.is_absolute():
            return path

        # Relative paths: use base_dir if set, otherwise CWD
        base_dir = getattr(config, "reference_base_dir", None)
        if base_dir is not None:
            return Path(base_dir) / path
        else:
            return Path.cwd() / path

    def _extract_title(self, content: str, file_path: Path) -> str:
        """Extract title from content or use filename.

        For markdown files, extracts the first # heading.
        Falls back to filename otherwise.

        Args:
            content: File content
            file_path: Path to file

        Returns:
            Extracted title or filename

        Examples:
            >>> source = FileSource()
            >>> source._extract_title("# My Title\\n\\nContent", Path("test.md"))
            'My Title'
            >>> source._extract_title("No heading here", Path("notes.txt"))
            'notes.txt'
        """
        # Look for markdown heading
        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()

        # Fall back to filename
        return file_path.name
