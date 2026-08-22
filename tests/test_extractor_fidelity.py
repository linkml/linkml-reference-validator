"""Tests for content extraction fidelity.

Two extractor bugs made the reference gate reject correctly curated snippets.
See https://github.com/monarch-initiative/genesets/issues/10

Bug 1 - over-aggressive stub detection: the XML extractor discarded any
document containing the word "restricted" anywhere in its raw markup. Morris
2019 (PMC6358485) is a 155 KB open-access paper whose Methods say the analysis
was "restricted to ... high quality HRC imputed variants", so the whole article
was thrown away and an 8.7 KB stub cached in its place, labelled as full text.

Bug 2 - markup stripping corrupts text: the HTML extractor called
``get_text(strip=True)`` with no separator, which strips each markup-delimited
run *before* joining. Text around italicised gene symbols lost its spaces, so
"(GUSB, GRN, and NEU1)" was extracted as "(GUSB,GRN, andNEU1)" and every
snippet spanning an italicised gene symbol failed to match.
"""

from unittest.mock import MagicMock, patch

import pytest

from linkml_reference_validator.etl.extract.html import HTMLExtractor
from linkml_reference_validator.etl.extract.xml import (
    MAX_STUB_NOTICE_CHARS,
    XMLExtractor,
    is_stub_notice,
)
from linkml_reference_validator.etl.sources.pmid import PMIDSource
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

# The sentence from Morris 2019 that used to discard the entire article.
MORRIS_METHODS_SENTENCE = (
    "The autosomal analysis was restricted to up to 13,977,204 high quality "
    "HRC imputed variants."
)

# A paragraph long enough that no length-based stub gate could mistake it for
# a placeholder, echoing a real article body.
LONG_BODY_FILLER = (
    "Bone mineral density was measured at the femoral neck and lumbar spine "
    "in each participating cohort using dual-energy X-ray absorptiometry, "
    "and association statistics were combined by fixed-effect meta-analysis "
    "across all contributing studies before genomic control correction. "
) * 6


def _jats(*paragraphs: str) -> bytes:
    """Build a minimal JATS article whose body holds the given paragraphs."""
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return f"<article><body><sec>{body}</sec></body></article>".encode()


@pytest.fixture
def validator(tmp_path):
    """Validator backed by an empty cache."""
    return SupportingTextValidator(
        ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)
    )


# ---------------------------------------------------------------------------
# Bug 1: stub detection must not discard real articles
# ---------------------------------------------------------------------------


def test_long_article_mentioning_restricted_is_kept():
    """The Morris 2019 regression: 'restricted' in Methods is not a stub marker."""
    xml = _jats(LONG_BODY_FILLER, MORRIS_METHODS_SENTENCE)

    text = XMLExtractor().extract(xml, content_type="application/xml")

    assert text is not None, (
        "A full article was discarded because its methods say 'restricted'"
    )
    assert MORRIS_METHODS_SENTENCE in text
    assert LONG_BODY_FILLER.strip() in text


def test_long_article_mentioning_cannot_be_obtained_is_kept():
    """The other blanket phrase is equally capable of appearing in real prose."""
    xml = _jats(
        LONG_BODY_FILLER,
        "Samples for which consent cannot be obtained were excluded from the analysis.",
    )

    text = XMLExtractor().extract(xml, content_type="application/xml")

    assert text is not None
    assert "consent cannot be obtained" in text


def test_restricted_in_reference_titles_does_not_discard_article():
    """The old check scanned raw markup, so even a cited title could kill an article."""
    xml = (
        "<article><body><sec><p>"
        + LONG_BODY_FILLER
        + "</p></sec></body>"
        + "<back><ref-list><ref><article-title>"
        + "Growth restricted infants and later disease"
        + "</article-title></ref></ref-list></back></article>"
    ).encode()

    text = XMLExtractor().extract(xml, content_type="application/xml")

    assert text is not None
    assert LONG_BODY_FILLER.strip() in text


def test_non_utf8_encoded_article_is_extracted():
    """An article declaring a non-UTF-8 encoding must not blow up extraction."""
    xml = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        "<article><body><sec><p>"
        + LONG_BODY_FILLER
        + "Fran\xe7ois measured the r\xe9sultats."
        + "</p></sec></body></article>"
    ).encode("iso-8859-1")

    text = XMLExtractor().extract(xml, content_type="application/xml")

    assert text is not None
    assert "François" in text


