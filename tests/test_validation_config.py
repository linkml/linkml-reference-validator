"""Tests for validation configuration loading."""

from linkml_reference_validator.cli.shared import load_validation_config


def test_load_validation_config_from_section(tmp_path):
    """Should load validation config from a named section."""
    config_file = tmp_path / ".linkml-reference-validator.yaml"
    config_file.write_text(
        """
validation:
  cache_dir: references_cache
  reference_prefix_map:
    geo: GEO
    NCBIGeo: GEO
"""
    )

    config = load_validation_config(config_file)

    assert config.cache_dir.name == "references_cache"
    assert config.reference_prefix_map["geo"] == "GEO"
    assert config.reference_prefix_map["NCBIGeo"] == "GEO"


def test_load_validation_config_ignores_repair_only(tmp_path):
    """Should ignore files that only define repair settings."""
    config_file = tmp_path / ".linkml-reference-validator.yaml"
    config_file.write_text(
        """
repair:
  auto_fix_threshold: 0.97
"""
    )

    config = load_validation_config(config_file)

    assert config.reference_prefix_map == {}


def test_full_text_config_defaults():
    from linkml_reference_validator.models import ReferenceValidationConfig

    config = ReferenceValidationConfig()
    assert config.fetch_full_text is True
    assert config.full_text_providers == ["pmc", "epmc_preprint", "unpaywall", "openalex"]
    assert config.pdf_backend == "pypdf"
    assert config.download_pdfs is True


def test_files_cache_dir(tmp_path):
    from linkml_reference_validator.models import ReferenceValidationConfig

    config = ReferenceValidationConfig(cache_dir=tmp_path / "cache")
    files_dir = config.get_files_cache_dir()
    assert files_dir == tmp_path / "cache" / "files"
    assert files_dir.exists()
def test_load_validation_config_literal_bracket_patterns(tmp_path):
    """Should load literal bracket patterns from validation config."""
    config_file = tmp_path / ".linkml-reference-validator.yaml"
    config_file.write_text(
        """
validation:
  literal_bracket_patterns:
    - "\\\\d"
    - "^\\\\S"
"""
    )

    config = load_validation_config(config_file)

    assert config.literal_bracket_patterns == [r"\d", r"^\S"]
