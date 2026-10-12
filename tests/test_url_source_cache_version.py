"""``url:`` entries cached before the URLSource fixes must be re-fetched.

Sanitizing HTML (#92) and recovering PDF titles (#93) change what URLSource
writes, and neither rewrites what it already wrote: raw page scripts and
URL-as-title entries carry the current ``extractor_version`` and would be
served forever. ``url_source_version`` is their own staleness stamp, scoped
the way ``html_full_text_version`` is, so only ``url:`` entries pay the refresh.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
import requests

from linkml_reference_validator.etl.reference_fetcher import (
    ABSENT_CONTENT_CACHE_VERSION,
    EXTRACTOR_CACHE_VERSION,
    URL_SOURCE_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig

URL = "https://example.org/article/1"
RAW_PAGE = (
    '<html><head><title>Journal | Home</title></head><body>'
    '<script>var apiKey = "SECRET-KEY-123";</script>'
    "<p>Patients showed lactic acidosis.</p></body></html>"
)


def _entry(
    reference_id: str, content_type: str, *, url_version: int | None = None, body: str = ""
) -> str:
    """A cache entry current in every respect except the stamp a test varies."""
    lines = [
        "---",
        f"reference_id: {reference_id}",
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}",
    ]
    if url_version is not None:
        lines.append(f"url_source_version: {url_version}")
    if content_type == "unavailable":
        lines.append(f"absent_content_version: {ABSENT_CONTENT_CACHE_VERSION}")
    lines += [f"content_type: {content_type}", "---", "", "## Content", "", body]
    return "\n".join(lines)


@pytest.mark.parametrize("content_type", ["url", "full_text_pdf", "unavailable"])
def test_unstamped_url_entry_is_stale(content_type):
    assert ReferenceFetcher._is_stale_cache_entry(_entry(f"url:{URL}", content_type))


@pytest.mark.parametrize("content_type", ["url", "full_text_pdf", "unavailable"])
def test_current_url_entry_is_fresh(content_type):
    entry = _entry(f"url:{URL}", content_type, url_version=URL_SOURCE_CACHE_VERSION)
    assert not ReferenceFetcher._is_stale_cache_entry(entry)


def test_a_version_1_entry_is_stale():
    """Version 1 cached sanitized markup; version 2 caches readable text (#102)."""
    assert URL_SOURCE_CACHE_VERSION >= 2
    assert ReferenceFetcher._is_stale_cache_entry(_entry(f"url:{URL}", "url", url_version=1))


def test_a_newer_stamp_is_not_stale():
    entry = _entry(f"url:{URL}", "url", url_version=URL_SOURCE_CACHE_VERSION + 1)
    assert not ReferenceFetcher._is_stale_cache_entry(entry)


def test_other_sources_are_untouched():
    assert not ReferenceFetcher._is_stale_cache_entry(_entry("PMID:12345", "abstract_only"))


@pytest.fixture
def fetcher(tmp_path):
    return ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path, rate_limit_delay=0.0))


def test_a_fresh_fetch_is_stamped_and_round_trips(fetcher, tmp_path):
    with patch("linkml_reference_validator.etl.sources.url.ContentAcquirer") as MockAcquirer:
        MockAcquirer.return_value.fetch_bytes.return_value = (RAW_PAGE.encode(), "text/html")
        fetcher.fetch(f"url:{URL}")

    written = next(tmp_path.glob("*.md")).read_text()
    assert f"url_source_version: {URL_SOURCE_CACHE_VERSION}" in written
    assert not ReferenceFetcher._is_stale_cache_entry(written)

    reloaded = fetcher._load_from_disk(f"url:{URL}")
    assert reloaded is not None
    assert reloaded.metadata["url_source_version"] == URL_SOURCE_CACHE_VERSION


def test_only_a_fresh_fetch_is_certified(fetcher, tmp_path):
    """Saving a url: entry that URLSource did not just produce must not stamp it."""
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=f"url:{URL}", content_type="url", title="t", content=RAW_PAGE
        )
    )
    written = next(tmp_path.glob("*.md")).read_text()
    assert "url_source_version" not in written


def test_old_raw_entry_is_refetched_and_sanitized(fetcher):
    cache_path = fetcher.get_cache_path(f"url:{URL}")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(_entry(f"url:{URL}", "url", body=RAW_PAGE))

    with patch("linkml_reference_validator.etl.sources.url.ContentAcquirer") as MockAcquirer:
        MockAcquirer.return_value.fetch_bytes.return_value = (RAW_PAGE.encode(), "text/html")
        result = fetcher.fetch(f"url:{URL}")

    assert result is not None
    assert "SECRET-KEY-123" not in result.content
    assert "SECRET-KEY-123" not in cache_path.read_text()


@pytest.mark.parametrize(
    "unreachable",
    [
        (None, None),  # the acquirer's own refusal: non-200, or over the size cap
        requests.ConnectionError("network is unreachable"),  # really offline
        requests.Timeout("timed out"),
    ],
)
def test_old_raw_entry_is_still_served_when_offline(fetcher, unreachable):
    """Out of date is better than not found. It is not re-saved, so it stays stale.

    Every unstamped url: entry goes back to the network after this change, so
    the first offline run is where this has to hold.
    """
    cache_path = fetcher.get_cache_path(f"url:{URL}")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(_entry(f"url:{URL}", "url", body=RAW_PAGE))

    with patch("linkml_reference_validator.etl.sources.url.ContentAcquirer") as MockAcquirer:
        if isinstance(unreachable, Exception):
            MockAcquirer.return_value.fetch_bytes.side_effect = unreachable
        else:
            MockAcquirer.return_value.fetch_bytes.return_value = unreachable
        result = fetcher.fetch(f"url:{URL}")

    assert result is not None
    assert "lactic acidosis" in result.content
    assert ReferenceFetcher._is_stale_cache_entry(cache_path.read_text())
