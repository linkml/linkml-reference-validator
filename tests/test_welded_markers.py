"""Citation markers, lead-in labels and section titles stay separate words.

Matching became whole-word in #150, so text an extractor welds together now
fails a correct quote where a substring test used to pass it. Each case here is
from a real cached reference that a downstream knowledge base quoted:

- a JATS citation ``FOXL2<sup><xref ref-type="bibr">8</xref></sup>.`` read as
  ``FOXL28.`` (PMC6851130), and ``PGE2.<sup>41</sup>`` as the number ``pge2.41``;
- a paragraph's bold lead-in label ``<bold>R 2.6</bold>We recommend`` read as
  ``2.6We`` (PMC9066594);
- a Crossref JATS abstract ``<jats:title>Abstract</jats:title><jats:sec>
  <jats:title>Disease overview</jats:title><jats:p>Acute myeloid...`` read as
  ``AbstractDisease overviewAcute myeloid`` (DOI:10.1002/ajh.26822);
- a superscript citation range ``ears¹⁻³`` (PMID:21358632), which the
  trailing-citation allowance did not cover because ``¹`` is not a decimal
  digit.
"""

import pytest

from linkml_reference_validator.etl.extract.xml import XMLExtractor
from linkml_reference_validator.etl.sources.doi import DOISource
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)


def extract(body: str) -> str:
    text = XMLExtractor().extract(f"<article><body>{body}</body></article>".encode())
    assert text is not None
    return text


def found(quote: str, content: str) -> bool:
    validator = SupportingTextValidator(ReferenceValidationConfig())
    reference = ReferenceContent(reference_id="PMID:1", content=content)
    return validator.find_text_in_reference(quote, reference).found


# --- JATS citation markers -------------------------------------------------


@pytest.mark.parametrize(
    "body,quote",
    [
        (
            '<p>It inhibits the expression of FOXL2<sup><xref ref-type="bibr" '
            'rid="CR8">8</xref></sup>. Here we add PITX2.</p>',
            "inhibits the expression of FOXL2",
        ),
        (
            '<p>caused by mutations in KCNA1<xref ref-type="bibr" rid="B18">18</xref>). '
            "At last follow up.</p>",
            "caused by mutations in KCNA1",
        ),
        (
            '<p>and a deficiency of PGE2.<sup><xref ref-type="bibr" rid="B41">41</xref></sup>'
            " Next sentence.</p>",
            "a deficiency of PGE2",
        ),
        (
            '<p>if left untreated.<sup><xref ref-type="bibr" rid="B2">2</xref>,'
            '<xref ref-type="bibr" rid="B8">8</xref></sup>Damage to major organs.</p>',
            "Damage to major organs",
        ),
    ],
)
def test_citation_markers_do_not_weld(body, quote):
    text = extract(body)
    assert found(quote, text), text


def test_citation_marker_still_reads_as_its_number():
    text = extract('<p>shown before<sup><xref ref-type="bibr" rid="B8">8</xref></sup>.</p>')
    assert "shown before 8" in text


def test_non_citation_superscripts_stay_attached():
    """A unit exponent or a figure link is not a citation; only bibr is padded."""
    text = extract(
        '<p>at 10<sup>6</sup> cells, see <xref ref-type="fig" rid="F1">Figure 1</xref>'
        "a, and H<sub>2</sub>O.</p>"
    )
    assert "10⁶" in text or "106" in text
    assert "H2O" in text


# --- Bold lead-in labels ---------------------------------------------------


def test_leading_bold_label_is_set_off():
    text = extract(
        "<p><bold>R 2.6</bold>We recommend to use 17β-oestradiol for puberty induction.</p>"
    )
    assert found("We recommend to use 17β-oestradiol", text), text


def test_bold_inside_a_sentence_is_left_alone():
    text = extract("<p>Variants in <bold>BRCA1</bold>were found.</p>")
    assert "BRCA1were" in text


# --- Crossref JATS abstracts -----------------------------------------------

CROSSREF_ABSTRACT = (
    "<jats:title>Abstract</jats:title>\n"
    "                  <jats:sec>\n"
    "                    <jats:title>Disease overview</jats:title>\n"
    "                    <jats:p>Acute myeloid leukemia (AML) is a frequently fatal "
    "bone marrow stem cell cancer.</jats:p>\n"
    "                  </jats:sec>\n"
    "                  <jats:sec><jats:title>Diagnosis</jats:title>"
    "<jats:p>One updated and one <jats:italic>new</jats:italic> classification.</jats:p>"
    "</jats:sec>"
)


def test_crossref_abstract_sections_are_separate_paragraphs():
    text = DOISource()._clean_abstract(CROSSREF_ABSTRACT)
    assert text.split("\n\n") == [
        "Abstract",
        "Disease overview",
        "Acute myeloid leukemia (AML) is a frequently fatal bone marrow stem cell cancer.",
        "Diagnosis",
        "One updated and one new classification.",
    ]
    assert found("Acute myeloid leukemia (AML) is a frequently fatal", text)
    assert found("One updated and one new classification", text)


def test_crossref_plain_paragraph_is_unchanged():
    assert DOISource()._clean_abstract("<jats:p>Test abstract.</jats:p>") == "Test abstract."


# --- Superscript citations in plain text -----------------------------------


@pytest.mark.parametrize(
    "quote,content",
    [
        ("markedly small ears", "patellae and markedly small ears¹⁻³. Both pre-"),
        ("markedly small ears", "patellae and markedly small ears²³ and"),
    ],
)
def test_superscript_citation_after_a_word_is_allowed(quote, content):
    assert found(quote, content)


def test_superscript_does_not_extend_a_number():
    """The allowance stays letter-only: a quote ending in a digit gets none."""
    assert not found("a dose of 10", "a dose of 10⁶ cells")


@pytest.mark.parametrize(
    "body,quote",
    [
        ("<p><bold>IL</bold>-6 levels were raised.</p>", "IL-6 levels were raised"),
        ("<p><bold>BRCA1</bold> mutations were found.</p>", "BRCA1 mutations were found"),
    ],
)
def test_leading_bold_that_is_not_welded_is_left_alone(body, quote):
    """Only a bold followed directly by a letter is a welded label (IL-6 is not)."""
    text = extract(body)
    assert found(quote, text), text


def test_crossref_html_breaks_and_divs_separate_paragraphs():
    text = DOISource()._clean_abstract("<div>First part.</div><div>Second part.</div>a<br/>b")
    assert text.split("\n\n") == ["First part.", "Second part.", "a", "b"]


@pytest.mark.parametrize(
    "body,quote",
    [
        ("<p>shown (<xref ref-type=\"bibr\" rid=\"B1\">1</xref>-3) before.</p>", "shown (1-3) before"),
        ('<p>small ears<sup><xref ref-type="bibr" rid="B1">1</xref>–3</sup> in all.</p>', "small ears"),
    ],
)
def test_citation_range_with_its_first_number_linked_keeps_its_dash(body, quote):
    """A dash after a padded marker must not become a minus sign."""
    text = extract(body)
    assert found(quote, text), text
