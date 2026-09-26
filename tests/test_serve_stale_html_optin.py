"""A consumer with a reviewed, committed cache can opt into serving stale HTML.

Refusing stale ``full_text_html`` is right by default: a pre-fix entry may be a
publisher landing page, and #12009 found exactly that stored as full text. But
the refusal assumes the entry can be repaired by re-fetching, and for a
PMC-only article it cannot -- PMC answers a Python HTTP client with a bot-check
interstitial on an HTTP 200 regardless of headers, so the advertised repair route
is unreachable.

For a consumer whose cache is committed and reviewed, that turns a guard into
data loss: every snippet quoting the body of any pre-stamp HTML entry fails, on
files the pull request never touched (monarch-initiative/dismech#12672 --
1,654 such files, ~294 of them with a snippet that is not in the abstract).

``serve_stale_html_full_text`` lets that consumer say so explicitly. It changes
only what may be *served*; nothing about overwriting, and nothing by default.
"""

from __future__ import annotations

from unittest.mock import patch

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
)

BODY_SENTENCE = "A sentence that exists only in the article body."


def _cache(tmp_path):
    (tmp_path / "PMID_30929739.md").write_text(
        "---\nreference_id: PMID:30929739\ntitle: A paper\n"
        f"content_type: full_text_html\n---\n\n## Content\n\n{BODY_SENTENCE}\n",
        encoding="utf-8",
    )


def _fetch(tmp_path, **cfg):
    _cache(tmp_path)
    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=tmp_path, email="me@example.org", fetch_full_text=False, **cfg
        )
    )

    class _Source:
        def fetch(self, identifier, config):
            return None  # the source yields nothing: the stale-fallback path

    with patch(
        "linkml_reference_validator.etl.reference_fetcher"
        ".ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        return fetcher.fetch("PMID:30929739")


def test_stale_html_is_withheld_by_default(tmp_path):
    """The default must not change: an unrepaired entry is still not quotable."""
    assert _fetch(tmp_path) is None


def test_stale_html_is_served_when_the_consumer_opts_in(tmp_path):
    content = _fetch(tmp_path, serve_stale_html_full_text=True)
    assert content is not None, "opting in must make the cached body servable"
    assert BODY_SENTENCE in (content.content or "")


def test_opting_in_does_not_stamp_or_rewrite_the_entry(tmp_path):
    """Serving is not migrating. The entry stays stale so a later run retries."""
    _fetch(tmp_path, serve_stale_html_full_text=True)
    text = (tmp_path / "PMID_30929739.md").read_text(encoding="utf-8")
    assert "extractor_version" not in text
    assert BODY_SENTENCE in text


def _fetch_with_abstract_source(tmp_path, **cfg):
    """The path a refresh normally takes: the source answers, with an abstract.

    ``_stale_fallback`` needs the source to yield *nothing*. For a PMC-only
    article PubMed still returns the abstract, so the refresh reaches
    ``_preserve_cached_full_text`` instead: the overwrite is refused, and then a
    separate question decides what may be served. That second question is the
    one the flag has to answer, and it is the one dismech actually hits.
    """
    _cache(tmp_path)
    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=tmp_path, email="me@example.org", fetch_full_text=False, **cfg
        )
    )
    fresh = ReferenceContent(
        reference_id="PMID:30929739",
        content="Just the abstract.",
        content_type="abstract_only",
        title="A paper",
    )

    class _Source:
        def fetch(self, identifier, config):
            return fresh

    with patch(
        "linkml_reference_validator.etl.reference_fetcher"
        ".ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        return fetcher.fetch("PMID:30929739")


def test_refused_overwrite_serves_the_abstract_by_default(tmp_path):
    content = _fetch_with_abstract_source(tmp_path)
    assert content is not None
    assert BODY_SENTENCE not in (content.content or ""), (
        "by default the cached body stays withheld even though it was preserved"
    )
    assert "Just the abstract." in (content.content or "")


def test_refused_overwrite_serves_the_cached_body_when_opted_in(tmp_path):
    content = _fetch_with_abstract_source(tmp_path, serve_stale_html_full_text=True)
    assert content is not None
    assert BODY_SENTENCE in (content.content or "")


def test_refused_overwrite_leaves_the_file_alone_either_way(tmp_path):
    """Serving is not overwriting: the entry keeps its body and stays un-stamped."""
    for flag in (False, True):
        _fetch_with_abstract_source(tmp_path, serve_stale_html_full_text=flag)
        text = (tmp_path / "PMID_30929739.md").read_text(encoding="utf-8")
        assert BODY_SENTENCE in text, f"body lost with flag={flag}"
        assert "extractor_version" not in text, f"entry stamped with flag={flag}"
