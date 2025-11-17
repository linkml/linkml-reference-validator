"""Tests for CLI commands."""

import pytest
from typer.testing import CliRunner
from linkml_reference_validator.cli import app

runner = CliRunner()


@pytest.fixture
def cli_cache_dir(tmp_path, fixtures_dir):
    """Set up cache directory with test fixtures for CLI tests."""
    cache_dir = tmp_path / "cli_cache"
    cache_dir.mkdir()

    # Copy fixtures
    for fixture_file in fixtures_dir.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    return cache_dir


def test_cli_help():
    """Test CLI help command."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "linkml-reference-validator" in result.stdout
    assert "Validation of supporting text" in result.stdout


def test_validate_text_command_success(cli_cache_dir):
    """Test validate-text command with valid text."""
    result = runner.invoke(
        app,
        [
            "validate-text",
            "Protein X functions in cell cycle regulation and plays a critical role",
            "PMID:TEST001",
            "--cache-dir",
            str(cli_cache_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Valid: True" in result.stdout
    assert "validated" in result.stdout.lower()


def test_validate_text_command_failure(cli_cache_dir):
    """Test validate-text command with invalid text."""
    result = runner.invoke(
        app,
        [
            "validate-text",
            "this text is not in the reference",
            "PMID:TEST001",
            "--cache-dir",
            str(cli_cache_dir),
        ],
    )

    assert result.exit_code == 1
    assert "Valid: False" in result.stdout
    assert "not found" in result.stdout.lower()


def test_validate_text_multi_part_with_ellipsis(cli_cache_dir):
    """Test validate-text with multi-part query using ellipsis."""
    result = runner.invoke(
        app,
        [
            "validate-text",
            "Protein X functions ... plays a critical role",
            "PMID:TEST001",
            "--cache-dir",
            str(cli_cache_dir),
        ],
    )

    assert result.exit_code == 0


def test_cache_reference_command(cli_cache_dir):
    """Test cache-reference command."""
    result = runner.invoke(
        app,
        [
            "cache-reference",
            "PMID:TEST001",
            "--cache-dir",
            str(cli_cache_dir),
        ],
    )

    assert result.exit_code == 0
    assert "Successfully cached" in result.stdout or "PMID:TEST001" in result.stdout


def test_cache_reference_missing(tmp_path):
    """Test cache-reference with missing reference."""
    result = runner.invoke(
        app,
        [
            "cache-reference",
            "PMID:NONEXISTENT999",
            "--cache-dir",
            str(tmp_path),
        ],
    )

    # Should fail since reference doesn't exist and can't be fetched
    assert result.exit_code == 1


def test_validate_data_command(tmp_path, fixtures_dir):
    """Test validate-data command with test schema and data."""
    # Set up cache
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for fixture_file in fixtures_dir.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    # Create test schema
    schema_file = tmp_path / "test_schema.yaml"
    schema_file.write_text("""
id: https://example.org/test
name: test
prefixes:
  linkml: https://w3id.org/linkml/
  test: https://example.org/test/
default_prefix: test

classes:
  Evidence:
    attributes:
      reference:
        range: Reference
        implements:
          - linkml:authoritative_reference
      supporting_text:
        range: string
        implements:
          - linkml:excerpt

  Reference:
    attributes:
      id:
        identifier: true
        range: string
      title:
        range: string

  Statement:
    tree_root: true
    attributes:
      text:
        range: string
      has_evidence:
        range: Evidence
        multivalued: true
""")

    # Create valid test data
    data_file = tmp_path / "test_data.yaml"
    data_file.write_text("""
text: "Test statement"
has_evidence:
  - reference:
      id: "PMID:TEST001"
      title: "Protein X functions in cell cycle regulation"
    supporting_text: "Protein X functions in cell cycle regulation and plays a critical role in DNA repair mechanisms"
""")

    result = runner.invoke(
        app,
        [
            "validate-data",
            str(data_file),
            "--schema",
            str(schema_file),
            "--cache-dir",
            str(cache_dir),
        ],
    )

    # Should pass validation
    assert result.exit_code == 0
    assert "All validations passed" in result.stdout or "passed" in result.stdout.lower()


def test_validate_data_command_failure(tmp_path, fixtures_dir):
    """Test validate-data command with invalid data."""
    # Set up cache
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for fixture_file in fixtures_dir.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    # Create test schema
    schema_file = tmp_path / "test_schema.yaml"
    schema_file.write_text("""