@pytest.mark.parametrize(
    "notice",
    [
        "The publisher of this article does not allow downloading of the full "
        "text in XML form from PMC.",
        "The full text of this article cannot be obtained from PMC.",
        "This article is not available from PMC.",
        "Access to the full text is restricted by the publisher.",
        # Wordings an exhaustive phrase list would miss; the length gate is
        # what lets a broad "restricted" catch them safely.
        "Access to this article is restricted.",
        "Full text is restricted.",
    ],
)
def test_short_stub_notice_is_rejected(notice):
    """Genuine PMC placeholder documents must still be discarded."""
    assert XMLExtractor().extract(_jats(notice), content_type="application/xml") is None


def test_is_stub_notice_requires_short_text():
    """A stub is short by definition; length is what makes the phrases safe."""
    notice = "The full text of this article cannot be obtained from PMC."

    assert is_stub_notice(notice) is True
    assert is_stub_notice(notice + " " + "x" * MAX_STUB_NOTICE_CHARS) is False


def test_is_stub_notice_ignores_ordinary_short_text():
    """Short text without a placeholder phrase is not a stub."""
    assert is_stub_notice("A brief note about the assay.") is False


def test_stub_detection_is_case_insensitive():
    """PMC's wording casing must not decide the outcome."""
    assert is_stub_notice("THIS ARTICLE IS NOT AVAILABLE FROM PMC.") is True


# ---------------------------------------------------------------------------
# Bug 1, second site: the PMID source had its own copy of the blanket check
# ---------------------------------------------------------------------------


@patch("linkml_reference_validator.etl.sources.pmid.Entrez.efetch")
def test_pmc_xml_fetch_keeps_article_mentioning_restricted(mock_efetch):
    """PMIDSource._fetch_pmc_xml duplicated the bug and must be fixed too."""
    handle = MagicMock()
    handle.read.return_value = _jats(
        LONG_BODY_FILLER, MORRIS_METHODS_SENTENCE
    ).decode()
    mock_efetch.return_value = handle

    text = PMIDSource()._fetch_pmc_xml(
        "6358485", ReferenceValidationConfig(rate_limit_delay=0.0)
    )

    assert text is not None, (
        "PMC XML fetch discarded a full article for saying 'restricted'"
    )
    assert MORRIS_METHODS_SENTENCE in text


@patch("linkml_reference_validator.etl.sources.pmid.Entrez.efetch")
def test_pmc_xml_fetch_still_rejects_stub(mock_efetch):
    """A real placeholder response is still recognised as having no full text."""
    handle = MagicMock()
    handle.read.return_value = _jats(
        "The publisher of this article does not allow downloading of the full "
        "text in XML form from PMC."
    ).decode()
    mock_efetch.return_value = handle

    text = PMIDSource()._fetch_pmc_xml(
        "1234567", ReferenceValidationConfig(rate_limit_delay=0.0)
    )

    assert text is None


@patch("linkml_reference_validator.etl.sources.pmid.Entrez.efetch")
def test_pmc_xml_fetch_preserves_accents_from_non_utf8_article(mock_efetch):
    """Entrez hands back str; an ISO-8859-1 declaration must not corrupt it.

    This is the production path. Re-encoding that str to UTF-8 leaves the
    declaration saying ISO-8859-1, and the parser believes the declaration -
    turning "François" into "FranÃ§ois" in author names and unit symbols.
    """
    handle = MagicMock()
    handle.read.return_value = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        "<article><body><sec><p>"
        + LONG_BODY_FILLER
        + "Fran\xe7ois measured the r\xe9sultats."
        + "</p></sec></body></article>"
    )
    mock_efetch.return_value = handle

    text = PMIDSource()._fetch_pmc_xml(
        "6358485", ReferenceValidationConfig(rate_limit_delay=0.0)
    )

    assert text is not None
    assert "François measured the résultats." in text
    assert "FranÃ§ois" not in text


@patch("linkml_reference_validator.etl.sources.pmid.Entrez.efetch")
def test_pmc_xml_fetch_accepts_bytes(mock_efetch):
    """Entrez may hand back bytes; extraction must cope either way."""
    handle = MagicMock()
    handle.read.return_value = _jats(LONG_BODY_FILLER)
    mock_efetch.return_value = handle

    text = PMIDSource()._fetch_pmc_xml(
        "6358485", ReferenceValidationConfig(rate_limit_delay=0.0)
    )

    assert text is not None
    assert LONG_BODY_FILLER.strip() in text


