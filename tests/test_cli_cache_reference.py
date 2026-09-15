"""Tests for the ``cache reference`` CLI command.

``cache reference`` exists to pre-populate the cache, so scripts gate on its
exit status. That makes "did this actually reach the source?" the question the
command has to answer, not "is there text for this reference?" - a stale entry
served during an outage is a failure to cache, however readable its text.
"""

import pytest
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
)

runner = CliRunner()


@pytest.fixture
def cache_dir(tmp_path):
    """An otherwise empty cache directory for the CLI to write into."""
    return tmp_path / "cache"


def _fetcher(cache_dir):
    return ReferenceFetcher(
        ReferenceValidationConfig(cache_dir=cache_dir, rate_limit_delay=0.0)
    )


def _write_stale_entry(cache_dir, reference_id="PMID:1", content="Stale body text."):
    """Leave a cache entry as an older extractor would have written it."""
    fetcher = _fetcher(cache_dir)
    fetcher._save_to_disk(
        ReferenceContent(reference_id=reference_id, content=content)
    )
    path = fetcher.get_cache_path(reference_id)
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            f"extractor_version: {EXTRACTOR_CACHE_VERSION}\n", ""
        ),
        encoding="utf-8",
    )
    return path


def _source_returning(mocker, content):
    """Patch the registry so every reference resolves to a source yielding ``content``."""
    return mocker.patch.object(
        ReferenceSourceRegistry,
        "get_source",
        return_value=mocker.Mock(
            return_value=mocker.Mock(fetch=mocker.Mock(return_value=content))
        ),
    )


def _run(cache_dir, *args):
    return runner.invoke(
        app, ["cache", "reference", *args, "--cache-dir", str(cache_dir)]
    )


def test_caching_a_reachable_reference_succeeds(cache_dir, mocker):
    """The ordinary case: the source answered and the entry was written."""
    _source_returning(
        mocker,
        ReferenceContent(
            reference_id="PMID:1",
            title="An Article",
            content="Freshly fetched text.",
            content_type="full_text",
        ),
    )

    result = _run(cache_dir, "PMID:1")

    assert result.exit_code == 0
    assert "Successfully cached PMID:1" in result.stdout
    assert f"extractor_version: {EXTRACTOR_CACHE_VERSION}" in _fetcher(
        cache_dir
    ).get_cache_path("PMID:1").read_text(encoding="utf-8")


def test_unreachable_source_with_a_stale_entry_reports_failure(cache_dir, mocker):
    """Serving an out-of-date copy is not caching: nothing was downloaded."""
    _write_stale_entry(cache_dir)
    _source_returning(mocker, None)

    result = _run(cache_dir, "PMID:1")

    assert result.exit_code == 1
    assert "Successfully cached" not in result.stdout
    assert "Failed to cache PMID:1" in result.stdout
    assert "out-of-date" in result.stdout


def test_unreachable_source_with_a_stale_entry_writes_nothing(cache_dir, mocker):
    """The entry stays stale, so a later reachable run still refreshes it."""
    path = _write_stale_entry(cache_dir)
    before = path.read_text(encoding="utf-8")
    _source_returning(mocker, None)

    _run(cache_dir, "PMID:1")

    assert path.read_text(encoding="utf-8") == before


def test_unreachable_source_with_no_entry_still_reports_failure(cache_dir, mocker):
    """The pre-existing failure path is unchanged."""
    _source_returning(mocker, None)

    result = _run(cache_dir, "PMID:1")

    assert result.exit_code == 1
    assert "Failed to fetch PMID:1" in result.stdout


def test_a_current_entry_is_reported_as_cached(cache_dir, mocker):
    """An entry this extractor wrote is already cached; no download is needed."""
    _fetcher(cache_dir)._save_to_disk(
        ReferenceContent(
            reference_id="PMID:1", content="Current body text.", content_type="full_text"
        )
    )
    _source_returning(mocker, None)

    result = _run(cache_dir, "PMID:1")

    assert result.exit_code == 0
    assert "Successfully cached PMID:1" in result.stdout
