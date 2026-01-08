"""Pytest configuration and fixtures."""

import pytest
from pathlib import Path
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher


@pytest.fixture
def fixtures_dir():
    """Get the test fixtures directory."""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def test_config(tmp_path, fixtures_dir):
    """Create a test configuration that uses fixtures directory as cache.

    This allows tests to use real cached references instead of mocks.
    """
    # Copy fixtures to temp cache directory
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    # Copy test fixtures to cache (both .txt and .md formats)
    for fixture_file in fixtures_dir.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    for fixture_file in fixtures_dir.glob("*.md"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())

    return ReferenceValidationConfig(
        cache_dir=cache_dir,
        rate_limit_delay=0.0,  # No delay for tests
    )


@pytest.fixture
def validator_with_fixtures(test_config):
    """Create a validator with real cached references."""
    return SupportingTextValidator(test_config)


@pytest.fixture
def fetcher_with_fixtures(test_config):
    """Create a fetcher with real cached references."""
    return ReferenceFetcher(test_config)
