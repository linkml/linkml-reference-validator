"""XMLExtractor body text: block separation, nesting and entities (#119, #120)."""

import pytest

from linkml_reference_validator.etl.extract.xml import XMLExtractor
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

PMC_DOCTYPE = (
    b'<!DOCTYPE pmc-articleset PUBLIC "-//NLM//DTD ARTICLE SET 2.0//EN" '
    b'"https://dtd.nlm.nih.gov/ncbi/pmc/articleset/nlm-articleset-2.0.dtd">'
)


def extract(body: bytes, prolog: bytes = b"") -> str:
    """Extract a minimal article wrapping ``body``, which must yield text."""
    text = XMLExtractor().extract(prolog + b"<article><body>" + body + b"</body></article>")
    assert text is not None
    return text


def quotable(quote: str, text: str) -> bool:
    """Whether the validator finds ``quote`` in extracted ``text``."""
    ref = ReferenceContent(reference_id="PMID:1", content=text)
    validator = SupportingTextValidator(ReferenceValidationConfig())
    return validator.find_text_in_reference(quote, ref).found


LIST_IN_PARAGRAPH = (
    b"<p>Intro text <list><list-item><p>alpha item</p></list-item>"
    b"<list-item><p>beta item</p></list-item></list> end.</p>"
)


def test_paragraph_inside_list_in_paragraph_is_emitted_once():
    """JATS lists live inside <p>; their item paragraphs must not repeat."""
    text = extract(LIST_IN_PARAGRAPH)
    assert text.count("alpha item") == 1
    assert text.count("beta item") == 1


def test_list_items_are_separated():
    """Adjacent list items must not weld into one token."""
    text = extract(LIST_IN_PARAGRAPH)
    assert "itembeta" not in text
    assert "alpha item beta item" in text


def test_list_items_without_inner_paragraphs_are_separated():
    """A <list-item> holding bare text is still a block."""
    text = extract(
        b"<p>Findings:<list><list-item>first</list-item><list-item>second</list-item></list></p>"
    )
    assert "firstsecond" not in text
    assert "first second" in text


def test_break_separates_lines():
    """<break/> is a line break, not nothing."""
    assert extract(b"<p>first line<break/>second line</p>") == "first line second line"


def test_inline_markup_stays_contiguous():
    """Inline elements must not gain spaces: H<sub>2</sub>O stays H2O."""
    assert extract(b"<p>Levels of H<sub>2</sub>O and <italic>BRCA</italic>1 rose.</p>") == (
        "Levels of H2O and BRCA1 rose."
    )


def test_sibling_paragraphs_still_separated():
    """Ordinary paragraphs remain blank-line separated."""
    assert extract(b"<sec><p>One.</p><p>Two.</p></sec>") == "One.\n\nTwo."


def test_figure_caption_inside_paragraph_once():
    """A <fig> inside <p> contributes its caption exactly once."""
    text = extract(
        b"<p>See figure.<fig><caption><p>Mice lacked PTEN.</p></caption></fig></p>"
    )
    assert text.count("Mice lacked PTEN.") == 1
    assert "figure.Mice" not in text


def test_table_inside_paragraph_is_not_repeated_in_prose():
    """A table-wrap inside <p> is rendered by the table pass, not the paragraph."""
    text = extract(
        b"<p>Results follow.<table-wrap><label>Table 1</label>"
        b"<table><tr><td>GENE1</td><td>0.05</td></tr></table></table-wrap></p>"
    )
    assert text.count("GENE1") == 1
    assert "| GENE1 | 0.05 |" in text


def test_list_quote_validates():
    """The motivating case: a quote spanning two list items validates."""
    assert quotable("alpha item beta item", extract(LIST_IN_PARAGRAPH))


