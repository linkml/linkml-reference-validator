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
