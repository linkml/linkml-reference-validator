"""Public splitting contract and compatibility with validator configuration."""

import re
import subprocess
import sys

import pytest

from linkml_reference_validator.matching import split_supporting_text
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator


@pytest.mark.parametrize(
    "text,patterns,expected",
    [
        ("protein functions in cells", [], ["protein functions in cells"]),
        ("protein [important] functions", [], ["protein functions"]),
        (" ... alpha .. beta .... ", [], ["alpha", "beta"]),
        ("a. b … c", [], ["a. b … c"]),
        (" \talpha\n beta  ", [], ["alpha beta"]),
        ("", [], []),
        (" \n ", [], []),
        ("[editorial] ... [note]", [], []),
        ("[2Fe-2S] [poly(A)+]", [], []),
        ("binds [2Fe-2S] [important]", [r"\d"], ["binds [2Fe-2S]"]),
        ("[2Fe-2S] [poly(A)+] [important]", [r"[()+]"], ["[poly(A)+]"]),
        ("[2Fe-2S] [poly(A)+] [important]", [r"\d", r"[()+]"], ["[2Fe-2S] [poly(A)+]"]),
        ("[A] [AB]", [r"^A$"], ["[A]"]),
        ("[keep] [anything]", [""], ["[keep] [anything]"]),
        ("alpha [unclosed", [], ["alpha [unclosed"]),
        ("[multi\nline]", [], ["[multi line]"]),
        ("a [outer [inner] end] b", [], ["a end] b"]),
        ("[a...b]", ["a"], ["[a", "b]"]),
    ],
)
def test_public_split_matches_existing_behavior(tmp_path, text, patterns, expected):
    """Pin concrete results as well as parity with the legacy entry point."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", literal_bracket_patterns=patterns
    )
    validator = SupportingTextValidator(config)
    assert split_supporting_text(text, patterns) == expected
    assert split_supporting_text(text, config.literal_bracket_patterns) == validator._split_query(text)


def test_default_patterns():
    """Omitted patterns strip scientific brackets just like an empty config."""
    assert split_supporting_text("a [2Fe-2S] ... b [note]") == ["a", "b"]


def test_precompiled_patterns():
    """Callers can reuse compiled regexes, including their flags."""
    patterns = (re.compile(r"^poly", re.IGNORECASE),)
    assert split_supporting_text("[POLY(A)+] [note]", patterns) == ["[POLY(A)+]"]


def test_invalid_pattern():
    """Invalid regexes fail even when the text contains no brackets."""
    with pytest.raises(re.error):
        split_supporting_text("plain text", ["["])


def test_import_without_fetching_dependencies():
    """A fresh interpreter can import the helper without loading the validator."""
    subprocess.run(
        [sys.executable, "-c", (
            "from linkml_reference_validator.matching import split_supporting_text; "
            "import sys; "
            "assert split_supporting_text('a ... b') == ['a', 'b']; "
            "assert 'linkml_reference_validator.etl.reference_fetcher' not in sys.modules; "
            "assert 'linkml_reference_validator.models' not in sys.modules"
        )],
        check=True,
    )