@pytest.mark.parametrize(
    "markup,expected",
    [
        # Whitespace runs collapse to one space, as in table cells, so a
        # no-break space reads as the space a curator would type.
        (b"Hello&nbsp;world", "Hello world"),
        (b"A &mdash; B", "A \u2014 B"),
        (b"pages 3&ndash;5", "pages 3\u20135"),
        (b"&alpha;-synuclein", "\u03b1-synuclein"),
    ],
)
def test_html_named_entities_with_external_dtd(markup, expected):
    """PMC's external DTD is never loaded, so its named entities must not vanish."""
    assert extract(b"<p>" + markup + b"</p>", prolog=PMC_DOCTYPE) == expected


def test_named_entities_without_doctype():
    """Undeclared HTML entities are kept even with no DOCTYPE at all."""
    assert extract(b"<p>Hello&nbsp;world</p>") == "Hello world"


def test_nbsp_quote_validates():
    """A quote typed with a plain space matches text that had &nbsp;."""
    assert quotable("Hello world", extract(b"<p>Hello&nbsp;world</p>", prolog=PMC_DOCTYPE))


def test_xml_predefined_entities_unchanged():
    """&amp; &lt; &gt; &quot; &apos; keep their XML meaning."""
    assert extract(b"<p>A &amp; B &lt; C &gt; D &quot;E&quot; &apos;F&apos;</p>") == (
        "A & B < C > D \"E\" 'F'"
    )


def test_numeric_references_unchanged():
    """Numeric character references are already well defined."""
    assert extract(b"<p>5&#160;&#x3BC;M</p>") == "5 \u03bcM"


def test_internal_entity_declaration_keeps_document():
    """An internal DTD subset declaring an entity must not drop the body."""
    text = XMLExtractor().extract(
        b'<?xml version="1.0"?><!DOCTYPE article [<!ENTITY i "internal">]>'
        b"<article><body><p>A &i; B</p></body></article>"
    )
    assert text == "A internal B"


def test_internal_declaration_wins_over_html_name():
    """A document's own declaration of an HTML-named entity is honoured."""
    text = XMLExtractor().extract(
        b'<!DOCTYPE article [<!ENTITY nbsp "[space]">]>'
        b"<article><body><p>A&nbsp;B</p></body></article>"
    )
    assert text == "A[space]B"


def test_unknown_entity_does_not_glue_words_or_drop_document():
    """An entity nobody defines leaves the rest of the paragraph intact."""
    text = extract(b"<p>Hello &bogusentity; world</p>", prolog=PMC_DOCTYPE)
    assert "Hello" in text and "world" in text


def test_external_entity_is_not_read(tmp_path):
    """XXE: a SYSTEM entity naming a local file is never loaded."""
    secret = tmp_path / "secret.txt"
    secret.write_text("TOPSECRET")
    data = (
        f'<!DOCTYPE article [<!ENTITY x SYSTEM "file://{secret}">]>'
        "<article><body><p>Leak: &x; done.</p></body></article>"
    ).encode()
    text = XMLExtractor().extract(data)
    assert text is None or "TOPSECRET" not in text


def test_entity_expansion_bomb_is_bounded():
    """Billion laughs: exponential internal entities are not expanded."""
    entities = "".join(
        f'<!ENTITY l{i} "{("&l" + str(i - 1) + ";") * 10}">' for i in range(1, 10)
    )
    data = (
        f'<!DOCTYPE article [<!ENTITY l0 "lol">{entities}]>'
        "<article><body><p>&l9;</p></body></article>"
    ).encode()
    text = XMLExtractor().extract(data)
    assert text is None or len(text) < 100_000


def test_non_utf8_declared_encoding_preserved():
    """Entity rewriting must not disturb a declared non-UTF-8 encoding."""
    data = (
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        "<article><body><p>Fran\xe7ois&nbsp;Dupont</p></body></article>"
    ).encode("latin-1")
    assert XMLExtractor().extract(data) == "Fran\u00e7ois Dupont"


def test_str_input_with_entities():
    """Decoded str input is handled like bytes."""
    text = XMLExtractor().extract(
        '<?xml version="1.0" encoding="ISO-8859-1"?>'
        "<article><body><p>Fran\u00e7ois&mdash;Dupont</p></body></article>"
    )
    assert text == "Fran\u00e7ois\u2014Dupont"
