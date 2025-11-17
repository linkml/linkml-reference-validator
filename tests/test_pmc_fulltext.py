"""Tests for PMC full-text validation using real cached PMC articles."""

from linkml_reference_validator.models import ValidationSeverity


def test_validate_with_pmc_fulltext_xml(validator_with_fixtures):
    """Test validation against PMC full-text XML article."""
    result = validator_with_fixtures.validate(
        "BRCA1 participates in homologous recombination repair of double-strand breaks",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO
    assert "validated" in result.message.lower()
    assert result.match_result is not None
    assert result.match_result.found is True


def test_validate_with_pmc_fulltext_html(validator_with_fixtures):
    """Test validation against PMC full-text HTML article."""
    result = validator_with_fixtures.validate(
        "TP53 is the most frequently mutated gene in human cancers",
        "PMC:TEST002",
    )

    assert result.is_valid is True
    assert result.severity == ValidationSeverity.INFO
    assert result.match_result.found is True


def test_pmc_content_from_introduction(validator_with_fixtures):
    """Test validation with text from Introduction section of PMC article."""
    result = validator_with_fixtures.validate(
        "BRCA1 interacts with multiple proteins in the DNA repair machinery",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.found is True


def test_pmc_content_from_results_section(validator_with_fixtures):
    """Test validation with text from Results section of PMC article."""
    result = validator_with_fixtures.validate(
        "The BRCA1-RAD51 complex facilitates strand invasion during homologous recombination",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.found is True


def test_pmc_content_from_discussion(validator_with_fixtures):
    """Test validation with text from Discussion section."""
    result = validator_with_fixtures.validate(
        "The interaction between BRCA1 and RAD51 is crucial for effective DNA repair",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.found is True


def test_pmc_specific_biological_claim(validator_with_fixtures):
    """Test validation with specific biological claim from PMC article."""
    result = validator_with_fixtures.validate(
        "truncating mutations in the RING domain abolish E3 ubiquitin ligase activity",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.found is True


def test_pmc_title_validation_success(validator_with_fixtures):
    """Test PMC article with correct title validation."""
    result = validator_with_fixtures.validate(
        "BRCA1 participates in homologous recombination repair",
        "PMC:TEST001",
        expected_title="Molecular mechanisms of BRCA1 in DNA repair",
    )

    assert result.is_valid is True
    assert "title validated" in result.message


def test_pmc_title_validation_mismatch(validator_with_fixtures):
    """Test PMC article with incorrect title."""
    result = validator_with_fixtures.validate(
        "BRCA1 participates in homologous recombination repair",
        "PMC:TEST001",
        expected_title="Wrong Title",
    )

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR
    assert "title mismatch" in result.message.lower()


def test_pmc_text_not_in_article(validator_with_fixtures):
    """Test validation fails when text is not in PMC article."""
    result = validator_with_fixtures.validate(
        "This completely fabricated text does not appear anywhere in the article",
        "PMC:TEST001",
    )

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR
    assert "not found" in result.message.lower()


def test_pmc_substring_matching_with_fulltext(validator_with_fixtures):
    """Test substring matching works with PMC full-text."""
    # Exact substring should match
    result = validator_with_fixtures.validate(
        "BRCA1 participates in homologous recombination repair",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.similarity_score == 1.0


def test_pmc_multi_sentence_quote(validator_with_fixtures):
    """Test validation with multi-sentence quote from PMC article."""
    result = validator_with_fixtures.validate(
        "BRCA1 forms a complex with RAD51 at sites of DNA damage. The BRCA1-RAD51 complex facilitates strand invasion",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.found is True


def test_pmc_quote_with_technical_terms(validator_with_fixtures):
    """Test validation with technical biological terms."""
    result = validator_with_fixtures.validate(
        "Li-Fraumeni syndrome is a hereditary cancer predisposition disorder caused by germline TP53 mutations",
        "PMC:TEST002",
    )

    assert result.is_valid is True
    assert result.match_result.found is True


def test_pmc_partial_quote_with_ellipsis(validator_with_fixtures):
    """Test validation with partial quote using ellipsis."""
    result = validator_with_fixtures.validate(
        "p53 functions as a transcription factor ... involved in cell cycle arrest, apoptosis, DNA repair",
        "PMC:TEST002",
    )

    assert result.is_valid is True


def test_pmc_guardian_of_genome_quote(validator_with_fixtures):
    """Test validation with quote containing special terminology."""
    result = validator_with_fixtures.validate(
        'p53 protein, often called the "guardian of the genome"',
        "PMC:TEST002",
    )

    assert result.is_valid is True


def test_pmc_fulltext_reference_from_fetcher(fetcher_with_fixtures):
    """Test fetcher loads PMC full-text correctly."""
    ref = fetcher_with_fixtures.fetch("PMC:TEST001")

    assert ref is not None
    assert ref.reference_id == "PMC:TEST001"
    assert ref.title == "Molecular mechanisms of BRCA1 in DNA repair"
    assert ref.content_type == "full_text_xml"
    assert "BRCA1" in ref.content
    assert "homologous recombination" in ref.content
    assert ref.authors == ["Zhang L", "Williams T", "Anderson P", "Martinez S", "Thompson R"]
    assert ref.journal == "Cell"
    assert ref.year == "2023"


def test_pmc_html_content_type(fetcher_with_fixtures):
    """Test fetcher handles PMC HTML content type."""
    ref = fetcher_with_fixtures.fetch("PMC:TEST002")

    assert ref is not None
    assert ref.reference_id == "PMC:TEST002"
    assert ref.content_type == "full_text_html"
    assert "TP53" in ref.content
    assert "p53" in ref.content


def test_pmc_longer_content_than_abstract(fetcher_with_fixtures):
    """Test that PMC full-text has more content than abstracts."""
    pmc_ref = fetcher_with_fixtures.fetch("PMC:TEST001")
    pmid_ref = fetcher_with_fixtures.fetch("PMID:TEST001")

    # PMC full-text should be significantly longer
    assert len(pmc_ref.content) > len(pmid_ref.content) * 2


def test_pmc_methods_section_content(validator_with_fixtures):
    """Test validation with text from Methods section."""
    result = validator_with_fixtures.validate(
        "Cell lines with BRCA1 mutations were generated using CRISPR-Cas9 technology",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.found is True


def test_pmc_complex_biological_statement(validator_with_fixtures):
    """Test validation with complex multi-part biological statement."""
    result = validator_with_fixtures.validate(
        "cells lacking functional BRCA1 exhibit increased sensitivity to DNA damaging agents such as cisplatin and PARP inhibitors",
        "PMC:TEST001",
    )

    assert result.is_valid is True
    assert result.match_result.found is True
