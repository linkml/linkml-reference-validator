"""HTML fetched by ``URLSource`` is cached as readable text (issue #102).

Since #92 the cache held sanitized body markup. A quote could then only match
text inside one text node, so any sentence running through a link, bold or
emphasis failed, and a whole page sat on one unreadable line. Now the page is
flattened: inline tags are unwrapped in place, block-level tags become line
breaks, a table row becomes one line with its cells separated by `` | ``, and
``<pre>`` keeps its whitespace. Unlike :class:`HTMLExtractor`, nothing is
narrowed to ``<article>`` or to ``<p>`` text, so no text the sanitized markup
held is lost.
"""

from pathlib import Path
from unittest.mock import patch

import pytest
from bs4 import BeautifulSoup, NavigableString  # type: ignore

from linkml_reference_validator.etl.extract.html import html_to_text, sanitize_html
from linkml_reference_validator.etl.sources.url import URLSource
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

FIXTURES = Path(__file__).parent / "fixtures" / "fulltext_html"

FLINT = b"""<!DOCTYPE html><html><head><title>Flint | Patch</title></head><body>
<nav><ul><li><a href="/">Home</a></li><li><a href="/news">News</a></li></ul></nav>
<article>
  <h1>Flint Water Pollution Control Division Press Release</h1>
  <p>This press release was produced by <a href="https://cityofflint.com">the City of Flint</a>.
  The views expressed here are the author's own.</p>
</article>
<aside><p>Related: <b>Flint</b> news.</p></aside>
</body></html>
"""

WIKIPEDIA = (
    b"<html><body><div><p>The <b>Flint water crisis</b> was a public health crisis "
    b"that lasted from 2014 to 2019.</p></div></body></html>"
)

ZFIN = (
    b'<html><body><p>Data are licensed under a <a rel="license" '
    b'href="https://creativecommons.org/licenses/by/4.0/">Creative Commons '
    b"Attribution 4.0 International License</a>.</p></body></html>"
)

MIXED = b"""<html><body>
<h2>Findings</h2>
<p>Patients showed lactic acidosis.</p>
<ul><li>Seizures were frequent.</li><li>Ataxia was <em>progressive</em>.</li></ul>
<table>
  <tr><th>Gene</th><th colspan="2">Finding</th></tr>
  <tr><td rowspan="2">POLG</td><td>depletion</td><td>severe</td></tr>
</table>
<pre>x    y
  z</pre>
<footer>Copyright 2021 Example &amp; Co.</footer>
</body></html>
"""


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)


def _fetch(url, body, content_type, config):
    with patch("linkml_reference_validator.etl.sources.url.ContentAcquirer") as MockAcquirer:
        MockAcquirer.return_value.fetch_bytes.return_value = (body, content_type)
        return URLSource().fetch(url, config)


def _found(quote, reference, config):
    return SupportingTextValidator(config).find_text_in_reference(quote, reference).found


@pytest.mark.parametrize(
    "body, quote",
    [
        (FLINT, "This press release was produced by the City of Flint."),
        (WIKIPEDIA, "The Flint water crisis was a public health crisis"),
        (ZFIN, "licensed under a Creative Commons Attribution 4.0 International License"),
    ],
    ids=["flint-link", "wikipedia-bold", "zfin-link"],
)
def test_a_quote_through_inline_markup_matches(config, body, quote):
    reference = _fetch("https://example.org/page", body, "text/html", config)
    assert _found(quote, reference, config)


def test_the_cache_holds_no_markup(config):
    reference = _fetch("https://example.org/page", FLINT, "text/html", config)
    assert "<" not in reference.content
    assert "This press release was produced by the City of Flint." in reference.content


def test_text_outside_article_is_kept(config):
    """A generic page is not narrowed to its <article>, as HTMLExtractor would."""
    reference = _fetch("https://example.org/page", FLINT, "text/html", config)
    assert "Home" in reference.content
    assert "Related: Flint news." in reference.content


def test_title_still_comes_from_the_raw_page(config):
    body = b'<head><meta name="citation_title" content="Real Title"><title>T</title></head>'
    reference = _fetch("https://example.org/page", body + FLINT, "text/html", config)
    assert reference.title == "Real Title"


def test_list_and_table_text_is_kept_beside_paragraphs():
    """HTMLExtractor keeps only <p> text when a page has any; this must not."""
    text = html_to_text(MIXED.decode())
    for kept in ("Findings", "lactic acidosis", "Seizures were frequent.", "POLG", "severe"):
        assert kept in text


def test_each_block_is_its_own_line():
    lines = html_to_text(MIXED.decode()).splitlines()
    assert "Findings" in lines
    assert "Patients showed lactic acidosis." in lines
    assert "Seizures were frequent." in lines
    assert "Ataxia was progressive." in lines


def test_a_table_row_is_one_line_with_separated_cells():
    lines = html_to_text(MIXED.decode()).splitlines()
    assert "Gene | Finding" in lines
    assert "POLG | depletion | severe" in lines


def test_a_quote_copied_from_a_rendered_table_row_matches(config):
    reference = _fetch("https://example.org/page", MIXED, "text/html", config)
    assert _found("POLG depletion severe", reference, config)


def test_pre_keeps_its_whitespace():
    assert "x    y\n  z" in html_to_text(MIXED.decode())


def test_entities_are_unescaped():
    assert "Copyright 2021 Example & Co." in html_to_text(MIXED.decode()).splitlines()


def test_inline_neighbours_are_not_welded_or_split():
    text = html_to_text("<p>near (<i>GUSB</i>, <i>GRN</i>) here</p>")
    assert text == "near (GUSB, GRN) here"


def test_block_neighbours_are_not_welded():
    assert html_to_text("<div>one</div><div>two</div>") == "one\ntwo"
    assert html_to_text("lead<p>para</p>tail") == "lead\npara\ntail"


def test_br_breaks_a_line():
    assert html_to_text("<p>Line one<br>Line two</p>") == "Line one\nLine two"


def test_non_content_is_still_dropped():
    page = '<p>Text</p><script>var apiKey = "K";</script><!-- note --><noscript>N</noscript>'
    assert html_to_text(page) == "Text"


def _pages():
    pages = {"mixed": MIXED.decode(), "flint": FLINT.decode()}
    for path in sorted(FIXTURES.glob("*.html")):
        pages[path.name] = path.read_text()
    return pages


@pytest.mark.parametrize("name, page", sorted(_pages().items()), ids=sorted(_pages()))
def test_every_text_node_of_the_sanitized_markup_survives(name, page):
    """Every quote that matched the old cache, within one text node, still matches."""
    normalize = SupportingTextValidator.normalize_text
    flat = normalize(html_to_text(page))
    soup = BeautifulSoup(sanitize_html(page), "html.parser")
    # Exactly NavigableString: subclasses are doctypes and declarations, not text.
    for node in soup.find_all(string=lambda text: type(text) is NavigableString):
        expected = normalize(str(node))
        if expected:
            assert expected in flat, f"{name}: lost {expected!r}"
