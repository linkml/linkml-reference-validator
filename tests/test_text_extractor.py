"""Tests for text extraction and OBO format validation."""

import tempfile
from pathlib import Path

from linkml_reference_validator.etl.text_extractor import (
    ExtractedTextMatch,
    TextExtractor,
)


class TestTextExtractor:
    """Test the TextExtractor class."""

    def test_basic_extraction(self):
        """Test basic regex extraction from text."""
        extractor = TextExtractor(
            regex_pattern=r'text="([^"]+)" ref=(\S+)',
            text_group=1,
            ref_group=2,
        )

        line = 'Some content with text="hello world" ref=PMID:123 here'
        matches = extractor.extract_from_text(line, line_number=1)

        assert len(matches) == 1
        assert matches[0].supporting_text == "hello world"
        assert matches[0].reference_id == "PMID:123"
        assert matches[0].line_number == 1
        assert matches[0].original_line == line

    def test_obo_format_extraction(self):
        """Test extraction of OBO format axiom annotations."""
        extractor = TextExtractor(
            regex_pattern=r'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"',
            text_group=1,
            ref_group=2,
        )

        line = 'def: "..." [PMID:11601609] {ex:supporting_text="cellulosome contains enzymes[PMID:11601609]"}'
        matches = extractor.extract_from_text(line, line_number=10)

        assert len(matches) == 1
        assert matches[0].supporting_text == "cellulosome contains enzymes"
        assert matches[0].reference_id == "PMID:11601609"
        assert matches[0].line_number == 10

    def test_no_matches(self):
        """Test that non-matching lines return empty list."""
        extractor = TextExtractor(
            regex_pattern=r'text="([^"]+)" ref=(\S+)',
            text_group=1,
            ref_group=2,
        )

        line = 'This line has no matches'
        matches = extractor.extract_from_text(line, line_number=1)

        assert len(matches) == 0

    def test_multiple_matches_per_line(self):
        """Test extraction of multiple matches from one line."""
        extractor = TextExtractor(
            regex_pattern=r'text="([^"]+)" ref=(\S+)',
            text_group=1,
            ref_group=2,
        )

        line = 'First text="alpha" ref=PMID:1 and second text="beta" ref=PMID:2'
        matches = extractor.extract_from_text(line, line_number=5)

        assert len(matches) == 2
        assert matches[0].supporting_text == "alpha"
        assert matches[0].reference_id == "PMID:1"
        assert matches[1].supporting_text == "beta"
        assert matches[1].reference_id == "PMID:2"
        assert all(m.line_number == 5 for m in matches)

    def test_extract_from_file(self):
        """Test extraction from a multi-line file."""
        extractor = TextExtractor(
            regex_pattern=r'text="([^"]+)" ref=(\S+)',
            text_group=1,
            ref_group=2,
        )

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write('line 1: text="hello" ref=PMID:1\n')
            f.write('line 2: no match here\n')
            f.write('line 3: text="world" ref=PMID:2\n')
            f.write('line 4: also no match\n')
            f.write('line 5: text="foo" ref=PMID:3\n')
            temp_path = Path(f.name)

        try:
            matches = extractor.extract_from_file(temp_path)

            assert len(matches) == 3
            assert matches[0].line_number == 1
            assert matches[0].supporting_text == "hello"
            assert matches[1].line_number == 3
            assert matches[1].supporting_text == "world"
            assert matches[2].line_number == 5
            assert matches[2].supporting_text == "foo"
        finally:
            temp_path.unlink()

    def test_obo_file_extraction(self):
        """Test extraction from actual OBO fixture file."""
        extractor = TextExtractor(
            regex_pattern=r'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"',
            text_group=1,
            ref_group=2,
        )

        obo_file = Path(__file__).parent / "fixtures" / "sample.obo"
        assert obo_file.exists(), f"OBO fixture not found: {obo_file}"

        matches = extractor.extract_from_file(obo_file)

        # Should find 2 matches in the sample OBO file
        # (one for GO:0043263 and one for GO:0000002)
        assert len(matches) == 2

        # Check first match (cellulosome)
        assert matches[0].reference_id == "PMID:11601609"
        assert "cellulosome" in matches[0].supporting_text.lower()
        assert "enzymes" in matches[0].supporting_text.lower()

        # Check second match
        assert matches[1].reference_id == "PMID:23456789"
        assert "supporting evidence" in matches[1].supporting_text.lower()

    def test_different_group_numbers(self):
        """Test using different capture group numbers."""
        # Swap the groups - ref comes first, text comes second
        extractor = TextExtractor(
            regex_pattern=r'ref=(\S+) text="([^"]+)"',
            text_group=2,  # Text is now group 2
            ref_group=1,   # Ref is now group 1
        )

        line = 'Something with ref=PMID:999 text="test content" here'
        matches = extractor.extract_from_text(line, line_number=1)

        assert len(matches) == 1
        assert matches[0].supporting_text == "test content"
        assert matches[0].reference_id == "PMID:999"


class TestExtractedTextMatch:
    """Test the ExtractedTextMatch dataclass."""

    def test_match_creation(self):
        """Test creating an ExtractedTextMatch."""
        match = ExtractedTextMatch(
            line_number=42,
            supporting_text="some text",
            reference_id="PMID:12345",
            original_line="the full line of text",
        )

        assert match.line_number == 42
        assert match.supporting_text == "some text"
        assert match.reference_id == "PMID:12345"
        assert match.original_line == "the full line of text"

    def test_match_equality(self):
        """Test that matches with same values are equal."""
        match1 = ExtractedTextMatch(
            line_number=1,
            supporting_text="text",
            reference_id="PMID:1",
            original_line="line",
        )
        match2 = ExtractedTextMatch(
            line_number=1,
            supporting_text="text",
            reference_id="PMID:1",
            original_line="line",
        )

        assert match1 == match2
