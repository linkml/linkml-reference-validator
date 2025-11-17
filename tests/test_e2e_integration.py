"""End-to-end integration tests with real LinkML schemas and data."""

import pytest
from linkml.validator import Validator  # type: ignore[import-untyped]
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)


@pytest.fixture
def e2e_schema_file(tmp_path):
    """Create a real LinkML schema for E2E testing."""
    schema_file = tmp_path / "test_schema.yaml"
    schema_file.write_text("""
id: https://example.org/biomedical-evidence
name: biomedical-evidence
prefixes:
  linkml: https://w3id.org/linkml/
  test: https://example.org/test/
default_prefix: test

classes:
  Evidence:
    description: Evidence supporting a claim
    attributes:
      reference:
        description: Reference to publication
        range: Reference
        implements:
          - linkml:authoritative_reference
      supporting_text:
        description: Quote from the reference
        range: string
        implements:
          - linkml:excerpt
      confidence:
        range: string

  Reference:
    description: A publication reference
    attributes:
      id:
        identifier: true
        range: string
      title:
        range: string
      authors:
        range: string
        multivalued: true

  GeneStatement:
    tree_root: true
    description: A statement about a gene
    attributes:
      gene_symbol:
        range: string
        required: true
      statement_text:
        range: string
        required: true
      has_evidence:
        range: Evidence
        multivalued: true
""")
    return schema_file


@pytest.fixture
def e2e_plugin(test_config):
    """Create plugin with test fixtures."""
    return ReferenceValidationPlugin(config=test_config)


def test_e2e_valid_evidence_with_nested_reference(e2e_schema_file, e2e_plugin):
    """Test E2E validation with valid nested reference structure."""
    validator = Validator(
        schema=str(e2e_schema_file),
        validation_plugins=[e2e_plugin],
    )

    data = {
        "gene_symbol": "BRCA1",
        "statement_text": "BRCA1 plays a role in DNA repair",
        "has_evidence": [
            {
                "reference": {
                    "id": "PMID:TEST001",
                    "title": "Protein X functions in cell cycle regulation",
                },
                "supporting_text": "Protein X functions in cell cycle regulation and plays a critical role in DNA repair mechanisms",
            }
        ],
    }

    report = validator.validate(data, target_class="GeneStatement")

    # Should pass - text is in reference and title matches
    assert len(report.results) == 0 or all(r.severity.value != "ERROR" for r in report.results)


def test_e2e_invalid_excerpt_not_in_reference(e2e_schema_file, e2e_plugin):
    """Test E2E validation with excerpt that's not in the reference."""
    validator = Validator(
        schema=str(e2e_schema_file),
        validation_plugins=[e2e_plugin],
    )

    data = {
        "gene_symbol": "BRCA1",
        "statement_text": "BRCA1 plays a role in DNA repair",
        "has_evidence": [
            {
                "reference": {
                    "id": "PMID:TEST001",
                    "title": "Protein X functions in cell cycle regulation",
                },
                "supporting_text": "This text is completely made up and not in the reference at all",
            }
        ],
    }

    report = validator.validate(data, target_class="GeneStatement")

    # Should fail - text is not in reference
    assert len(report.results) > 0
    assert any(r.severity.value == "ERROR" for r in report.results)
    assert any("not found" in r.message.lower() for r in report.results)


def test_e2e_title_mismatch(e2e_schema_file, e2e_plugin):
    """Test E2E validation with title mismatch."""
    validator = Validator(
        schema=str(e2e_schema_file),
        validation_plugins=[e2e_plugin],
    )

    data = {
        "gene_symbol": "BRCA1",
        "statement_text": "BRCA1 plays a role in DNA repair",
        "has_evidence": [
            {
                "reference": {
                    "id": "PMID:TEST001",
                    "title": "Wrong Title Here",  # Doesn't match cached title
                },
                "supporting_text": "Protein X functions in cell cycle regulation",
            }
        ],
    }

    report = validator.validate(data, target_class="GeneStatement")

    # Should fail - title doesn't match
    assert len(report.results) > 0
    assert any(r.severity.value == "ERROR" for r in report.results)
    assert any("title mismatch" in r.message.lower() for r in report.results)


def test_e2e_multiple_evidence_items(e2e_schema_file, e2e_plugin):
    """Test E2E validation with multiple evidence items."""
    validator = Validator(
        schema=str(e2e_schema_file),
        validation_plugins=[e2e_plugin],
    )

    data = {
        "gene_symbol": "TP53",
        "statement_text": "TP53 regulates cell cycle and apoptosis",
        "has_evidence": [
            {
                "reference": {
                    "id": "PMID:TEST001",
                    "title": "Protein X functions in cell cycle regulation",
                },
                "supporting_text": "Protein X functions in cell cycle regulation and plays a critical role",
            },
            {
                "reference": {
                    "id": "PMID:TEST002",
                    "title": "Role of Protein Y in apoptosis pathway",  # Corrected title
                },
                "supporting_text": "Protein Y inhibits apoptosis through direct interaction with caspase-3",
            },
        ],
    }

    report = validator.validate(data, target_class="GeneStatement")

    # Both evidence items should validate successfully
    assert len([r for r in report.results if r.severity.value == "ERROR"]) == 0


