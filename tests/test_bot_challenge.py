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
    URL_SOURCE_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.etl.rules import is_bot_challenge_title
from linkml_reference_validator.etl.sources.url import URLSource
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

URL = "https://www.ncbi.nlm.nih.gov/books/NBK1233/"
TITLE = "MELAS - GeneReviews® - NCBI Bookshelf"
BODY_TEXT = "MELAS is a multisystem disorder with onset typically in childhood."
CHALLENGE_TITLE = "Checking your browser - reCAPTCHA"
CHALLENGE = (
    f"<!DOCTYPE html><html><head><title>{CHALLENGE_TITLE}</title>"
    "</head><body><p>Checking your browser before accessing the site.</p></body></html>"
)
ARTICLE = f"<html><head><title>{TITLE}</title></head><body><p>{BODY_TEXT}</p></body></html>"


def _entry(*, title: str = TITLE, body: str = BODY_TEXT, url_version: int | None = None) -> str:
    """A url: cache entry. Unstamped (``url_version=None``) means stale."""
    lines = [
        "---",
        f"reference_id: url:{URL}",
        f"title: {title}",
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}",
    ]
    if url_version is not None:
        lines.append(f"url_source_version: {url_version}")
    lines += ["content_type: url", "---", "", "## Content", "", body]
    return "\n".join(lines)


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(cache_dir=tmp_path, rate_limit_delay=0.0)


@pytest.fixture
def fetcher(config):
    return ReferenceFetcher(config)


@pytest.fixture
def cache_path(fetcher):
    path = fetcher.get_cache_path(f"url:{URL}")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture
def stale_entry(cache_path):
    """A good entry written before ``url_source_version``, so it is stale."""
    cache_path.write_text(_entry())
    assert ReferenceFetcher._is_stale_cache_entry(cache_path.read_text())
    return cache_path


@pytest.fixture
def poisoned_entry(cache_path):
    """A challenge page cached by version 2, before this fix: stamped current."""
    cache_path.write_text(
        _entry(title=CHALLENGE_TITLE, body="Checking your browser", url_version=2)
    )
    assert URL_SOURCE_CACHE_VERSION == 2
    assert not ReferenceFetcher._is_stale_cache_entry(cache_path.read_text())
    return cache_path


def _serving(page: str, content_type: str = "text/html"):
    """Patch the network so every url: fetch gets ``page``."""
    acquirer = patch("linkml_reference_validator.etl.sources.url.ContentAcquirer")
    mock = acquirer.start()
    mock.return_value.fetch_bytes.return_value = (page.encode(), content_type)
    return acquirer


@pytest.fixture
def challenged():
    acquirer = _serving(CHALLENGE)
    yield
    acquirer.stop()


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


@pytest.mark.parametrize("content_type", ["text/html", "text/plain", ""])
def test_source_declines_a_challenge_page(content_type):
    """Checked before the HTML sniff, so a mislabelled challenge is caught too."""
    acquirer = _serving(CHALLENGE, content_type)
    result = URLSource().fetch(URL, ReferenceValidationConfig(rate_limit_delay=0.0))
    acquirer.stop()
    assert result is None


def test_source_keys_on_the_title_tag_not_the_body():
    """An article that merely talks about reCAPTCHA is still an article."""
    page = (
        "<html><head><title>Usability of reCAPTCHA for older adults</title></head>"
        "<body><p>Checking your browser is a phrase users find confusing.</p></body></html>"
    )
    acquirer = _serving(page)
    result = URLSource().fetch(URL, ReferenceValidationConfig(rate_limit_delay=0.0))
    acquirer.stop()
    assert result is not None
    assert result.title == "Usability of reCAPTCHA for older adults"


# --- the fetcher -------------------------------------------------------------


def test_stale_entry_is_served_and_kept(fetcher, stale_entry, challenged):
    before = stale_entry.read_text()
    outcome = fetcher.fetch_with_provenance(f"url:{URL}")

    assert outcome.content is not None
    assert outcome.content.title == TITLE
    assert BODY_TEXT in outcome.content.content
    assert outcome.served_stale
    assert stale_entry.read_text() == before


def test_forced_refresh_returns_nothing_and_keeps_the_entry(fetcher, stale_entry, challenged):
    """``cache fetch --force`` while challenged: a failure, and no damage."""
    before = stale_entry.read_text()
    assert fetcher.fetch(f"url:{URL}", force_refresh=True) is None
    assert stale_entry.read_text() == before


def test_nothing_is_cached_when_there_was_no_entry(fetcher, tmp_path, challenged):
    """The ``cache fetch`` case: report failure rather than write the challenge."""
    assert fetcher.fetch(f"url:{URL}") is None
    assert not list(tmp_path.rglob("*.md"))


@pytest.mark.parametrize("trusted", [False, True])
def test_a_cached_challenge_page_is_absent(tmp_path, poisoned_entry, trusted):
    """Stamped current, so staleness never caught it; trust must not serve it."""
    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=tmp_path, rate_limit_delay=0.0, trust_cached_entries=trusted
        )
    )
    assert fetcher._load_from_disk(f"url:{URL}") is None
    assert fetcher._load_from_disk(f"url:{URL}", allow_stale=True, allow_stale_html=True) is None


def test_a_cached_challenge_page_is_replaced_by_the_next_good_fetch(fetcher, poisoned_entry):
    acquirer = _serving(ARTICLE)
    result = fetcher.fetch(f"url:{URL}")
    acquirer.stop()

    assert result is not None
    assert result.title == TITLE
    assert f"title: {TITLE}" in poisoned_entry.read_text()


def test_a_cached_challenge_page_is_not_served_while_still_challenged(
    fetcher, poisoned_entry, challenged
):
    assert fetcher.fetch(f"url:{URL}") is None


# --- the validator -----------------------------------------------------------


def test_curated_title_is_compared_against_the_cached_one(config, stale_entry, challenged):
    validator = SupportingTextValidator(config)
    result = validator.validate("onset typically in childhood", f"url:{URL}", expected_title=TITLE)
    title_result = validator.validate_title(f"url:{URL}", expected_title=TITLE)

    assert result.is_valid, result.message
    assert title_result.is_valid, title_result.message


def test_a_cached_challenge_page_is_never_a_title_mismatch(config, poisoned_entry, challenged):
    """Unfetchable is the honest answer; blaming the curated title is not."""
    validator = SupportingTextValidator(config)
    result = validator.validate("onset typically in childhood", f"url:{URL}", expected_title=TITLE)
    title_result = validator.validate_title(f"url:{URL}", expected_title=TITLE)

    for r in (result, title_result):
        assert not r.is_valid
        assert "Title mismatch" not in r.message
        assert CHALLENGE_TITLE not in r.message
