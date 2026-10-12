"""Fuzzy repair must not offer a correction that changes what a quote claims (issue #108).

A typo fix is close in spelling to the quote; so are some words of the
opposite meaning. These tests hold each such case to "not repaired, and not
suggested", end to end, and pin the typo fixes that must still work.
"""

import pytest

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.fuzzy_text_utils import (
    adds_negation,
    keeps_every_word,
)
from linkml_reference_validator.validation.repairer import SupportingTextRepairer
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator


def offered(quote: str, content: str) -> bool:
    """Whether ``quote`` is repaired against, or suggested from, ``content``."""
    reference = ReferenceContent(reference_id="PMID:1", content=content)
    config = ReferenceValidationConfig()
    repaired = SupportingTextRepairer(config).attempt_repair(quote, "PMID:1", reference).is_repaired
    match = SupportingTextValidator(config).find_text_in_reference(quote, reference)
    return repaired or "try:" in (match.suggested_fix or "")


CLAIM = "AKT was {} after rapamycin treatment in tumour cells"


# ------------------------------------------------- 1. opposite prefixes swapped


@pytest.mark.parametrize(
    "said,quoted",
    [
        ("hypophosphorylated", "hyperphosphorylated"),
        ("downregulated", "upregulated"),
        ("underexpressed", "overexpressed"),
        ("extracellular", "intracellular"),
        ("intercellular", "intracellular"),
        ("postsynaptic", "presynaptic"),
        ("heterozygous", "homozygous"),
        ("decreased", "increased"),
        ("antiapoptotic", "proapoptotic"),
        ("antagonised", "agonised"),
    ],
)
def test_a_word_with_the_opposite_prefix_is_not_a_typo(said, quoted):
    assert not offered(CLAIM.format(quoted), CLAIM.format(said).capitalize() + ".")


# ------------------------------------------ 2. a prefix dropped with a typo


@pytest.mark.parametrize(
    "said,quoted",
    [
        ("affected", "unaffectd"),
        ("active", "inactve"),
        ("phosphorylated", "dephosphorylatd"),
        ("regulated", "dysregulatd"),
        ("hyperphosphorylated", "hypophosphorylatd"),
    ],
)
def test_a_dropped_or_swapped_prefix_is_not_a_typo_even_with_a_typo(said, quoted):
    assert not offered(CLAIM.format(quoted), CLAIM.format(said).capitalize() + ".")


# ------------------------------------------- 3. a repair that adds a negation


@pytest.mark.parametrize(
    "said",
    [
        "PTEN did not activate AKT after rapamycin treatment in tumour cells",
        "PTEN didn't activate AKT after rapamycin treatment in tumour cells",
        "PTEN never activated AKT after rapamycin treatment in tumour cells",
        "PTEN failed to activate AKT after rapamycin treatment in tumour cells",
    ],
    ids=["not", "contraction", "never", "failed"],
)
def test_a_correction_that_adds_a_negation_is_not_offered(said):
    assert not offered("PTEN activated AKT after rapamycin treatment in tumour cells", said + ".")


@pytest.mark.parametrize(
    "query,match,expected",
    [
        ("PTEN activates AKT", "PTEN does not activate AKT", True),
        ("PTEN activates AKT", "PTEN doesn't activate AKT", True),
        ("PTEN activates AKT", "PTEN cannot activate AKT", True),
        ("AKT was not detected", "AKT was not detectd", False),  # the quote has it already
        ("AKT was not detected, not even once", "AKT was not detected", False),  # dropped, not added
        ("no AKT", "no AKT, and no mTOR", True),  # a second one is added
        ("PTEN activates AKT", "PTEN activates AKT signalling", False),
    ],
)
def test_adds_negation(query, match, expected):
    assert adds_negation(query, match) is expected


# ----------------------------------------------- typo fixes that must still work


@pytest.mark.parametrize(
    "said,quoted",
    [
        ("unaffected", "unaffectd"),  # the prefix is kept: a typo after it
        ("hyperphosphorylated", "hyperphosphorylatd"),
        ("intracellular", "intracelular"),
        ("signalling", "signaling"),
        ("tumour", "tumor"),
        ("decreased", "decresed"),
    ],
)
def test_a_typo_that_keeps_the_prefix_is_still_repaired(said, quoted):
    assert offered(CLAIM.format(quoted), CLAIM.format(said).capitalize() + ".")


def test_near_spellings_still_count_as_kept():
    assert keeps_every_word("hyperphosphorylatd AKT in tumor cells", "hyperphosphorylated AKT in tumour cells")