# ---------------------------------------------------------------------------
# Bug 2: markup must not eat the whitespace around it
# ---------------------------------------------------------------------------


def test_html_preserves_spaces_around_italic_gene_symbols():
    """The exact regression from the issue: italicised gene lists lost spaces."""
    html = (
        b"<html><body><p>Variants near three lysosomal genes "
        b"(<i>GUSB</i>, <i>GRN</i>, and <i>NEU1</i>) reached significance."
        b"</p></body></html>"
    )

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert "(GUSB, GRN, and NEU1)" in text
    assert "andNEU1" not in text
    assert "GUSB,GRN" not in text


def test_html_preserves_spaces_across_other_inline_markup():
    """Any inline markup, not just italics, must keep its surrounding spaces."""
    html = (
        b"<html><body><p>The <b>alpha</b> and <em>beta</em> subunits "
        b"of <span>the complex</span> were purified.</p></body></html>"
    )

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert "The alpha and beta subunits of the complex were purified." in text


def test_html_paragraphs_remain_separated():
    """Fixing the intra-paragraph spacing must not fuse separate paragraphs."""
    html = b"<html><body><p>First paragraph.</p><p>Second paragraph.</p></body></html>"

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert "First paragraph." in text
    assert "Second paragraph." in text
    assert "First paragraph.Second" not in text


def test_html_paragraph_text_is_trimmed():
    """Source indentation around a paragraph should not survive extraction."""
    html = b"<html><body><p>\n    Indented sentence.\n  </p></body></html>"

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert text == "Indented sentence."


def test_html_fallback_without_paragraphs_keeps_symbol_boundaries():
    """The no-<p> fallback must reproduce inline spacing exactly, like the <p> path.

    Asserted on the extracted string rather than through the matcher: the
    normalizer collapses whitespace and drops punctuation, so a matcher-based
    assertion passes even on corrupted text like "(\\nGUSB\\n,\\nGRN\\n)" and
    would not pin this behaviour at all.
    """
    html = (
        b"<html><body><div>Variants near "
        b"(<i>GUSB</i>, <i>GRN</i>, and <i>NEU1</i>) were found."
        b"</div></body></html>"
    )

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert text == "Variants near (GUSB, GRN, and NEU1) were found."


def test_html_fallback_separates_adjacent_block_elements():
    """Preserving inline spacing must not let neighbouring blocks run together."""
    html = b"<html><body><div>Introduction</div><div>The protein binds.</div></body></html>"

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert "IntroductionThe" not in text
    assert "Introduction" in text
    assert "The protein binds." in text


def test_html_fallback_separates_headings_and_list_items():
    """Headings and list items are block boundaries too."""
    html = b"<html><body><h1>Results</h1><ul><li>First</li><li>Second</li></ul></body></html>"

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert "ResultsFirst" not in text
    assert "FirstSecond" not in text


def test_html_fallback_treats_br_as_a_break():
    """A <br> is a line break, not a word boundary to be swallowed."""
    html = b"<html><body><div>Line one<br>Line two</div></body></html>"

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert "Line oneLine two" not in text
    assert "Line one" in text
    assert "Line two" in text


def test_html_paragraph_treats_br_as_a_break():
    """The same on the paragraph path, which is the one users hit most."""
    html = b"<html><body><p>Line one<br>Line two</p></body></html>"

    text = HTMLExtractor().extract(html, content_type="text/html")

    assert "Line oneLine two" not in text
    assert "Line one" in text
    assert "Line two" in text


def test_html_fallback_snippet_validates(validator):
    """End to end on the fallback path, as on the paragraph path."""
    html = (
        b"<html><body><div>Variants near "
        b"(<i>GUSB</i>, <i>GRN</i>, and <i>NEU1</i>) were found."
        b"</div></body></html>"
    )

    text = HTMLExtractor().extract(html, content_type="text/html")

    ref = ReferenceContent(reference_id="PMID:123", content=text)
    assert validator.find_text_in_reference("(GUSB, GRN, and NEU1)", ref).found is True


# ---------------------------------------------------------------------------
# End to end: the curated snippet the gate used to reject now validates
# ---------------------------------------------------------------------------


