"""A slot URI must name a reference or excerpt, not merely mention one (#142, #130).

Field detection matched the word "reference" anywhere in a slot URI, so a slot
such as ``reference_type`` (``slot_uri: ex:referenceType``) was taken for the
reference field. URI-detected fields are tried before the name fallbacks, so it
shadowed the real ``reference`` slot and validation tried to fetch "journal
article" (#142). Excerpt detection had the same weakness as a bare substring
("excerpt" in ``ex:excerpt_location``).

The rule now: the URI's local name must end in the term, after at most one
generic suffix such as ``Field`` or ``Id``. So ``myReferenceField``,
``reference_id`` and ``cross_reference`` still name a reference, and
``referenceType`` and ``referenceCount`` do not.

Also here: a successful validation said "title validated" when the reference
had no title to compare against (#130).
"""

import pytest
from linkml.validator import Validator  # type: ignore[import-untyped]

from linkml_reference_validator.field_detection import ExcerptURIs, ReferenceURIs
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)


@pytest.mark.parametrize(
    "uri",
    [
        "ex:referenceType",
        "ex:reference_type",
        "ex:referenceCount",
        "http://example.org/referenceStatus",
        "ex:references_format",
    ],
)
def test_a_property_of_a_reference_is_not_a_reference(uri):
    assert ReferenceURIs.is_reference_uri(uri) is False


@pytest.mark.parametrize(
    "uri",
    [
        "ex:reference",
        "ex:references",
        "ex:reference_id",
        "ex:referenceIds",
        "ex:referenceUri",
        "http://example.org/myReferenceField",
        "ex:cross_reference",
        "ex:primaryReference",
        "dcterms:references",
        "linkml:authoritative_reference",
        "http://example.org/reference/",
    ],
)
def test_a_uri_naming_a_reference_still_matches(uri):
    assert ReferenceURIs.is_reference_uri(uri) is True


@pytest.mark.parametrize(
    "uri",
    [
        "ex:excerpt_location",
        "ex:excerptSource",
        "ex:supporting_text_length",
        "ex:exactness",
        "http://www.w3.org/ns/oa#exactMatch",
        # An identifier of an excerpt is not the excerpt.
        "ex:excerpt_id",
        "ex:supportingTextUri",
        "ex:excerpt_curie",
        # oa:exact anchored, not any URI that happens to end in those letters.
        "http://example.org/noa#exact",
        "ex:foa:exact",
    ],
)
def test_a_property_of_an_excerpt_is_not_an_excerpt(uri):
    assert ExcerptURIs.is_excerpt_uri(uri) is False


@pytest.mark.parametrize(
    "uri",
    [
        "oa:exact",
        "http://www.w3.org/ns/oa#exact",
        "linkml:excerpt",
        "https://w3id.org/linkml/excerpt",
        "http://example.org/myExcerptField",
        "supporting_text",
        "ex:supportingText",
        "ex:excerpts",
        "https://www.w3.org/ns/oa#exact",
        "http://example.org/excerpt/",
    ],
)
def test_a_uri_naming_an_excerpt_still_matches(uri):
    assert ExcerptURIs.is_excerpt_uri(uri) is True


SCHEMA = """
id: https://example.org/test
name: test
prefixes:
  linkml: https://w3id.org/linkml/
  ex: https://example.org/
default_prefix: ex
imports:
  - linkml:types
classes:
  Evidence:
    tree_root: true
    attributes:
      reference_type:
        range: string
        slot_uri: ex:referenceType
      reference:
        range: string
      supporting_text:
        range: string
      excerpt_location:
        range: string
        slot_uri: ex:excerpt_location
"""


@pytest.fixture
def validator(tmp_path, fixtures_dir):
    schema = tmp_path / "schema.yaml"
    schema.write_text(SCHEMA)
    cache = tmp_path / "cache"
    cache.mkdir()
    for source in fixtures_dir.glob("*.md"):
        (cache / source.name).write_text(source.read_text())
    plugin = ReferenceValidationPlugin(
        config=ReferenceValidationConfig(cache_dir=cache, fetch_full_text=False)
    )
    return plugin, Validator(schema=str(schema), validation_plugins=[plugin])


def test_the_issue_schema_validates_against_the_real_reference(validator):
    """The reproduction from #142: no "Could not fetch reference: journal article"."""
    plugin, v = validator
    report = v.validate({
        "reference_type": "journal article",
        "reference": "PMID:TEST001",
        "supporting_text": "Protein X functions in cell cycle regulation",
        "excerpt_location": "abstract, first sentence",
    })
    assert [r.message for r in report.results] == []
    assert plugin.snippets_checked == 1


def test_the_issue_schema_still_catches_a_wrong_quote(validator):
    _, v = validator
    report = v.validate({
        "reference_type": "journal article",
        "reference": "PMID:TEST001",
        "supporting_text": "Protein X has nothing to do with the cell cycle",
    })
    assert len(report.results) == 1
    assert "journal article" not in report.results[0].message


# --- #130 ---------------------------------------------------------------------


class _Fetcher:
    """Serves one in-memory reference, so no cache or network is involved."""

    def __init__(self, reference: ReferenceContent):
        self.reference = reference

    def fetch(self, reference_id, force_refresh=False):
        return self.reference


def _validate_against(title):
    validator = SupportingTextValidator(ReferenceValidationConfig())
    validator.fetcher = _Fetcher(  # type: ignore[assignment]
        ReferenceContent(reference_id="PMID:1", content="PTEN activates AKT.", title=title)
    )
    return validator.validate("PTEN activates AKT", "PMID:1", expected_title="A Totally Wrong Title")


def test_no_title_to_compare_is_not_reported_as_validated():
    """The reproduction from #130."""
    result = _validate_against(None)
    assert result.is_valid
    assert "title validated" not in result.message
    assert "title not checked" in result.message
    assert result.title_checked is False


def test_a_matching_title_is_still_reported_as_validated():
    validator = SupportingTextValidator(ReferenceValidationConfig())
    validator.fetcher = _Fetcher(  # type: ignore[assignment]
        ReferenceContent(reference_id="PMID:1", content="PTEN activates AKT.", title="A Title")
    )
    result = validator.validate("PTEN activates AKT", "PMID:1", expected_title="A Title")
    assert result.is_valid
    assert result.message.endswith(", title validated")
