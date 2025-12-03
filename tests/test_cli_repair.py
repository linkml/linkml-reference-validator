"""Tests for repair CLI commands."""

import pytest
from typer.testing import CliRunner
from linkml_reference_validator.cli import app

runner = CliRunner()


@pytest.fixture
def cli_cache_dir(tmp_path, fixtures_dir):
    """Set up cache directory with test fixtures for CLI tests."""
    cache_dir = tmp_path / "cli_cache"
    cache_dir.mkdir()

    # Copy all fixtures (including .md files)
    for fixture_file in fixtures_dir.glob("*"):
        if fixture_file.is_file():
            (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    return cache_dir


# ============================================================================
# Test repair text command
# ============================================================================


def test_repair_text_already_valid(cli_cache_dir):
    """Test repair text command with already valid text."""
    result = runner.invoke(
        app,
        [
            "repair",
            "text",
            "Protein X functions in cell cycle regulation",
            "PMID:TEST001",
            "--cache-dir",
            str(cli_cache_dir),
        ],
    )

    assert result.exit_code == 0
    assert "already valid" in result.stdout.lower()


def test_repair_text_character_normalization(cli_cache_dir):
    """Test repair text command with character normalization."""
    result = runner.invoke(
        app,
        [
            "repair",
            "text",
            "CO2 levels were measured",
            "PMID:TEST001",
            "--cache-dir",
            str(cli_cache_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Repaired" in result.stdout
    assert "CO₂" in result.stdout
    assert "CHARACTER_NORMALIZATION" in result.stdout


def test_repair_text_not_found(cli_cache_dir):
    """Test repair text command with text not in reference."""
    result = runner.invoke(
        app,
        [
            "repair",
            "text",
            "This text is completely fabricated and does not exist",
            "PMID:TEST001",
            "--cache-dir",
            str(cli_cache_dir),
        ],
    )

    assert result.exit_code == 1
    assert "Could not repair" in result.stdout


def test_repair_text_verbose(cli_cache_dir):
    """Test repair text command with verbose output."""
    result = runner.invoke(
        app,
        [
            "repair",
            "text",
            "CO2 levels were measured",
            "PMID:TEST001",
            "--cache-dir",
            str(cli_cache_dir),
            "--verbose",
        ],
    )

    assert result.exit_code == 0
    assert "Confidence" in result.stdout


# ============================================================================
# Test repair data command
# ============================================================================


def test_repair_data_dry_run(tmp_path, cli_cache_dir):
    """Test repair data command with dry run."""
    # Create test schema
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text("""
id: https://example.org/test
name: test
prefixes:
  linkml: https://w3id.org/linkml/
default_prefix: test

classes:
  Statement:
    tree_root: true
    attributes:
      text:
        range: string
      evidence:
        multivalued: true
        range: Evidence

  Evidence:
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
""")

    # Create test data with CO2 instead of CO₂
    data_file = tmp_path / "data.yaml"
    data_file.write_text("""
text: "Test statement"
evidence:
  - reference: "PMID:TEST001"
    supporting_text: "CO2 levels were measured"
""")

    result = runner.invoke(
        app,
        [
            "repair",
            "data",
            str(data_file),
            "--schema",
            str(schema_file),
            "--cache-dir",
            str(cli_cache_dir),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "DRY RUN" in result.stdout
    assert "Repair Report" in result.stdout


def test_repair_data_apply_fixes(tmp_path, cli_cache_dir):
    """Test repair data command with fixes applied."""
    # Create test schema
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text("""
id: https://example.org/test
name: test
default_prefix: test

classes:
  Statement:
    tree_root: true
    attributes:
      text:
        range: string
      evidence:
        multivalued: true
        range: Evidence

  Evidence:
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
""")

    # Create test data
    data_file = tmp_path / "data.yaml"
    data_file.write_text("""
text: "Test statement"
evidence:
  - reference: "PMID:TEST001"
    supporting_text: "CO2 levels were measured"
""")

    result = runner.invoke(
        app,
        [
            "repair",
            "data",
            str(data_file),
            "--schema",
            str(schema_file),
            "--cache-dir",
            str(cli_cache_dir),
            "--no-dry-run",
        ],
    )

    # Check result
    assert "Repair Report" in result.stdout
    # Should create backup
    assert (tmp_path / "data.yaml.bak").exists()


def test_repair_data_output_file(tmp_path, cli_cache_dir):
    """Test repair data command with custom output file."""
    # Create test schema
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text("""
id: https://example.org/test
name: test
default_prefix: test

classes:
  Statement:
    tree_root: true
    attributes:
      text:
        range: string
      evidence:
        multivalued: true
        range: Evidence

  Evidence:
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
""")

    # Create test data
    data_file = tmp_path / "data.yaml"
    data_file.write_text("""
text: "Test statement"
evidence:
  - reference: "PMID:TEST001"
    supporting_text: "CO2 levels were measured"
""")

    output_file = tmp_path / "repaired.yaml"

    result = runner.invoke(
        app,
        [
            "repair",
            "data",
            str(data_file),
            "--schema",
            str(schema_file),
            "--cache-dir",
            str(cli_cache_dir),
            "--no-dry-run",
            "--output",
            str(output_file),
        ],
    )

    assert "Repair Report" in result.stdout
    assert output_file.exists()


def test_repair_data_with_valid_data(tmp_path, cli_cache_dir):
    """Test repair data command with already valid data."""
    # Create test schema
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text("""
id: https://example.org/test
name: test
default_prefix: test

classes:
  Statement:
    tree_root: true
    attributes:
      text:
        range: string
      evidence:
        multivalued: true
        range: Evidence

  Evidence:
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
""")

    # Create valid test data
    data_file = tmp_path / "data.yaml"
    data_file.write_text("""
text: "Test statement"
evidence:
  - reference: "PMID:TEST001"
    supporting_text: "Protein X functions in cell cycle regulation"
""")

    result = runner.invoke(
        app,
        [
            "repair",
            "data",
            str(data_file),
            "--schema",
            str(schema_file),
            "--cache-dir",
            str(cli_cache_dir),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0
    assert "Already valid: 1" in result.stdout


# ============================================================================
# Test configuration file support
# ============================================================================


def test_repair_data_with_config_file(tmp_path, cli_cache_dir):
    """Test repair data command with configuration file."""
    # Create test schema
    schema_file = tmp_path / "schema.yaml"
    schema_file.write_text("""
id: https://example.org/test
name: test
default_prefix: test

classes:
  Statement:
    tree_root: true
    attributes:
      text:
        range: string
      evidence:
        multivalued: true
        range: Evidence

  Evidence:
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
""")

    # Create test data with evidence
    data_file = tmp_path / "data.yaml"
    data_file.write_text("""
text: "Test statement"
evidence:
  - reference: "PMID:TEST001"
    supporting_text: "CO2 levels were measured"
""")

    # Create config file
    config_file = tmp_path / "repair-config.yaml"
    config_file.write_text("""
repair:
  auto_fix_threshold: 0.98
  suggest_threshold: 0.85
  character_mappings:
    "CO2": "CO₂"
    "H2O": "H₂O"
""")

    result = runner.invoke(
        app,
        [
            "repair",
            "data",
            str(data_file),
            "--schema",
            str(schema_file),
            "--cache-dir",
            str(cli_cache_dir),
            "--config",
            str(config_file),
            "--dry-run",
        ],
    )

    assert "Repair Report" in result.stdout


# ============================================================================
# Test error handling
# ============================================================================


def test_repair_data_missing_file(tmp_path):
    """Test repair data command with missing data file."""
    result = runner.invoke(
        app,
        [
            "repair",
            "data",
            str(tmp_path / "nonexistent.yaml"),
            "--schema",
            str(tmp_path / "schema.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


def test_repair_data_missing_schema(tmp_path):
    """Test repair data command with missing schema file."""
    data_file = tmp_path / "data.yaml"
    data_file.write_text("text: test")

    result = runner.invoke(
        app,
        [
            "repair",
            "data",
            str(data_file),
            "--schema",
            str(tmp_path / "nonexistent.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "not found" in result.stdout.lower()


# ============================================================================
# Test help messages
# ============================================================================


def test_repair_help():
    """Test repair command help."""
    result = runner.invoke(app, ["repair", "--help"])
    assert result.exit_code == 0
    assert "Repair supporting text" in result.stdout


def test_repair_text_help():
    """Test repair text command help."""
    result = runner.invoke(app, ["repair", "text", "--help"])
    assert result.exit_code == 0
    assert "supporting text quote" in result.stdout.lower()


def test_repair_data_help():
    """Test repair data command help."""
    result = runner.invoke(app, ["repair", "data", "--help"])
    assert result.exit_code == 0
    assert "data file" in result.stdout.lower()
