"""The micro sign and variant Greek letters normalize like the ordinary letters (issue #126).

PDFs, publishers and curators use the micro sign ``µ`` (U+00B5) and Greek
``μ`` (U+03BC) interchangeably, and the variant forms ``ϕ ϵ ϑ ϐ ϖ`` for the
ordinary letters, so a correct quote must match either spelling.
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
        ("an IC50 of 5 µM", "an IC50 of 5 μM was observed"),
        ("an IC50 of 5 μM", "an IC50 of 5 µM was observed"),
    ],
)
def test_micro_sign_and_greek_mu_are_equivalent(quote, content):
    """``5 µM`` and ``5 μM`` match each other in both directions."""
    assert found(quote, content)


@pytest.mark.parametrize(
    "variant,ordinary",
    [
        ("µ", "μ"),  # micro sign, mu
        ("ϕ", "φ"),  # phi symbol, phi
        ("ϵ", "ε"),  # lunate epsilon, epsilon
        ("ϑ", "θ"),  # theta symbol, theta
        ("ϐ", "β"),  # beta symbol, beta
        ("ϖ", "π"),  # pi symbol, pi
        ("ϰ", "κ"),  # kappa symbol, kappa
        ("ϱ", "ρ"),  # rho symbol, rho
    ],
)
def test_variant_forms_normalize_like_the_ordinary_letter(variant, ordinary):
    """Each variant form is spelled out as the letter it stands for."""
    normalize = SupportingTextValidator.normalize_text
    assert normalize(f"{variant}-value") == normalize(f"{ordinary}-value")


def test_greek_mu_still_differs_from_the_latin_letter_u():
    """Folding stops at the Greek letters; a Latin ``u`` is not ``mu``."""
    assert not found("5 uM", "an IC50 of 5 µM was observed")
