"""A bot-challenge page is a failed fetch, not a document (#117).

NCBI answers a rate-limited ``url:`` fetch with "Checking your browser -
reCAPTCHA" on an HTTP 200, so no status check sees it. Before this, URLSource
returned the page as the reference: its title was compared against the curated
one and reported as a curation error, and the page replaced a good cache entry.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from linkml_reference_validator.etl import rules
from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.etl.sources.url import URLSource, is_bot_challenge_title
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

URL = "https://www.ncbi.nlm.nih.gov/books/NBK1233/"
TITLE = "MELAS - GeneReviews® - NCBI Bookshelf"
BODY_TEXT = "MELAS is a multisystem disorder with onset typically in childhood."
CHALLENGE = (
    "<!DOCTYPE html><html><head><title>Checking your browser - reCAPTCHA</title>"
    "</head><body><p>Checking your browser before accessing the site.</p></body></html>"
)


def _unstamped_entry() -> str:
    """A good cache entry written before ``url_source_version``, so it is stale."""
    return "\n".join(
        [
            "---",
            f"reference_id: url:{URL}",
            f"title: {TITLE}",
            f"extractor_version: {EXTRACTOR_CACHE_VERSION}",
            "content_type: url",
            "---",
            "",
            "## Content",
            "",
            BODY_TEXT,
        ]
    )


@pytest.fixture
def fetcher(tmp_path):
    return ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path, rate_limit_delay=0.0))


@pytest.fixture
def stale_entry(fetcher):
    path = fetcher.get_cache_path(f"url:{URL}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_unstamped_entry())
    assert ReferenceFetcher._is_stale_cache_entry(path.read_text())
    return path


def _challenged():
    """Patch the network so every url: fetch gets the challenge page."""
    mock = patch("linkml_reference_validator.etl.sources.url.ContentAcquirer")
    acquirer = mock.start()
    acquirer.return_value.fetch_bytes.return_value = (CHALLENGE.encode(), "text/html")
    return mock


# --- the rule ----------------------------------------------------------------


@pytest.mark.parametrize("title", rules.BOT_CHALLENGE_TITLE_EXAMPLES)
def test_challenge_title_example(title):
    assert is_bot_challenge_title(title)


@pytest.mark.parametrize("title", rules.BOT_CHALLENGE_TITLE_COUNTEREXAMPLES)
def test_challenge_title_counterexample(title):
    assert not is_bot_challenge_title(title)


def test_no_title_is_not_a_challenge():
    assert not is_bot_challenge_title(None)
    assert not is_bot_challenge_title("")


# --- the source --------------------------------------------------------------


def test_source_declines_a_challenge_page():
    mock = _challenged()
    try:
        assert URLSource().fetch(URL, ReferenceValidationConfig(rate_limit_delay=0.0)) is None
    finally:
        mock.stop()


def test_source_keys_on_the_title_tag_not_the_body():
    """An article that merely talks about reCAPTCHA is still an article."""
    page = (
        "<html><head><title>Usability of reCAPTCHA for older adults</title></head>"
        "<body><p>Checking your browser is a phrase users find confusing.</p></body></html>"
    )
    with patch("linkml_reference_validator.etl.sources.url.ContentAcquirer") as MockAcquirer:
        MockAcquirer.return_value.fetch_bytes.return_value = (page.encode(), "text/html")
        result = URLSource().fetch(URL, ReferenceValidationConfig(rate_limit_delay=0.0))
    assert result is not None
    assert result.title == "Usability of reCAPTCHA for older adults"


# --- the fetcher -------------------------------------------------------------


def test_stale_entry_is_served_and_kept(fetcher, stale_entry):
    before = stale_entry.read_text()
    mock = _challenged()
    try:
        outcome = fetcher.fetch_with_provenance(f"url:{URL}")
    finally:
        mock.stop()

    assert outcome.content is not None
    assert outcome.content.title == TITLE
    assert BODY_TEXT in outcome.content.content
    assert outcome.served_stale
    assert stale_entry.read_text() == before


def test_nothing_is_cached_when_there_was_no_entry(fetcher, tmp_path):
    """The ``cache fetch`` case: report failure rather than write the challenge."""
    mock = _challenged()
    try:
        assert fetcher.fetch(f"url:{URL}") is None
    finally:
        mock.stop()
    assert not list(tmp_path.rglob("*.md"))


# --- the validator -----------------------------------------------------------


def test_curated_title_is_compared_against_the_cached_one(tmp_path, stale_entry):
    validator = SupportingTextValidator(
        ReferenceValidationConfig(cache_dir=tmp_path, rate_limit_delay=0.0)
    )
    mock = _challenged()
    try:
        result = validator.validate(
            "onset typically in childhood", f"url:{URL}", expected_title=TITLE
        )
        title_result = validator.validate_title(f"url:{URL}", expected_title=TITLE)
    finally:
        mock.stop()

    assert result.is_valid, result.message
    assert title_result.is_valid, title_result.message


def test_a_challenge_already_in_the_cache_is_named_as_one(tmp_path):
    """An entry poisoned before this fix must not read as the curator's mistake."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path, rate_limit_delay=0.0, trust_cached_entries=True
    )
    validator = SupportingTextValidator(config)
    path = validator.fetcher.get_cache_path(f"url:{URL}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _unstamped_entry().replace(TITLE, "Checking your browser - reCAPTCHA")
    )

    result = validator.validate("onset typically in childhood", f"url:{URL}", expected_title=TITLE)
    title_result = validator.validate_title(f"url:{URL}", expected_title=TITLE)

    for r in (result, title_result):
        assert not r.is_valid
        assert "bot-challenge page" in r.message
