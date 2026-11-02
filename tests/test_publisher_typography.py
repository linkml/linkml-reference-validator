"""Publisher typography that means the same as its ASCII spelling.

The meaning-bearing symbol rules (issue #125) and the decimal-separator rule
made normalization keep ``<``, ``>``, ``±``, a number's minus sign and the
point inside ``10.5``. Each rule listed the spellings it recognised, and a
spelling left off the list was still stripped as punctuation, so a quote typed
in ASCII stopped matching a source that prints the same thing another way.
Every case below is from a real cached reference that a downstream knowledge
base had quoted correctly:

- the Lancet journals write decimals with a middle dot (``57·4``);
- MEDLINE abstracts transliterate ``≥`` and ``≤`` as ``>/=`` and ``</=``;
- typesetters print a minus sign as an en dash (``z score, –1.98``), as a
  Unicode hyphen (``<‐2.5``), or as ``−`` set off by a thin space
  (``from − 2.92``);
- ``+/–`` with an en dash is ± as much as ``+/-`` is.
"""

import pytest

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator


def found(quote: str, content: str) -> bool:
    """Whether ``quote`` validates against ``content``."""
    validator = SupportingTextValidator(ReferenceValidationConfig())
    reference = ReferenceContent(reference_id="PMID:1", content=content)
    return validator.find_text_in_reference(quote, reference).found


@pytest.mark.parametrize(
    "quote,content",
    [
        # Middle-dot decimals (Lancet house style)
        ("would increase from 57.4 (95% uncertainty interval 50.4-65.1)",
         "dementia would increase from 57·4 (95% uncertainty interval 50·4–65·1) million"),
        ("at diagnosis (p=0.011)", "at diagnosis (p=0·011) and IgG4"),
        ("from 57·4 (95%", "would increase from 57.4 (95% uncertainty"),
        # MEDLINE ASCII transliterations of ≥ and ≤
        ("shed V. cholerae for >/= 4 days", "contacts shed V. cholerae for ≥ 4 days."),
        ("severe (</=30x109/L platelets)", "or severe (≤30x109/L platelets)."),
        ("shed V. cholerae for ≥ 4 days", "contacts shed V. cholerae for >/= 4 days."),
        # A minus sign printed as an en dash, a Unicode hyphen, or a spaced −
        ("a height of 123.8 cm (z score, -1.98)", "a height of 123.8 cm (z score, –1.98), a weight"),
        ("microcephaly measured as -4 to -6 SD", "microcephaly measured as –4 to −6 SD (3/3)"),
        ("(head circumference < -2.5 SD)", "microcephaly (head circumference < ‐2.5 SD), and"),
        ("height SDS from -2.92 to -1.97", "an increase in height SDS from − 2.92 to − 1.97 (median)"),
        ("at positions -48 and -60", "substitutions (at positions –48 and –60 relative"),
        # ± printed with an en dash
        ("in the brains of Wdr26+/- mice", "observed in the brains of Wdr26+/– mice (Figure 5"),
        ("a mean of 5 ± 2 mM", "a mean of 5 +/– 2 mM"),
    ],
)
def test_typographic_variants_match_their_ascii_spelling(quote, content):
    """The same number, comparison or sign in another typography matches."""
    assert found(quote, content)


@pytest.mark.parametrize(
    "quote,content",
    [
        # A middle dot between digits is still a decimal point: 5 is not 10·5
        ("5 mM H2O2", "treated with 10·5 mM H2O2"),
        # >/= is ≥, so it is not > alone, and not ≤
        ("for >/= 4 days", "shed for > 4 days"),
        ("for >/= 4 days", "shed for ≤ 4 days"),
        # An en-dash minus is still a sign
        ("(z score, 1.98)", "a height of 123.8 cm (z score, –1.98)"),
        ("from 2.92 to 1.97", "height SDS from − 2.92 to − 1.97"),
        # ± with an en dash is not dropped
        ("a mean of 5 2 mM", "a mean of 5 +/– 2 mM"),
    ],
)
def test_typographic_variants_keep_their_meaning(quote, content):
    """Recognising a spelling does not let a changed value through."""
    assert not found(quote, content)


@pytest.mark.parametrize(
    "quote,content",
    [
        # An en dash after a digit or word is a range or a compound, as before
        ("aged 1 12 years", "children aged 1–12 years"),
        ("IL 6 levels", "raised IL‐6 levels"),
        ("CI 67.7 83.5", "(95% CI 67·7–83·5)"),
        # A spaced en dash between numbers is a range, not a minus sign
        ("scores of 10 20", "scores of 10 – 20"),
        # "−" after a number is a subtraction, not the sign of the next one
        ("gives 10 - 2 = 8", "which gives 10 − 2 = 8 in all"),
        ("gives 10 - 2 = 8", "which gives 10  − 2 = 8 in all"),
        ("gives 10 - 2 = 8", "which gives 10\n − 2 = 8 in all"),
        # A middle dot in a formula is not a decimal point
        ("with MgCl2 6H2O added", "buffer with MgCl2·6H2O added"),
    ],
)
def test_range_dashes_are_still_punctuation(quote, content):
    """Dashes that are not minus signs still read as punctuation."""
    assert found(quote, content)


def test_unevenly_spaced_en_dash_before_a_digit_is_a_sign():
    """A known limitation, shared with ASCII "-": "18 –65" reads as 18 and -65.

    A dash after a space and before a digit is in sign position, so a range
    printed with a space on one side only is read as a negative number.
    """
    assert SupportingTextValidator.normalize_text("ages 18 –65") == "ages 18 neg65"
    assert SupportingTextValidator.normalize_text("ages 18 -65") == "ages 18 neg65"


def test_each_minus_spelling_is_a_sign_and_nothing_else_is():
    """Every listed spelling is a minus; a character between two is not.

    Guards the character class built from MINUS_SIGN_SPELLINGS: unescaped, a
    "-" anywhere but first would make a range and admit other characters.
    """
    from linkml_reference_validator.validation.supporting_text_validator import (
        MINUS_SIGN_SPELLINGS,
    )

    n = SupportingTextValidator.normalize_text
    for spelling in MINUS_SIGN_SPELLINGS:
        assert n(f"by {spelling}2.5 fold") == "by neg2.5 fold", repr(spelling)
    assert n("by .2.5 fold") == "by 2.5 fold"


def test_normalize_text_spellings():
    """The variants normalize to the same words as their ASCII forms."""
    n = SupportingTextValidator.normalize_text
    assert n("57·4") == n("57.4") == "57.4"
    assert n(">/= 4") == n("≥ 4") == "ge 4"
    assert n("</= 4") == n("≤ 4") == "le 4"
    assert n("(z score, –1.98)") == n("(z score, -1.98)")
    assert n("from − 2.92") == n("from -2.92") == "from neg2.92"
    assert n("< ‐2.5") == n("< -2.5") == "lt neg2.5"
    assert n("(z score, \u20121.98)") == n("(z score, -1.98)")
    assert n("Wdr26+/– mice") == n("Wdr26+/- mice") == "wdr26 pm mice"
