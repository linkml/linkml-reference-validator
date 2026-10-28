"""Symbols that carry meaning survive normalization (issue #125).

Normalization used to replace all punctuation with spaces, including the
comparison operators, the plus-minus sign and the minus sign of a number,
so a quote that reversed a comparison or the sign of a value still passed.
These tests pin those cases, and the matches that must keep working.
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
        ("difference was significant (p < 0.05)", "the difference was significant (p > 0.05)"),
        ("significant (p > 0.05)", "the difference was significant (p < 0.05)"),
        ("p ≤ 0.01", "with p ≥ 0.01 throughout"),
        ("p <= 0.01", "with p >= 0.01 throughout"),
        ("levels decreased by -2.5 fold", "levels decreased by 2.5 fold"),
        ("levels decreased by 2.5 fold", "levels decreased by -2.5 fold"),
        ("stored at 80 °C", "samples were stored at −80 °C"),
        ("2.5 fold change", "a -2.5 fold change"),
        ("a mean of 5 2 mM", "a mean of 5 ± 2 mM"),
    ],
)
def test_reversed_comparison_or_sign_fails(quote, content):
    """A quote that changes a comparison, a sign, or drops a ± is not found."""
    assert not found(quote, content)


@pytest.mark.parametrize(
    "quote,content",
    [
        ("significant (p < 0.05)", "the difference was significant (p<0.05) overall"),
        ("p ≤ 0.01", "with p ≤ 0.01 throughout"),
        ("p <= 0.01", "with p ≤ 0.01 throughout"),
        ("p >= 0.01", "with p ≥ 0.01 throughout"),
        ("decreased by -2.5 fold", "levels decreased by −2.5 fold"),
        ("stored at −80 °C", "samples were stored at -80 °C"),
        ("a mean of 5 ± 2 mM", "a mean of 5 +/- 2 mM"),
        ("5 ± 2 mM", "a mean of 5±2 mM"),
        ("a mean of 5 ± 2 mM", "a mean of 5 +/− 2 mM"),
        ("a mean of 5 ± 2 mM", "a mean of 5 +− 2 mM"),
        ("mean ± SD", "values are mean +/-SD of three runs"),
        ("mean ± SEM", "values are mean ±SEM of three runs"),
        ("a change of -2.5", "a change of (−2.5) overall"),
        ("x = -5", "solved for x=-5 here"),
    ],
)
def test_same_meaning_in_other_spellings_matches(quote, content):
    """ASCII and Unicode spellings of the same symbol are equivalent."""
    assert found(quote, content)


@pytest.mark.parametrize(
    "quote,content",
    [
        ("IL-6 levels", "serum IL-6 levels rose"),
        ("IL 6 levels", "serum IL-6 levels rose"),
        ("COVID 19 patients", "COVID-19 patients were enrolled"),
        ("days 3 5", "on days 3-5 after infection"),
        ("pH 7.4-8.0", "a pH 7.4-8.0 buffer"),
        ("3'-5' exonuclease", "a 3′–5′ exonuclease activity"),
        ("Ca2+ dependent", "a Ca2+-dependent kinase"),
        ("reduced by 10-20%", "reduced by 10%-20% overall"),
        ("tilted 5-10°", "tilted 5°-10° at rest"),
        ("A B transition", "the A → B transition"),
        ("A B transition", "the A -> B transition"),
    ],
)
def test_hyphens_and_arrows_are_not_signs_or_comparisons(quote, content):
    """A hyphen after a word or digit, and an arrow, still normalize to a space."""
    assert found(quote, content)


def test_normalize_text_spells_out_meaning_symbols():
    """The tokens are ordinary words, so whole-word matching handles them."""
    normalize = SupportingTextValidator.normalize_text
    assert normalize("p<0.05") == "p lt 0.05"
    assert normalize("p ≥ 0.01") == normalize("p >= 0.01") == "p ge 0.01"
    assert normalize("5 ± 2") == normalize("5 +/- 2") == normalize("5 +- 2") == "5 pm 2"
    assert normalize("by −2.5 fold") == normalize("by -2.5 fold") == "by neg2.5 fold"
    assert normalize("IL-6 and COVID-19") == "il 6 and covid 19"
    assert normalize("10%-20%") == normalize("10-20%") == "10 20"
    assert normalize("x=-5, [-3]") == "x neg5 neg3"


def test_plus_minus_repair_still_needs_the_symbol_as_written():
    """``+-`` -> ``±`` is still confirmed literally, so ``Ca2+-`` is left alone."""
    repairer = SupportingTextRepairer(ReferenceValidationConfig())
    reference = ReferenceContent(
        reference_id="PMID:1",
        content="Ca2+-dependent CO₂ fixation was measured in HEK293 cells.",
    )
    result = repairer.attempt_repair("Ca2+-dependent CO2 fixation", "PMID:1", reference)
    assert result.is_repaired
    assert result.repaired_text == "Ca2+-dependent CO₂ fixation"


def test_titles_compare_meaning_symbols_too():
    """Title validation compares normalize_text output, so a reversed comparison differs."""
    normalize = SupportingTextValidator.normalize_text
    assert normalize("Survival with dose < 5 mg") == normalize("Survival with dose <5 mg")
    assert normalize("Survival with dose < 5 mg") != normalize("Survival with dose > 5 mg")
