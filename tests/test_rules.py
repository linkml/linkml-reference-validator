"""Every publisher rule in ``etl.rules`` has examples, and the code honours them.

The examples live in ``etl/rules.py`` beside their rules. This file only runs
them, through the code that consumes each rule rather than the rule alone, so
an example that passes here passes where it matters.
"""

import pytest
from bs4 import BeautifulSoup

from linkml_reference_validator.etl import rules
from linkml_reference_validator.etl.extract import html, pdf, xml
from linkml_reference_validator.etl.extract.pdf import clean_pdf_title
from linkml_reference_validator.etl.extract.xml import is_stub_notice
from linkml_reference_validator.etl.fulltext import pmc
from linkml_reference_validator.etl.fulltext.pmc import find_pmc_article_body
from linkml_reference_validator.etl.sources import url
from linkml_reference_validator.etl.sources.url import URLSource

#: Stands in for ``{body}`` in markup examples: long enough to be an article.
BODY = "<p>" + ("Real article prose. " * 40) + "</p>"


# --- every rule has an example ---------------------------------------------


@pytest.mark.parametrize(
    "rule_names,examples",
    [
        (set(rules.LANDING_PAGE_RULES), rules.LANDING_PAGE_EXAMPLES),
        (set(rules.ARTICLE_BODY_SELECTORS), rules.ARTICLE_BODY_EXAMPLES),
        (set(rules.PMC_ARTICLE_BODY_CLASSES), rules.PMC_ARTICLE_BODY_EXAMPLES),
        (set(rules.STUB_NOTICE_PHRASES), rules.STUB_NOTICE_EXAMPLES),
    ],
    ids=["landing-page", "article-body", "pmc-article-body", "stub-notice"],
)
def test_every_rule_has_an_example(rule_names, examples):
    assert set(examples) == rule_names
    assert all(examples.values())


def test_placeholder_titles_have_examples():
    assert rules.PDF_PLACEHOLDER_TITLE_EXAMPLES
    assert rules.PDF_PLACEHOLDER_TITLE_COUNTEREXAMPLES


# --- consumers use the rules, not copies ------------------------------------


def test_consumers_import_the_rules():
    assert url.LANDING_PAGE_RULES is rules.LANDING_PAGE_RULES
    assert pdf.PDF_PLACEHOLDER_TITLE is rules.PDF_PLACEHOLDER_TITLE
    assert pmc.PMC_ARTICLE_BODY_CLASSES is rules.PMC_ARTICLE_BODY_CLASSES
    assert xml.STUB_NOTICE_PHRASES is rules.STUB_NOTICE_PHRASES
    assert html.ARTICLE_BODY_SELECTOR == ", ".join(rules.ARTICLE_BODY_SELECTORS)


# --- landing pages -----------------------------------------------------------


@pytest.mark.parametrize(
    "pdf_url,landing",
    [pair for pairs in rules.LANDING_PAGE_EXAMPLES.values() for pair in pairs],
)
def test_landing_page_example(pdf_url, landing):
    assert URLSource._landing_page_url(pdf_url) == landing


@pytest.mark.parametrize("pdf_url", rules.LANDING_PAGE_COUNTEREXAMPLES)
def test_landing_page_counterexample(pdf_url):
    assert URLSource._landing_page_url(pdf_url) is None


# --- placeholder PDF titles -------------------------------------------------


@pytest.mark.parametrize("title", rules.PDF_PLACEHOLDER_TITLE_EXAMPLES)
def test_placeholder_title_example(title):
    assert clean_pdf_title(title) is None


@pytest.mark.parametrize("title", rules.PDF_PLACEHOLDER_TITLE_COUNTEREXAMPLES)
def test_placeholder_title_counterexample(title):
    assert clean_pdf_title(title) == title


# --- article body containers ------------------------------------------------


@pytest.mark.parametrize("selector,markup", sorted(rules.ARTICLE_BODY_EXAMPLES.items()))
def test_article_body_example(selector, markup):
    soup = BeautifulSoup(markup.format(body=BODY), "html.parser")
    assert soup.select_one(html.ARTICLE_BODY_SELECTOR) is not None, selector


@pytest.mark.parametrize("markup", rules.ARTICLE_BODY_COUNTEREXAMPLES)
def test_article_body_counterexample(markup):
    soup = BeautifulSoup(markup.format(body=BODY), "html.parser")
    assert soup.select_one(html.ARTICLE_BODY_SELECTOR) is None


# --- PMC article containers --------------------------------------------------


@pytest.mark.parametrize(
    "markup",
    [m for examples in rules.PMC_ARTICLE_BODY_EXAMPLES.values() for m in examples],
)
def test_pmc_article_body_example(markup):
    soup = BeautifulSoup(markup.format(body=BODY), "html.parser")
    assert find_pmc_article_body(soup) is not None


@pytest.mark.parametrize("markup", rules.PMC_ARTICLE_BODY_COUNTEREXAMPLES)
def test_pmc_article_body_counterexample(markup):
    soup = BeautifulSoup(markup.format(body=BODY), "html.parser")
    assert find_pmc_article_body(soup) is None


# --- PMC placeholder notices --------------------------------------------------


@pytest.mark.parametrize(
    "phrase,notice",
    [(p, n) for p, notices in rules.STUB_NOTICE_EXAMPLES.items() for n in notices],
)
def test_stub_notice_example(phrase, notice):
    assert phrase in notice.lower(), "an example must show the phrase it is filed under"
    assert is_stub_notice(notice)
