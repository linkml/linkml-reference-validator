"""Pin compatibility-ligature matching without broad scientific equivalence."""

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator


@pytest.mark.parametrize(
    "ligature,expanded",
    [("ﬀ", "ff"), ("ﬁ", "fi"), ("ﬂ", "fl"), ("ﬃ", "ffi"), ("ﬄ", "ffl"),
     ("ﬅ", "st"), ("ﬆ", "st"), ("Ĳ", "ij"), ("ĳ", "ij")],
)
def test_compatibility_ligatures(ligature: str, expanded: str) -> None:
    """Every explicitly supported compatibility ligature expands within words."""
    normalize = SupportingTextValidator.normalize_text
    assert normalize(f"A{ligature}Z") == f"a{expanded}z"
    assert normalize(normalize(f"A{ligature}Z")) == f"a{expanded}z"


@pytest.mark.parametrize("ligature_side", ["content", "query", "both"])
@pytest.mark.parametrize("split", [False, True])
def test_real_excerpt_with_ligatures(tmp_path: Path, ligature_side: str, split: bool) -> None:
    """Validate a real PLOS excerpt with simulated PDF typography on either side.

    The source fixture and its provenance are in fixtures/fulltext_html/README.md;
    only fi typography is changed, without mocking extraction or matching.
    """
    source = Path(__file__).parent / "fixtures/fulltext_html/plos-0000308.html"
    content = BeautifulSoup(source.read_text(), "html.parser").get_text(" ")
    query = (
        "To confirm that these findings ... [editorial note] "
        "we repeated our analysis on a subset of the cohort"
        if split else
        "To confirm that these findings were not dependent on a few extremely high-profile papers"
    )
    if ligature_side in {"content", "both"}:
        content = content.replace("fi", "ﬁ")
    if ligature_side in {"query", "both"}:
        query = query.replace("fi", "ﬁ")
    validator = SupportingTextValidator(ReferenceValidationConfig(cache_dir=tmp_path))
    reference = ReferenceContent(reference_id="doi:10.1371/journal.pone.0000308", content=content)
    match = validator.find_text_in_reference(query, reference)
    assert match.found
    assert match.similarity_score == 1.0
    # Folding must not turn fuzzy suggestions or missing split parts into evidence.
    assert not validator.find_text_in_reference(query + " ... nonexistent conclusion", reference).found


@pytest.mark.parametrize(
    "original,distinct",
    [("æ", "ae"), ("Æ", "AE"), ("œ", "oe"), ("Œ", "OE"),
     ("10⁶", "106"), ("H₂O", "H2O"), ("①", "1"), ("µ", "μ"), ("α", "β")],
)
@pytest.mark.parametrize("reverse", [False, True])
def test_distinct_letters_and_scientific_symbols(
    tmp_path: Path, original: str, distinct: str, reverse: bool,
) -> None:
    """Ligature repair must not introduce NFKC or AE/OE gate equivalences."""
    if reverse:
        original, distinct = distinct, original
    validator = SupportingTextValidator(ReferenceValidationConfig(cache_dir=tmp_path))
    assert validator.normalize_text(original) != validator.normalize_text(distinct)
    reference = ReferenceContent(reference_id="TEST:distinctions", content=f"Measured {original} marker")
    assert not validator.find_text_in_reference(f"Measured {distinct} marker", reference).found


def test_ligatures_with_existing_normalization() -> None:
    """Folding composes with Greek spelling, case, punctuation, and whitespace."""
    assert SupportingTextValidator.normalize_text("  α-ﬁbrils,  Æ/Œ! ") == "alpha fibrils æ œ"


@pytest.mark.parametrize("reverse", [False, True])
def test_cached_title_ligatures(tmp_path: Path, reverse: bool) -> None:
    """Both title validation entry points fold ligatures but still require exact titles."""
    title, expected = "Ĳ and amyloid ﬁbrils", "IJ and amyloid fibrils"
    if reverse:
        title, expected = expected, title
    validator = SupportingTextValidator(ReferenceValidationConfig(cache_dir=tmp_path))
    reference = ReferenceContent(
        reference_id="PMID:123", title=title, content="The study describes amyloid fibrils."
    )
    validator.fetcher._save_to_disk(reference)
    assert validator.validate_title(reference.reference_id, expected).is_valid
    assert validator.validate(
        "amyloid fibrils", reference.reference_id, expected_title=expected,
    ).is_valid
    assert not validator.validate_title(reference.reference_id, "amyloid fibrils").is_valid
