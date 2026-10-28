"""HTML article text keeps everything in the scope, not just its ``<p>`` text (issue #121).

``HTMLExtractor`` used to return only ``<p>`` text whenever a scope held any
``<p>``, so lists, tables, headings and bare ``<div>`` text were dropped and a
correct quote of them failed. Nested or unclosed ``<p>`` also repeated and
welded text. Every HTML full-text path (PMC, OpenAlex, downloaded HTML) goes
through this extractor, so these tests pin the shared behaviour.
"""

from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    HTML_FULL_TEXT_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator

MIXED = (
    b"<article><h2>Results</h2><p>We found three things.</p>"
    b"<ul><li>POLG variants cause ataxia</li></ul>"
    b"<table><tr><td>GENE1</td><td>0.05</td></tr></table>"
    b"<div>Unwrapped finding text.</div></article>"
)


def test_text_outside_paragraphs_is_kept():
    """Headings, list items, table cells and bare div text all reach the output."""
    text = HTMLExtractor().extract(MIXED) or ""
    for expected in (
        "Results",
        "We found three things.",
        "POLG variants cause ataxia",
        "GENE1",
        "0.05",
        "Unwrapped finding text.",
    ):
        assert expected in text


def test_blocks_stay_on_separate_lines():
    """A block never welds onto its neighbour."""
    text = HTMLExtractor().extract(MIXED) or ""
    assert "things.POLG" not in text
    assert "ataxiaGENE1" not in text


def test_unclosed_paragraphs_are_neither_repeated_nor_welded():
    """html.parser nests unclosed ``<p>``; each paragraph still appears once, on its own."""
    text = HTMLExtractor().extract(b"<article><p>Para one<p>Para two</article>") or ""
    assert text.count("Para two") == 1
    assert "Para onePara" not in text


def test_blocks_inside_a_paragraph_are_separated():
    """A ``<div>`` inside a ``<p>`` starts a new line instead of welding."""
    text = HTMLExtractor().extract(
        b"<article><p>Intro<div>block A</div><div>block B</div></p></article>"
    ) or ""
    assert "Introblock" not in text
    assert "block Ablock" not in text
    assert all(part in text for part in ("Intro", "block A", "block B"))


def test_inline_markup_keeps_its_spacing():
    """The fix that motivated the old shortcut still holds: italics do not weld."""
    text = HTMLExtractor().extract(
        b"<article><p>near (<i>GUSB</i>, <i>GRN</i>, and <i>NEU1</i>) here</p></article>"
    )
    assert text == "near (GUSB, GRN, and NEU1) here"


def test_a_list_item_quote_validates():
    """End to end: a correct quote of a list item is found in the extracted text."""
    text = HTMLExtractor().extract(MIXED) or ""
    reference = ReferenceContent(reference_id="PMID:1", content=text)
    match = SupportingTextValidator(ReferenceValidationConfig()).find_text_in_reference(
        "POLG variants cause ataxia", reference
    )
    assert match.found


def test_html_entries_from_the_paragraph_only_extractor_are_stale():
    """Cached HTML full text from before this fix is re-fetched, not served."""
    entry = (
        "---\n"
        "reference_id: PMID:1\n"
        "content_type: full_text_html\n"
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}\n"
        f"html_full_text_version: {HTML_FULL_TEXT_CACHE_VERSION - 1}\n"
        "---\nBody."
    )
    assert HTML_FULL_TEXT_CACHE_VERSION >= 2
    assert ReferenceFetcher._is_stale_cache_entry(entry)


def _fetch_with_source_down(tmp_path, html_stamp: str):
    """Fetch a cached HTML entry while the source yields nothing (the stale fallback)."""
    from unittest.mock import patch

    (tmp_path / "PMID_30929739.md").write_text(
        "---\nreference_id: PMID:30929739\ntitle: A paper\n"
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}\n{html_stamp}"
        "content_type: full_text_html\n---\n\n## Content\n\nA body sentence.\n",
        encoding="utf-8",
    )
    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=tmp_path, email="me@example.org", fetch_full_text=False
        )
    )

    class _Source:
        def fetch(self, identifier, config):
            return None

    with patch(
        "linkml_reference_validator.etl.reference_fetcher"
        ".ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        return fetcher.fetch("PMID:30929739")


def test_verified_html_from_an_older_extractor_is_served_when_refresh_fails(tmp_path):
    """A version-1 entry is a checked article body, only incomplete: serve it stale.

    Withholding it would turn this extractor fix into lost evidence for every
    HTML entry that cannot be re-fetched, such as a PMC-only article (#95).
    """
    reference = _fetch_with_source_down(tmp_path, "html_full_text_version: 1\n")
    assert reference is not None
    assert "A body sentence." in (reference.content or "")


def test_unverified_html_is_still_withheld_when_refresh_fails(tmp_path):
    """An unstamped entry may be a landing page, so it is still not served."""
    assert _fetch_with_source_down(tmp_path, "") is None


CITED_TITLE = "Aspirin cures every known headache"


def _article_with(bibliography: str) -> bytes:
    return (
        "<article><h2>Results</h2><p>Our own finding about PTEN.</p>"
        f"{bibliography}</article>"
    ).encode()


def test_reference_list_entries_are_not_article_text():
    """A cited paper's title is not evidence for the citing article.

    The old ``<p>``-only shortcut dropped reference-list ``<li>`` entries by
    accident; keeping all text must not start matching quotes against them.
    """
    for bibliography in (
        f'<ol class="references"><li>Smith J. {CITED_TITLE}. 2001.</li></ol>',
        f'<section class="ref-list"><ul><li>{CITED_TITLE}</li></ul></section>',
        f'<div role="doc-bibliography"><p>{CITED_TITLE}</p></div>',
        f'<ol class="c-article-references"><li>{CITED_TITLE}</li></ol>',
    ):
        text = HTMLExtractor().extract(_article_with(bibliography)) or ""
        assert "Our own finding about PTEN." in text
        assert CITED_TITLE not in text, bibliography


def test_pmc_path_drops_reference_list_and_noscript():
    """extract_scope, the PMC path, applies the same exclusions as extract."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        '<section class="body main-article-body"><p>Body text.</p>'
        "<ul><li>A list finding.</li></ul>"
        "<noscript>Please enable JavaScript</noscript>"
        f'<section class="ref-list"><ul><li>{CITED_TITLE}</li></ul></section>'
        "</section>",
        "html.parser",
    )
    text = HTMLExtractor().extract_scope(soup.section) or ""
    assert "Body text." in text and "A list finding." in text
    assert "enable JavaScript" not in text
    assert CITED_TITLE not in text


def test_verified_stamp_tolerates_a_yaml_comment():
    """The stamp is read the same whether or not a comment follows it."""
    assert ReferenceFetcher._is_verified_html_body(
        "---\nhtml_full_text_version: 1  # migrated\n---\nBody."
    )
