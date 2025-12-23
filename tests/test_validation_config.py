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
