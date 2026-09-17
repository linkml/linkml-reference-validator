"""Tests for the ``cache reference`` CLI command.

``cache reference`` exists to pre-populate the cache, so scripts gate on its
exit status. The question it has to answer is therefore whether the public
validation cache holds a current entry afterwards - not whether it reached the
source, since an entry this extractor already wrote may be reported as cached
without contacting anything, and not merely whether there is text for the
reference, since a stale entry served during an outage is text this version was
meant to replace.
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


def _write_stale_entry(
    cache_dir, reference_id="PMID:1", content="Stale body text.", content_type="unknown"
):
    """Leave a cache entry as an older extractor would have written it."""
    fetcher = _fetcher(cache_dir)
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=reference_id, content=content, content_type=content_type
        )
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
    """Invoke the command.

    Assertions below read ``result.output`` rather than ``result.stdout``: the
    failure messages go to stderr, and only ``output`` carries both streams on
    every click version (8.2 dropped CliRunner's ``mix_stderr``).
    """
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
    assert "Successfully cached PMID:1" in result.output
    assert f"extractor_version: {EXTRACTOR_CACHE_VERSION}" in _fetcher(
        cache_dir
    ).get_cache_path("PMID:1").read_text(encoding="utf-8")


def test_unreachable_source_with_a_stale_entry_reports_failure(cache_dir, mocker):
    """Serving an out-of-date copy is not caching: no current entry was left."""
    _write_stale_entry(cache_dir)
    _source_returning(mocker, None)

    result = _run(cache_dir, "PMID:1")

    assert result.exit_code == 1
    assert "Successfully cached" not in result.output
    assert "Failed to cache PMID:1" in result.output
    assert "out-of-date" in result.output


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
    assert "Failed to fetch PMID:1" in result.output


def test_an_unroutable_id_is_not_reported_as_an_unreachable_source(cache_dir, mocker):
    """No source handles the ID at all, which is not an outage.

    Both causes land in the same fallback, so the message has to cover both:
    "retry later" is the wrong advice for a typo'd prefix.
    """
    _write_stale_entry(cache_dir)
    mocker.patch.object(ReferenceSourceRegistry, "get_source", return_value=None)

    result = _run(cache_dir, "PMID:1")

    assert result.exit_code == 1
    assert "could not be re-fetched" in result.output
    assert "could not be reached" not in result.output


def test_forcing_a_refresh_against_a_stale_entry_reports_plain_failure(cache_dir, mocker):
    """An explicit refresh that failed reports failure, not a stale fallback.

    ``--force`` takes the other branch of the fallback, which returns no content
    at all rather than the out-of-date copy, so the plain message is the right one.
    """
    _write_stale_entry(cache_dir)
    _source_returning(mocker, None)

    result = _run(cache_dir, "PMID:1", "--force")

    assert result.exit_code == 1
    assert "Failed to fetch PMID:1" in result.output
    assert "out-of-date" not in result.output


def test_stale_html_full_text_is_not_even_offered_as_a_fallback(cache_dir, mocker):
    """The third outcome: refused as a fallback, so it reports plain failure.

    A stale ``full_text_html`` entry may be a repository landing page rather than
    an article, so the fetcher declines to serve it even when nothing else is
    available. Nothing is served, so nothing is served stale, and the command
    reports the ordinary fetch failure instead of the out-of-date message.
    """
    _write_stale_entry(cache_dir, content_type="full_text_html")
    _source_returning(mocker, None)

    result = _run(cache_dir, "PMID:1")

    assert result.exit_code == 1
    assert "Failed to fetch PMID:1" in result.output
    assert "out-of-date" not in result.output


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
    assert "Successfully cached PMID:1" in result.output