def test_curated_snippet_spanning_italics_validates(validator):
    """The user-visible outcome: a correct snippet is accepted, not rejected."""
    html = (
        b"<html><body><article><p>Three genes involved in lysosomal function "
        b"(<i>GUSB</i>, <i>GRN</i>, and <i>NEU1</i>) were implicated by the "
        b"Parkinson's disease GWAS.</p></article></body></html>"
    )
    content = HTMLExtractor().extract(html, content_type="text/html")
    ref = ReferenceContent(reference_id="PMID:123", content=content)

    match = validator.find_text_in_reference(
        "Three genes involved in lysosomal function (GUSB, GRN, and NEU1)", ref
    )

    assert match.found is True


def test_curated_snippet_in_restricted_mentioning_article_validates(validator):
    """Both bugs together: a real article, kept, and matched on a real snippet."""
    xml = _jats(LONG_BODY_FILLER, MORRIS_METHODS_SENTENCE)
    content = XMLExtractor().extract(xml, content_type="application/xml")
    ref = ReferenceContent(reference_id="PMID:30598549", content=content)

    match = validator.find_text_in_reference(
        "restricted to up to 13,977,204 high quality HRC imputed variants", ref
    )

    assert match.found is True


# ---------------------------------------------------------------------------
# The PMC full-text provider: the other call site for the same XML
#
# ReferenceFetcher resolves full text through the provider registry, so this
# path carries most PMC full text - more than PMIDSource._fetch_pmc_xml.
# ---------------------------------------------------------------------------


@patch("linkml_reference_validator.etl.fulltext.pmc.Entrez.efetch")
def test_pmc_provider_preserves_accents_from_non_utf8_article(mock_efetch):
    """The provider path must not re-encode either.

    Re-encoding the str Entrez returns leaves an ISO-8859-1 declaration in
    front of UTF-8 bytes, and the parser believes the declaration.
    """
    from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

    handle = MagicMock()
    handle.read.return_value = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        "<article><body><sec><p>"
        + LONG_BODY_FILLER
        + "Fran\xe7ois measured 5 \xb5g."
        + "</p></sec></body></article>"
    )
    mock_efetch.return_value = handle

    text = PMCFullTextProvider()._fetch_pmc_xml_source(
        "6358485", ReferenceValidationConfig(rate_limit_delay=0.0)
    )
    extracted = XMLExtractor().extract(text, content_type="application/xml")

    assert extracted is not None
    assert "François measured 5 µg." in extracted
    assert "FranÃ§ois" not in extracted
    assert "Âµ" not in extracted


def test_pmc_provider_html_preserves_inline_markup():
    """The provider's HTML fallback must get the shared extractor's fixes too.

    Pins <br> handling and inline-markup spacing on the paragraph branch; the
    no-paragraph fallback is covered separately by
    test_extract_scope_handles_a_region_without_paragraphs, since a fixture
    with <p> elements never reaches it.
    """
    from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider

    html = (
        b"<html><body><div class='article-body'>"
        b"<p>Variants near (<i>GUSB</i>, <i>GRN</i>) were found.</p>"
        b"<p>Line one<br>Line two</p>"
        b"</div></body></html>"
    )

    with patch(
        "linkml_reference_validator.etl.fulltext.pmc.requests.get"
    ) as mock_get:
        mock_get.return_value = MagicMock(status_code=200, content=html)
        text = PMCFullTextProvider()._fetch_pmc_html(
            "123", ReferenceValidationConfig(rate_limit_delay=0.0)
        )

    assert "(GUSB, GRN)" in text
    assert "Line oneLine two" not in text


def test_pmid_source_html_fallback_preserves_inline_markup():
    """PMIDSource's own HTML fallback carried the third copy of the same walk.

    It never had the welding bug, but it got none of this PR's other HTML
    work either, and it is live as the fallback in PMIDSource's full-text
    path. Like its sibling, this pins <br> handling and inline spacing on the
    paragraph branch, not the no-paragraph fallback.
    """
    html = (
        b"<html><body><div class='article-body'>"
        b"<p>Variants near (<i>GUSB</i>, <i>GRN</i>) were found.</p>"
        b"<p>Line one<br>Line two</p>"
        b"</div></body></html>"
    )

    with patch("linkml_reference_validator.etl.sources.pmid.requests.get") as mock_get:
        mock_get.return_value = MagicMock(status_code=200, content=html)
        text = PMIDSource()._fetch_pmc_html(
            "123", ReferenceValidationConfig(rate_limit_delay=0.0)
        )

    assert "(GUSB, GRN)" in text
    assert "Line oneLine two" not in text


