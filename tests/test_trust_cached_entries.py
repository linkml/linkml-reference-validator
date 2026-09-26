"""A committed cache can be used as it is, without a re-fetch on every run.

Staleness re-fetching is right for a cache the tool owns and can rebuild. For a
cache that is committed and reviewed it inverts: the re-fetch is the risk, not
the repair. It can shorten a body (dismech#12879), replace an entry with a
bot-check page served on an HTTP 200 (dismech#12867), or withhold text that
nothing can recover (dismech#12672).

`trust_cached_entries` says use the file. Off by default, so caches still
migrate for consumers that want that.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceValidationConfig

BODY = "A sentence a curator quoted, present only in this cached body."


def _cache(tmp_path, content_type="full_text_html"):
    (tmp_path / "PMID_20301575.md").write_text(
        "---\nreference_id: PMID:20301575\ntitle: A paper\n"
        f"content_type: {content_type}\n---\n\n## Content\n\n{BODY}\n",
        encoding="utf-8",
    )


def _fetch(tmp_path, trust):
    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=tmp_path, email="me@example.org", trust_cached_entries=trust
        )
    )
    calls = []

    class _Source:
        def fetch(self, identifier, config):
            calls.append(identifier)
            return None

    with patch(
        "linkml_reference_validator.etl.reference_fetcher"
        ".ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        return fetcher.fetch("PMID:20301575"), calls


@pytest.mark.parametrize(
    "content_type", ["full_text_html", "full_text_xml", "abstract_only"]
)
def test_a_trusted_entry_is_served_without_any_fetch(tmp_path, content_type):
    """The point: no network call at all, so nothing can go wrong during one."""
    _cache(tmp_path, content_type)
    content, calls = _fetch(tmp_path, trust=True)

    assert content is not None, f"{content_type} should be served from disk"
    assert BODY in (content.content or "")
    assert calls == [], f"a trusted entry must not be re-fetched, got {calls}"


def test_the_file_is_left_exactly_as_it_was(tmp_path):
    """Nothing is rewritten, so a validation run leaves the cache untouched."""
    _cache(tmp_path)
    before = (tmp_path / "PMID_20301575.md").read_text(encoding="utf-8")
    _fetch(tmp_path, trust=True)
    assert (tmp_path / "PMID_20301575.md").read_text(encoding="utf-8") == before


def test_the_default_still_re_fetches(tmp_path):
    """Off by default: an unstamped entry is still treated as stale."""
    _cache(tmp_path)
    _content, calls = _fetch(tmp_path, trust=False)
    assert calls == ["20301575"], (
        "by default an unstamped entry is re-fetched; the flag must be opt-in"
    )