def test_e2e_flat_reference_id_string(tmp_path, test_config):
    """Test E2E with flat reference_id as string (alternative data shape)."""
    schema_file = tmp_path / "flat_schema.yaml"
    schema_file.write_text("""
id: https://example.org/flat-evidence
name: flat-evidence
prefixes:
  linkml: https://w3id.org/linkml/
default_prefix: test

classes:
  FlatEvidence:
    tree_root: true
    attributes:
      reference_id:
        range: string
        implements:
          - linkml:authoritative_reference
      quote:
        range: string
        implements:
          - linkml:excerpt
""")

    plugin = ReferenceValidationPlugin(config=test_config)
    validator = Validator(
        schema=str(schema_file),
        validation_plugins=[plugin],
    )

    data = {
        "reference_id": "PMID:TEST001",
        "quote": "Protein X functions in cell cycle regulation and plays a critical role",
    }

    report = validator.validate(data, target_class="FlatEvidence")

    # Should pass - flat structure is supported
    assert len([r for r in report.results if r.severity.value == "ERROR"]) == 0


def test_e2e_missing_reference(e2e_schema_file, e2e_plugin):
    """Test E2E validation with missing/uncached reference."""
    validator = Validator(
        schema=str(e2e_schema_file),
        validation_plugins=[e2e_plugin],
    )

    data = {
        "gene_symbol": "BRCA1",
        "statement_text": "BRCA1 plays a role in DNA repair",
        "has_evidence": [
            {
                "reference": {
                    "id": "PMID:NONEXISTENT999",
                    "title": "Some Title",
                },
                "supporting_text": "Some text",
            }
        ],
    }

    report = validator.validate(data, target_class="GeneStatement")

    # Should fail - reference could not be fetched
    assert len(report.results) > 0
    assert any(r.severity.value == "ERROR" for r in report.results)
    assert any("could not fetch" in r.message.lower() for r in report.results)


def test_e2e_substring_matching_exact(e2e_schema_file, test_config):
    """Test E2E with substring matching for exact substrings."""
    plugin = ReferenceValidationPlugin(config=test_config)
    validator = Validator(
        schema=str(e2e_schema_file),
        validation_plugins=[plugin],
    )

    data = {
        "gene_symbol": "BRCA1",
        "statement_text": "BRCA1 plays a role in DNA repair",
        "has_evidence": [
            {
                "reference": {
                    "id": "PMID:TEST001",
                    "title": "Protein X functions in cell cycle regulation",
                },
                # This exact substring should match (using actual text from fixture)
                "supporting_text": "Protein X functions in cell cycle regulation and plays a critical role in DNA repair mechanisms",
            }
        ],
    }

    report = validator.validate(data, target_class="GeneStatement")

    # Should pass - text is exact substring
    error_results = [r for r in report.results if r.severity.value == "ERROR"]
    assert len(error_results) == 0


def test_e2e_substring_matching_not_found(e2e_schema_file, test_config):
    """Test E2E with substring not present in reference."""
    plugin = ReferenceValidationPlugin(config=test_config)
    validator = Validator(
        schema=str(e2e_schema_file),
        validation_plugins=[plugin],
    )

    data = {
        "gene_symbol": "BRCA1",
        "statement_text": "BRCA1 plays a role in DNA repair",
        "has_evidence": [
            {
                "reference": {
                    "id": "PMID:TEST001",
                    "title": "Protein X functions in cell cycle regulation",
                },
                # Different wording - should fail since "operates" is not in reference
                "supporting_text": "Protein X operates in cell cycle regulation",
            }
        ],
    }

    report = validator.validate(data, target_class="GeneStatement")

    # Should fail - text not found as substring
    assert len(report.results) > 0
    assert any(r.severity.value == "ERROR" for r in report.results)


def test_e2e_list_of_instances(e2e_schema_file, e2e_plugin):
    """Test E2E validation with a list of instances."""
    validator = Validator(
        schema=str(e2e_schema_file),
        validation_plugins=[e2e_plugin],
    )

    instances = [
        {
            "gene_symbol": "GENE1",
            "statement_text": "Statement 1",
            "has_evidence": [
                {
                    "reference": {"id": "PMID:TEST001"},
                    "supporting_text": "Protein X functions in cell cycle regulation",
                }
            ],
        },
        {
            "gene_symbol": "GENE2",
            "statement_text": "Statement 2",
            "has_evidence": [
                {
                    "reference": {"id": "PMID:TEST002"},
                    "supporting_text": "Protein Y inhibits apoptosis",
                }
            ],
        },
    ]

    # Validate each instance
    all_results = []
    for instance in instances:
        report = validator.validate(instance, target_class="GeneStatement")
        all_results.extend(report.results)

    # Both should validate successfully
    error_results = [r for r in all_results if r.severity.value == "ERROR"]
    assert len(error_results) == 0