# ---------------------------------------------------------------------------
# extract_scope: extracting from a region the caller already selected
# ---------------------------------------------------------------------------


def test_extract_scope_does_not_reselect_the_region():
    """A caller-chosen region must be used whole, not narrowed again.

    extract() picks <article>/<main> when given a whole document. Handing it a
    region the caller already selected re-ran that choice inside the region, so
    a nested <article> silently dropped everything around it.
    """
    from bs4 import BeautifulSoup

    region = BeautifulSoup(
        "<div class='article-body'>"
        "<p>Introductory paragraph outside the nested element.</p>"
        "<article><p>Nested article paragraph.</p></article>"
        "</div>",
        "html.parser",
    ).find("div")

    text = HTMLExtractor().extract_scope(region)

    assert "Introductory paragraph outside the nested element." in text
    assert "Nested article paragraph." in text


def test_extract_scope_matches_extract_for_a_plain_region():
    """The scope-taking entry point and the parsing one must agree."""
    from bs4 import BeautifulSoup

    markup = (
        "<div><script>JUNKSCRIPT</script><style>JUNKSTYLE</style>"
        "<p>Variants near (<i>GUSB</i>, <i>GRN</i>) were found.</p></div>"
    )
    region = BeautifulSoup(markup, "html.parser").find("div")

    assert HTMLExtractor().extract_scope(region) == HTMLExtractor().extract(markup)


def test_extract_scope_handles_a_region_without_paragraphs():
    """The block fallback runs for a region holding no <p> at all.

    Both PMC HTML fallbacks returned None for such a region before delegating;
    they now return its block-separated text. Recorded here because it changes
    what counts as full text.
    """
    from bs4 import BeautifulSoup

    region = BeautifulSoup(
        "<div class='article-body'><div>Introduction</div><div>The protein binds.</div></div>",
        "html.parser",
    ).find("div", class_="article-body")

    text = HTMLExtractor().extract_scope(region)

    assert "Introduction" in text
    assert "The protein binds." in text
    assert "IntroductionThe" not in text


def test_extract_scope_drops_script_and_style():
    """Script and style content must never reach cached full text.

    extract() decomposes them before selecting a region, but the three PMC
    paths enter at extract_scope instead. bs4's get_text() happens to skip
    Script/Stylesheet strings by default, so this held by luck of a library
    default rather than by anything this code did - pinned here, and made
    explicit in extract_scope, because a JSON-LD blob landing in a cached
    article would silently corrupt every snippet check against it.
    """
    from bs4 import BeautifulSoup

    region = BeautifulSoup(
        "<div class='article-body'>"
        '<script type="application/ld+json">{"headline":"JUNKSCRIPT"}</script>'
        "<style>.hidden{content:'JUNKSTYLE'}</style>"
        "<div>Variants near (<i>GUSB</i>, <i>GRN</i>) were found.</div>"
        "</div>",
        "html.parser",
    ).find("div", class_="article-body")

    text = HTMLExtractor().extract_scope(region)

    assert "JUNKSCRIPT" not in text
    assert "JUNKSTYLE" not in text
    assert "Variants near (GUSB, GRN) were found." in text


def test_extract_scope_is_idempotent():
    """Extraction must be repeatable on the same region.

    The block fallback marks boundaries by inserting newlines; doing that in
    the caller's tree meant a second call inserted a second separator after
    every block, so the text grew on each pass.
    """
    from bs4 import BeautifulSoup

    region = BeautifulSoup(
        "<div class='b'><div>One</div><div>Two</div></div>", "html.parser"
    ).find("div", class_="b")
    extractor = HTMLExtractor()

    first = extractor.extract_scope(region)

    assert extractor.extract_scope(region) == first
    assert extractor.extract_scope(region) == first


def test_extract_scope_leaves_the_caller_tree_alone():
    """A caller's parsed document must survive extraction unchanged.

    extract_scope takes a tag the caller owns and still holds a reference to,
    so stripping script/style and rewriting <br> in place would hand back a
    document the caller never asked to have edited.
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        "<div class='b'><script>JUNK</script><p>One<br>Two</p></div>", "html.parser"
    )
    before = str(soup)

    HTMLExtractor().extract_scope(soup.find("div", class_="b"))

    assert str(soup) == before
