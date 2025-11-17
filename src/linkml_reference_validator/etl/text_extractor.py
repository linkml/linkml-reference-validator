"""Text extraction utilities for extracting supporting text and references from plain text files."""

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ExtractedTextMatch:
    """A match extracted from text using regex.

    Examples:
        >>> match = ExtractedTextMatch(
        ...     line_number=42,
        ...     supporting_text="cellulosome contains up to 11 enzymes",
        ...     reference_id="PMID:11601609",
        ...     original_line='def: "..." [PMID:11601609] {ex:supporting_text="cellulosome contains up to 11 enzymes[PMID:11601609]"}'
        ... )
        >>> match.line_number
        42
        >>> match.reference_id
        'PMID:11601609'
    """

    line_number: int
    supporting_text: str
    reference_id: str
    original_line: str


class TextExtractor:
    r"""Extract supporting text and reference IDs from plain text files using regex.

    Examples:
        >>> extractor = TextExtractor(
        ...     regex_pattern=r'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"',
        ...     text_group=1,
        ...     ref_group=2
        ... )
        >>> line = 'def: "..." [PMID:123] {ex:supporting_text="test text[PMID:123]"}'
        >>> class_matches = list(extractor.extract_from_text(line, line_number=1))
        >>> len(class_matches)
        1
        >>> class_matches[0].supporting_text
        'test text'
        >>> class_matches[0].reference_id
        'PMID:123'
    """

    def __init__(
        self,
        regex_pattern: str,
        text_group: int = 1,
        ref_group: int = 2,
    ):
        r"""Initialize the text extractor.

        Args:
            regex_pattern: Regular expression pattern with capture groups
            text_group: Capture group number for supporting text (1-indexed)
            ref_group: Capture group number for reference ID (1-indexed)

        Examples:
            >>> extractor = TextExtractor(r'text="([^"]*)" ref=(\S+)', 1, 2)
            >>> extractor.text_group
            1
            >>> extractor.ref_group
            2
        """
        self.regex_pattern = regex_pattern
        self.text_group = text_group
        self.ref_group = ref_group
        self._compiled_regex = re.compile(regex_pattern)

    def extract_from_text(
        self, text: str, line_number: int = 1
    ) -> list[ExtractedTextMatch]:
        r"""Extract matches from a single line of text.

        Args:
            text: The text to extract from
            line_number: The line number (for tracking)

        Returns:
            List of extracted matches (may be empty if no matches found)

        Examples:
            >>> ext2 = TextExtractor(r'ref="([^"]+)" id=(\S+)')
            >>> results = ext2.extract_from_text('ref="some text" id=PMID:123', 1)
            >>> len(results)
            1
            >>> results[0].supporting_text
            'some text'
            >>> results[0].reference_id
            'PMID:123'
            >>> results[0].line_number
            1
        """
        matches = []
        for match in self._compiled_regex.finditer(text):
            supporting_text = match.group(self.text_group)
            reference_id = match.group(self.ref_group)
            matches.append(
                ExtractedTextMatch(
                    line_number=line_number,
                    supporting_text=supporting_text,
                    reference_id=reference_id,
                    original_line=text.rstrip(),
                )
            )
        return matches

    def extract_from_file(self, file_path: Path) -> list[ExtractedTextMatch]:
        r"""Extract matches from a file, line by line.

        Args:
            file_path: Path to the text file

        Returns:
            List of all extracted matches from the file

        Examples:
            >>> import tempfile
            >>> extractor = TextExtractor(r'text="([^"]+)" ref=(\S+)')
            >>> with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            ...     _ = f.write('line 1: text="hello" ref=PMID:1\n')
            ...     _ = f.write('line 2: no match here\n')
            ...     _ = f.write('line 3: text="world" ref=PMID:2\n')
            ...     temp_path = f.name
            >>> matches = extractor.extract_from_file(Path(temp_path))
            >>> len(matches)
            2
            >>> matches[0].line_number
            1
            >>> matches[0].supporting_text
            'hello'
            >>> matches[1].line_number
            3
            >>> matches[1].supporting_text
            'world'
            >>> import os
            >>> os.unlink(temp_path)
        """
        all_matches = []
        with open(file_path, "r", encoding="utf-8") as f:
            for line_number, line in enumerate(f, start=1):
                matches = self.extract_from_text(line, line_number)
                all_matches.extend(matches)
        return all_matches
