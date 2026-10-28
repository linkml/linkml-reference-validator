"""A quote must match whole words, not begin or end inside one (issue #124).

Normalized parts used to be tested as bare substrings of the normalized
reference, so "activates" matched inside "inactivates" and a quote stating
the opposite of the reference passed. These tests pin the failing cases and
the matches that must keep working.
"""

import pytest

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.repairer import SupportingTextRepairer
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator


def found(quote: str, content: str) -> bool:
    """Whether ``quote`` validates against ``content``."""
    validator = SupportingTextValidator(ReferenceValidationConfig())
    reference = ReferenceContent(reference_id="PMID:1", content=content)
    return validator.find_text_in_reference(quote, reference).found


@pytest.mark.parametrize(
    "quote,content",
    [
        ("activates AKT signaling", "Loss of PTEN inactivates AKT signaling in mice."),
        ("toxic to hepatocytes", "the compound was nontoxic to hepatocytes"),
        ("5 mM H2O2 induced apoptosis", "10.5 mM H2O2 induced apoptosis"),
        ("stable in vivo", "the variant was unstable in vivo"),
        ("regulated in tumors", "PTEN was downregulated in tumors"),
        ("PTEN is not", "PTEN is nothing like AKT"),
        ("the protein binds DNA", "the protein binds DNAse"),
    ],
)
def test_quote_starting_or_ending_mid_word_fails(quote, content):
    """A quote that begins or ends inside a word of the reference is not found."""
    assert not found(quote, content)


@pytest.mark.parametrize(
    "quote,content",
    [
        ("activates AKT signaling", "Loss of PTEN activates AKT signaling in mice."),
        ("PTEN", "PTEN"),
        ("protein functions", "The protein functions in cells."),
        ("binds DNA", "it binds DNA."),
        ("T cell receptor", "the T-cell receptor was"),
        ("alpha catenin", "α-catenin binds"),
        ("10.5 mM H2O2", "with 10.5 mM H2O2 induced"),
        ("loss of PTEN ... AKT signaling", "Loss of PTEN activates AKT signaling."),
    ],
)
def test_whole_word_quotes_still_match(quote, content):
    """Quotes that start and end on word boundaries, at any position, still match."""
    assert found(quote, content)


def test_each_ellipsis_part_is_held_to_word_boundaries():
    """The boundary rule applies to every part of a split quote, not just the whole."""
    assert not found("Loss of PTEN ... activates AKT", "Loss of PTEN inactivates AKT signaling.")


def test_figure_labels_are_matched_on_word_boundaries():
    """Each searchable text (an SVG figure label) is held to word boundaries too."""
    validator = SupportingTextValidator(ReferenceValidationConfig())
    match = validator._substring_match(
        ["activates AKT"], "", searchable=["PTEN inactivates AKT", "mTOR"]
    )
    assert not match.found


def test_repair_does_not_confirm_a_mid_word_match():
    """Character normalization is not offered as a fix when it only matches mid-word."""
    reference = ReferenceContent(
        reference_id="PMID:1", content="Treatment with nonCO₂ gas activates AKT."
    )
    result = SupportingTextRepairer(ReferenceValidationConfig()).attempt_repair(
        "CO2 gas activates AKT", "PMID:1", reference
    )
    assert not result.is_repaired


@pytest.mark.parametrize(
    "quote,content",
    [
        ("PTEN is a tumor suppressor", "PTEN is a tumor suppressor12 in mice."),
        ("PTEN is a tumor suppressor", "PTEN is a tumor suppressor1,2."),
        ("PTEN is a tumor suppressor", "PTEN is a tumor suppressor1-3 in mice."),
    ],
)
def test_citation_digits_welded_to_the_last_word_still_match(quote, content):
    """Extraction welds superscript citations onto a word; a quote ending there still matches.

    JATS ``suppressor<sup><xref>12</xref></sup>``, PMC HTML and PDF text all
    render the citation as ``suppressor12``, so a quote of the sentence must
    not fail on its last word.
    """
    assert found(quote, content)


def test_citation_allowance_does_not_extend_a_number():
    """Trailing digits are allowed only after a letter: ``10`` must not grow into ``105``."""
    assert not found("a dose of 10", "a dose of 105 mg")


def test_digit_separators_are_part_of_the_number():
    """A point or comma between digits is kept, so differently punctuated numbers differ."""
    assert not found("on days 3, 5 and 7", "on days 3,5 and 7")
    assert found("on days 3,5 and 7", "measured on days 3,5 and 7")
    assert found("p < 0.05", "significant (p<0.05)")


def test_unmapped_glyph_still_splits_the_word():
    """U+FFFD splits a damaged word, so a quote of its second half still matches."""
    assert found("ammation of the gut", "in�ammation of the gut")


def test_mid_word_miss_says_why_and_suggests_nothing_that_fails_again():
    """A quote found only inside longer words gets a clear error, not itself as a fix."""
    validator = SupportingTextValidator(ReferenceValidationConfig())
    quote = "activates AKT signaling"
    match = validator.find_text_in_reference(
        quote, ReferenceContent(reference_id="PMID:1", content="Loss of PTEN inactivates AKT signaling.")
    )
    assert not match.found
    assert "whole words" in (match.error_message or "")
    assert f'"{quote}"' not in (match.suggested_fix or "")


@pytest.mark.parametrize("quote", ["activates AKT signaling", "activates AKT signaling in mice"])
def test_repair_never_returns_the_failing_quote_as_its_fix(quote):
    """Fuzzy repair must not 'fix' a mid-word miss by returning the same quote."""
    reference = ReferenceContent(
        reference_id="PMID:1",
        content="Loss of PTEN inactivates AKT signaling in mice. Other text about things.",
    )
    result = SupportingTextRepairer(ReferenceValidationConfig()).attempt_repair(
        quote, "PMID:1", reference
    )
    assert not (result.is_repaired and result.repaired_text == quote)


def test_fuzzy_exact_stage_requires_whole_words():
    """The fuzzy matcher's exact shortcut does not accept a mid-word hit."""
    from linkml_reference_validator.validation.fuzzy_text_utils import find_fuzzy_match_in_text

    found_, score, _ = find_fuzzy_match_in_text("activates AKT", "PTEN inactivates AKT.")
    assert score < 100
    assert find_fuzzy_match_in_text("activates AKT", "PTEN activates AKT.") == (
        True, 100.0, "activates AKT"
    )
