"""Inline section headings in a PubMed abstract stay separate words.

Some publishers supply a structured abstract as one ``AbstractText`` whose
section headings are inline bold, with no space after them:
``<b>Background</b>Neuroblastoma can arise...``. ``get_text()`` then welds the
heading onto the first word ("BackgroundNeuroblastoma"), and since matching
became whole-word (#150) a correct quote beginning at that word fails.
PMID:33307929 is the real record this comes from.
"""

from bs4 import BeautifulSoup

from linkml_reference_validator.etl.sources.pmid import PMIDSource
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator

PMID_33307929 = (
    "<Abstract><AbstractText><b>Background</b>Neuroblastoma can arise from "
    "extra-adrenal sites in the paraspinal sympathetic chain, including the "
    "presacral region, where they must be differentiated from an immature or "
    "malignant neural lesion arising from a teratoma.<b>Case Report</b>We "
    "describe two congenital presacral neuroblastomas.</AbstractText></Abstract>"
)


def render(xml: str) -> str:
    """The abstract text the PMID source would cache for ``xml``."""
    rendered = PMIDSource()._parse_abstract(BeautifulSoup(xml, "xml"))
    assert rendered is not None
    return rendered


def found(quote: str, content: str) -> bool:
    """Whether ``quote`` validates against ``content``."""
    validator = SupportingTextValidator(ReferenceValidationConfig())
    reference = ReferenceContent(reference_id="PMID:1", content=content)
    return validator.find_text_in_reference(quote, reference).found


def test_inline_headings_are_set_off_as_labels():
    text = render(PMID_33307929)
    assert text.startswith("Background: Neuroblastoma can arise")
    assert "a teratoma.\n\nCase Report: We describe two" in text


def test_quotes_beginning_after_an_inline_heading_match():
    text = render(PMID_33307929)
    assert found("Neuroblastoma can arise from extra-adrenal sites", text)
    assert found("We describe two congenital presacral neuroblastomas.", text)


def test_bold_inside_a_sentence_is_left_alone():
    xml = (
        "<Abstract><AbstractText>Variants in <b>BRCA1</b> and "
        "<b>BRCA2</b>were found.</AbstractText></Abstract>"
    )
    assert render(xml) == "Variants in BRCA1 and BRCA2were found."


def test_a_heading_already_followed_by_a_space_or_colon_is_unchanged_in_words():
    xml = (
        "<Abstract><AbstractText><b>Background:</b> It began. "
        "<b>Results</b> It worked.</AbstractText></Abstract>"
    )
    text = render(xml)
    assert found("It began", text) and found("It worked", text)
    assert "Background:" in text and "::" not in text


def test_labelled_abstract_text_is_unchanged():
    xml = (
        '<Abstract><AbstractText Label="METHODS">We ran a trial.</AbstractText>'
        '<AbstractText Label="RESULTS">It worked.</AbstractText></Abstract>'
    )
    assert render(xml) == "METHODS: We ran a trial.\n\nRESULTS: It worked."


# PubMed itself sometimes stores the headings welded with no markup at all
# (PMID:39670790): "IntroductionThe black widow spider ... exposures.Conclusions
# Poison center data ...".
WELDED_PLAIN = (
    "<Abstract><AbstractText>IntroductionThe black widow spider is common. "
    "ResultsA total of 15,000 exposures were reported in 3.4% (n=521) of exposures."
    "ConclusionsPoison center data indicate that most exposures are minor."
    "</AbstractText></Abstract>"
)


def test_plain_welded_headings_are_set_off():
    text = render(WELDED_PLAIN)
    assert text.startswith("Introduction: The black widow spider")
    assert "of exposures.\n\nConclusions: Poison center data" in text
    assert found("The black widow spider is common", text)
    assert found("Poison center data indicate that most exposures are minor", text)
    assert found("A total of 15,000 exposures", text)


def test_heading_words_inside_sentences_are_left_alone():
    xml = (
        "<Abstract><AbstractText>The Results were striking. Methodsical work "
        "followed.</AbstractText></Abstract>"
    )
    text = render(xml)
    assert "The Results were striking." in text
    assert "Methodsical work" in text


def test_leading_bold_followed_by_a_hyphen_is_not_a_label():
    text = render("<Abstract><AbstractText><b>IL</b>-6 levels were raised.</AbstractText></Abstract>")
    assert found("IL-6 levels were raised", text), text
    assert "IL:" not in text


def test_bold_after_a_full_stop_but_not_welded_is_not_a_label():
    xml = (
        "<Abstract><AbstractText>It was observed. <b>Importantly</b>, the effect held, "
        "vs. <b>BRCA2</b> carriers.</AbstractText></Abstract>"
    )
    text = render(xml)
    assert "Importantly:" not in text and "BRCA2:" not in text
    assert found("observed. Importantly, the effect held", text)


def test_chained_welded_headings_are_all_split():
    text = render("<Abstract><AbstractText>AbstractBackgroundIt began.</AbstractText></Abstract>")
    assert found("It began", text), text
    assert text == "Abstract: Background: It began."
