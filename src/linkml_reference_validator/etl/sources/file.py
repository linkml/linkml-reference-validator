"""Local file reference source.

Reads content from local files (markdown, text, HTML, SVG, drawio).

Examples:
    >>> from linkml_reference_validator.etl.sources.file import FileSource
    >>> FileSource.prefix()
    'file'
    >>> FileSource.can_handle("file:./notes.md")
    True
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from linkml_reference_validator.etl.acquire import resolve_format
from linkml_reference_validator.etl.extract import ExtractorRegistry
from linkml_reference_validator.matching import FIGURE_CONTENT_TYPES
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)


@ReferenceSourceRegistry.register
class FileSource(ReferenceSource):
    """Fetch reference content from local files.

    Supports markdown (.md), plain text (.txt), HTML (.html), SVG (.svg) and
    drawio (.drawio, .drawio.xml) files. Content is read as-is without parsing
    (HTML entities preserved), except for figures: an SVG or drawio figure is
    matched against the text it renders, read by
    :class:`~linkml_reference_validator.etl.extract.svg.SVGExtractor` or
    :class:`~linkml_reference_validator.etl.extract.drawio.DrawioExtractor`,
    so a quote cannot pass against markup, attributes or hidden text. A figure
    with no rendered text, or whose rendered text cannot be determined, is
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
        file_path = self.resolve_path(identifier, config)

        if not file_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None

        if not file_path.is_file():
            logger.warning(f"Not a file: {file_path}")
            return None

        figure_format = resolve_format(None, file_path.name, None)
        if figure_format in FIGURE_CONTENT_TYPES:
            return self._fetch_figure(file_path, figure_format)

        content = file_path.read_text(encoding="utf-8")
        title = self._extract_title(content, file_path)

        return ReferenceContent(
            reference_id=f"file:{file_path}",
            title=title,
            content=content,
            content_type="local_file",
        )

    def _fetch_figure(self, file_path: Path, figure_format: str) -> ReferenceContent:
        """Read an SVG or drawio figure as the labels it draws.

        Examples:
            >>> import tempfile
            >>> with tempfile.TemporaryDirectory() as d:
            ...     figure = Path(d) / "fig.svg"
            ...     _ = figure.write_text(
            ...         '<svg xmlns="http://www.w3.org/2000/svg">'
            ...         '<desc>Hidden</desc><text>PTEN</text></svg>')
            ...     ref = FileSource()._fetch_figure(figure, "svg")
            >>> (ref.content, ref.content_type, ref.title)
            ('PTEN', 'local_svg', 'fig.svg')
        """
        # The registry maps each figure format to its extractor.
        extractor = ExtractorRegistry.get(figure_format)
        if extractor is None:
            raise LookupError(f"no extractor is registered for {figure_format}")
        text = extractor.extract(file_path.read_bytes())
        return ReferenceContent(
            reference_id=f"file:{file_path}",
            title=file_path.name,
            content=text,
            content_type=FIGURE_CONTENT_TYPES[figure_format] if text else "unavailable",
        )

    @staticmethod
    def resolve_path(identifier: str, config: ReferenceValidationConfig) -> Path:
        """Resolve a file path from identifier.

        - Absolute paths are used directly
        - Relative paths use reference_base_dir if set, otherwise CWD

        The result is absolute with ``.`` and ``..`` collapsed, so relative and
        absolute spellings of one path give one path, and one cache key (#135).
        Symlinks are deliberately not followed: a report names the path the
        curator wrote, and repointing a link (a "current version" link, say)
        does not leave an entry under the old target behind. A link and its
        target are therefore two references, each read live from the file.

        Args:
            identifier: File path string
            config: Configuration with optional reference_base_dir

        Returns:
            Resolved absolute Path object

        Examples:
            >>> import tempfile
            >>> from linkml_reference_validator.models import ReferenceValidationConfig
            >>> with tempfile.TemporaryDirectory() as d:
            ...     config = ReferenceValidationConfig(reference_base_dir=Path(d))
            ...     relative = FileSource.resolve_path("./sub/../notes.md", config)
            ...     absolute = FileSource.resolve_path(str(Path(d) / "notes.md"), config)
            >>> relative == absolute and relative.is_absolute()
            True
        """
        path = Path(identifier)

        # Relative paths: use base_dir if set, otherwise CWD
        if not path.is_absolute():
            base_dir = getattr(config, "reference_base_dir", None)
            path = Path(base_dir) / path if base_dir is not None else Path.cwd() / path
        return Path(os.path.abspath(path))

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
