"""Tests for identifier crosswalk."""

from linkml_reference_validator.models import ReferenceContent
from linkml_reference_validator.etl.identifiers import build_identifiers


def test_build_from_doi_reference():
    content = ReferenceContent(reference_id="DOI:10.1038/x", doi="10.1038/x")
    ids = build_identifiers(content)
    assert ids.doi == "10.1038/x"
    assert ids.pmid is None


def test_build_from_pmid_reference_with_doi_metadata():
    content = ReferenceContent(reference_id="PMID:123", doi="10.1/y")
    ids = build_identifiers(content)
    assert ids.pmid == "123"
    assert ids.doi == "10.1/y"


def test_build_from_pmid_reference_without_doi():
    content = ReferenceContent(reference_id="PMID:123")
    ids = build_identifiers(content)
    assert ids.pmid == "123"
    assert ids.doi is None


def test_build_from_url_reference():
    content = ReferenceContent(reference_id="url:https://x/y.pdf")
    ids = build_identifiers(content)
    assert ids.url == "https://x/y.pdf"


def test_build_from_ppr_reference():
    content = ReferenceContent(reference_id="PPR:PPR123456")
    ids = build_identifiers(content)
    assert ids.pprid == "PPR123456"


def test_build_from_ppr_reference_carries_doi_metadata():
    content = ReferenceContent(reference_id="PPR:PPR123456", doi="10.1101/2024.01.01.573333")
    ids = build_identifiers(content)
    assert ids.pprid == "PPR123456"
    assert ids.doi == "10.1101/2024.01.01.573333"


def test_build_carries_is_preprint_flag():
    assert build_identifiers(
        ReferenceContent(reference_id="DOI:10.1/x", is_preprint=True)
    ).is_preprint is True
    assert build_identifiers(
        ReferenceContent(reference_id="DOI:10.1/x", is_preprint=False)
    ).is_preprint is False
    assert build_identifiers(
        ReferenceContent(reference_id="PMID:123")
    ).is_preprint is None
