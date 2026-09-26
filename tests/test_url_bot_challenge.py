"""A bot-check page is not a reference, and must not become one.

PMC answers a Python HTTP client with a challenge page carried on an HTTP 200,
so no status check sees it. ``URLSource`` took its ``<title>`` as the reference
title and its markup as the content, which surfaced downstream as

    [ERROR] Title mismatch: expected 'Pharmacotherapy for Alcohol Use Disorder…'
            but got 'Checking your browser'

on a pull request that cited a PMC article by URL (monarch-initiative/dismech#12867).
The cache had no entry, so validation fetched it live and compared a curated
title against a challenge page.

Treating it as a transient failure is the honest outcome: nothing about the
reference is known, and a retry from somewhere unblocked can still succeed.
Caching it records an interstitial as a paper.
"""

from __future__ import annotations

import pytest

from linkml_reference_validator.etl.sources.url import URLSource

CHALLENGE_PAGES = [
    pytest.param(
        "<html><head><title>Checking your browser before accessing</title></head>"
        "<body><p>Enable JavaScript and cookies to continue.</p></body></html>",
        id="pmc-checking-your-browser",
    ),
    pytest.param(
        "<html><head><title>Just a moment...</title></head>"
        "<body><div id='cf-challenge'>Verifying you are human.</div></body></html>",
        id="cloudflare-just-a-moment",
    ),
    pytest.param(
        "<html><head><title>Access denied</title></head>"
        "<body><p>We have detected unusual traffic from your network.</p></body></html>",
        id="unusual-traffic",
    ),
]


@pytest.mark.parametrize("html", CHALLENGE_PAGES)
def test_a_challenge_page_is_recognised(html):
    assert URLSource._is_bot_challenge(html) is True


@pytest.mark.parametrize(
    "html",
    [
        pytest.param(
            "<html><head><title>Pivotal Role of TLR4 Receptors - PMC</title></head>"
            "<body><section class='body main-article-body'><p>"
            + ("Real article prose. " * 40)
            + "</p></section></body></html>",
            id="real-pmc-article",
        ),
        pytest.param(
            "<html><head><title>A paper about human verification methods</title></head>"
            "<body><p>" + ("Prose discussing CAPTCHA research. " * 30) + "</p></body></html>",
            id="article-whose-subject-is-bot-detection",
        ),
        pytest.param("plain text, no markup at all", id="plain-text"),
    ],
)
def test_a_real_page_is_not_mistaken_for_a_challenge(html):
    """The check must not fire on an article that merely discusses the topic.

    A paper about CAPTCHAs contains the words; a challenge page is short and
    carries them in its title or as its whole body. Getting this backwards would
    discard real references.
    """
    assert URLSource._is_bot_challenge(html) is False
