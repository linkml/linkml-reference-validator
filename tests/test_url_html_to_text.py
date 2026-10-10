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

import pytest
from bs4 import BeautifulSoup, NavigableString  # type: ignore

from linkml_reference_validator.etl.extract.html import html_to_text, sanitize_html
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