id: https://example.org/test
name: test
prefixes:
  linkml: https://w3id.org/linkml/
  test: https://example.org/test/
default_prefix: test

classes:
  Evidence:
    attributes:
      reference:
        range: Reference
        implements:
          - linkml:authoritative_reference
      supporting_text:
        range: string
        implements:
          - linkml:excerpt

  Reference:
    attributes:
      id:
        identifier: true
        range: string
      title:
        range: string

  Statement:
    tree_root: true
    attributes:
      text:
        range: string
      has_evidence:
        range: Evidence
        multivalued: true
""")

    # Create invalid test data
    data_file = tmp_path / "test_data_bad.yaml"
    data_file.write_text("""
text: "Test statement"
has_evidence:
  - reference:
      id: "PMID:TEST001"
      title: "Protein X functions in cell cycle regulation"
    supporting_text: "This text is definitely not in the reference at all"
""")

    result = runner.invoke(
        app,
        [
            "validate-data",
            str(data_file),
            "--schema",
            str(schema_file),
            "--cache-dir",
            str(cache_dir),
        ],
    )

    # Should fail validation
    assert result.exit_code == 1
    assert "Issues found" in result.stdout or "ERROR" in result.stdout


def test_validate_data_verbose_mode(tmp_path, fixtures_dir):
    """Test validate-data with verbose flag."""
    # Set up cache
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for fixture_file in fixtures_dir.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    # Create minimal schema
    schema_file = tmp_path / "test_schema.yaml"
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
""")

    data_file = tmp_path / "data.yaml"
    data_file.write_text("""
text: "Test"
""")

    result = runner.invoke(
        app,
        [
            "validate-data",
            str(data_file),
            "--schema",
            str(schema_file),
            "--cache-dir",
            str(cache_dir),
            "--verbose",
        ],
    )

    assert result.exit_code == 0


def test_validate_text_file_command(tmp_path):
    """Test validate text-file command with OBO-style file."""
    # Create a simple test file with regex-extractable content
    test_file = tmp_path / "test.obo"
    test_file.write_text('''
[Term]
id: GO:0000001
name: test term 1
def: "Definition without supporting text" [PMID:12345678]

[Term]
id: GO:0000002
name: test term 2
def: "Definition with supporting text" [PMID:23456789] {ex:supporting_text="some test text[PMID:23456789]"}
''')

    # Run command (it will fail to fetch real references, but we're testing extraction)
    result = runner.invoke(
        app,
        [
            "validate",
            "text-file",
            str(test_file),
            "--regex",
            r'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"',
            "--text-group",
            "1",
            "--ref-group",
            "2",
        ],
    )

    # Check that extraction worked
    assert "Found 1 match" in result.stdout
    assert "some test text" in result.stdout or "PMID:23456789" in result.stdout


def test_validate_text_file_no_matches(tmp_path):
    """Test validate text-file command with file that has no matches."""
    test_file = tmp_path / "test.txt"
    test_file.write_text('''
This is a plain text file.
It has no matches for the regex pattern.
Just regular text here.
''')

    result = runner.invoke(
        app,
        [
            "validate",
            "text-file",
            str(test_file),
            "--regex",
            r'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"',
        ],
    )

    assert result.exit_code == 0
    assert "No matches found" in result.stdout


def test_validate_text_file_summary_mode(tmp_path, cli_cache_dir):
    """Test validate text-file command with summary flag."""
    test_file = tmp_path / "test.txt"
    # Use TEST001 which exists in fixtures
    test_file.write_text('line 1: text="Protein X functions in cell cycle" ref=PMID:TEST001\n')

    result = runner.invoke(
        app,
        [
            "validate",
            "text-file",
            str(test_file),
            "--regex",
            r'text="([^"]+)" ref=(\S+)',
            "--summary",
            "--cache-dir",
            str(cli_cache_dir),
        ],
    )

    # Summary mode should show counts but not individual lines
    assert "Validation Summary" in result.stdout
    assert "Total validations" in result.stdout
