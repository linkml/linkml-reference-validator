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
