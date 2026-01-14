"""Tests for lookup CLI command."""

import json

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from linkml_reference_validator.cli import app

runner = CliRunner()


@pytest.fixture
def cli_cache_dir(tmp_path, fixtures_dir):
    """Set up cache directory with test fixtures for CLI tests."""
    cache_dir = tmp_path / "cli_cache"
    cache_dir.mkdir()

    # Copy fixtures (both .txt and .md formats)
    for fixture_file in fixtures_dir.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    for fixture_file in fixtures_dir.glob("*.md"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    return cache_dir


class TestLookupCommand:
    """Tests for the top-level lookup command."""

    def test_lookup_default_markdown_format(self, cli_cache_dir):
        """Test lookup default output is markdown with frontmatter."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:TEST001",
                "--cache-dir",
                str(cli_cache_dir),
            ],
        )

        assert result.exit_code == 0
        # Default should be markdown with frontmatter
        assert "---" in result.stdout
        assert "reference_id: PMID:TEST001" in result.stdout
        assert "## Content" in result.stdout

    def test_lookup_json_format(self, cli_cache_dir):
        """Test lookup with JSON format."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:TEST001",
                "--cache-dir",
                str(cli_cache_dir),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        # Should be valid JSON
        data = json.loads(result.stdout)
        assert data["reference_id"] == "PMID:TEST001"
        assert "title" in data
        assert "content" in data

    def test_lookup_yaml_format(self, cli_cache_dir):
        """Test lookup with YAML format."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:TEST001",
                "--cache-dir",
                str(cli_cache_dir),
                "--format",
                "yaml",
            ],
        )

        assert result.exit_code == 0
        # Should be valid YAML
        yaml = YAML(typ="safe")
        data = yaml.load(result.stdout)
        assert data["reference_id"] == "PMID:TEST001"
        assert "title" in data

    def test_lookup_text_format(self, cli_cache_dir):
        """Test lookup with pretty text format."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:TEST001",
                "--cache-dir",
                str(cli_cache_dir),
                "--format",
                "text",
            ],
        )

        assert result.exit_code == 0
        # Should show formatted text
        assert "Reference:" in result.stdout or "PMID:TEST001" in result.stdout
        assert "Title:" in result.stdout

    def test_lookup_multiple_references(self, cli_cache_dir):
        """Test lookup with multiple reference IDs."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:TEST001",
                "PMID:TEST002",
                "--cache-dir",
                str(cli_cache_dir),
            ],
        )

        assert result.exit_code == 0
        # Should show both references
        assert "PMID:TEST001" in result.stdout
        assert "PMID:TEST002" in result.stdout

    def test_lookup_multiple_json_format(self, cli_cache_dir):
        """Test lookup multiple references with JSON format."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:TEST001",
                "PMID:TEST002",
                "--cache-dir",
                str(cli_cache_dir),
                "--format",
                "json",
            ],
        )

        assert result.exit_code == 0
        # Should be valid JSON array
        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert len(data) == 2
        assert data[0]["reference_id"] == "PMID:TEST001"
        assert data[1]["reference_id"] == "PMID:TEST002"

    def test_lookup_missing_reference(self, tmp_path):
        """Test lookup for reference that can't be fetched."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:NONEXISTENT999",
                "--cache-dir",
                str(tmp_path),
            ],
        )

        # Should fail since reference doesn't exist and can't be fetched
        assert result.exit_code == 1

    def test_lookup_partial_failure(self, cli_cache_dir):
        """Test lookup with mix of valid and invalid references."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:TEST001",
                "PMID:NONEXISTENT999",
                "--cache-dir",
                str(cli_cache_dir),
            ],
        )

        # Should succeed if at least one reference found
        assert result.exit_code == 0
        # Should show the found reference
        assert "PMID:TEST001" in result.stdout
        # Error for missing reference should be in stderr
        assert "Could not fetch" in result.output

    def test_lookup_with_no_cache(self, cli_cache_dir):
        """Test lookup with --no-cache bypasses cache."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMID:NONEXISTENT999",
                "--cache-dir",
                str(cli_cache_dir),
                "--no-cache",
            ],
        )

        # Should fail since reference can't be fetched from source
        assert result.exit_code == 1

    def test_lookup_normalizes_reference_id(self, cli_cache_dir):
        """Test lookup normalizes reference IDs (lowercase pmid to PMID)."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "pmid:TEST001",  # lowercase prefix
                "--cache-dir",
                str(cli_cache_dir),
            ],
        )

        assert result.exit_code == 0
        assert "PMID:TEST001" in result.stdout

    def test_lookup_pmc_reference(self, cli_cache_dir):
        """Test lookup works with PMC references."""
        result = runner.invoke(
            app,
            [
                "lookup",
                "PMC:TEST001",
                "--cache-dir",
                str(cli_cache_dir),
            ],
        )

        assert result.exit_code == 0


class TestCacheLookupCommand:
    """Tests for the cache lookup subcommand (path lookup)."""

    def test_cache_lookup_returns_path(self, cli_cache_dir):
        """Test cache lookup returns path to cached file."""
        result = runner.invoke(
            app,
            [
                "cache",
                "lookup",
                "PMID:TEST001",
                "--cache-dir",
                str(cli_cache_dir),
            ],
        )

        assert result.exit_code == 0
        assert "PMID_TEST001.md" in result.stdout

    def test_cache_lookup_missing_reference(self, tmp_path):
        """Test cache lookup for reference not in cache."""
        result = runner.invoke(
            app,
            [
                "cache",
                "lookup",
                "PMID:NONEXISTENT999",
                "--cache-dir",
                str(tmp_path),
            ],
        )

        assert result.exit_code == 1
        assert "not cached" in result.stdout.lower()
