"""PMC's current article markup must be recognised by the HTML fallback.

The fallback looked for ``div.article-body`` or ``div.tsec``. PMC serves neither
today: the article sits in ``<section class="body main-article-body">`` -- a
different element *and* a different class. So the path declined for every PMC
article, and the "retry when the source serves full text again to repair it"
advice printed when a stale ``full_text_html`` entry is withheld pointed at a
route that could never succeed (reported downstream as monarch-initiative/dismech#12672).

The structural test is what makes this fetch safe -- a bot-check interstitial
arrives on an HTTP 200 and carries no article container -- so widening the
selector must not widen it to something an interstitial or a navigation page
would satisfy.
"""

from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from linkml_reference_validator.etl.fulltext.pmc import find_pmc_article_body

BODY = "<p>" + ("Real article prose. " * 40) + "</p>"


@pytest.mark.parametrize(
    "markup,label",
    [
        (f'<section class="body main-article-body">{BODY}</section>', "current PMC"),
        (f'<div class="article-body">{BODY}</div>', "legacy div.article-body"),
        (f'<div class="tsec">{BODY}</div>', "legacy div.tsec"),
        (f'<section class="main-article-body">{BODY}</section>', "class without 'body'"),
    ],
)
def test_article_containers_are_found(markup, label):
    soup = BeautifulSoup(markup, "html.parser")
    assert find_pmc_article_body(soup) is not None, f"{label} should be recognised"


@pytest.mark.parametrize(
    "markup,label",
    [
        ("<html><body><p>Checking your browser before accessing.</p></body></html>",
         "bot-check interstitial"),
        ("<html><body><nav><a href='/'>Home</a></nav></body></html>", "navigation page"),
        ("<html><body><div class='usa-banner'>An official website</div></body></html>",
         "banner chrome only"),
    ],
)
def test_pages_without_an_article_container_are_declined(markup, label):
    soup = BeautifulSoup(markup, "html.parser")
    assert find_pmc_article_body(soup) is None, f"{label} must not be accepted"


def test_a_bare_body_element_is_not_an_article_container():
    """``<body>`` is on every page, so matching class="body" alone would accept
    an interstitial. Only the article-body classes count."""
    soup = BeautifulSoup(f"<html><body>{BODY}</body></html>", "html.parser")
    assert find_pmc_article_body(soup) is None


def test_a_challenge_page_carrying_a_classed_body_is_still_declined():
    """The interstitial arrives on an HTTP 200, so this selector is the only check.

    PMC's challenge page carries a classed ``<body>``. None of its classes may
    overlap the article-body list, or a bot-check page gets cached as full text.
    """
    markup = (
        '<html><body class="usa-page bot-check">'
        "<h1>Checking your browser before accessing</h1>"
        "<p>Enable JavaScript and cookies to continue.</p>"
        "</body></html>"
    )
    soup = BeautifulSoup(markup, "html.parser")
    assert find_pmc_article_body(soup) is None
