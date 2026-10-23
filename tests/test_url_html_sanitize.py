"""HTML fetched by ``URLSource`` is sanitized before it is cached (issue #92).

``URLSource`` used to store the response body verbatim, so page scripts,
comments and tag attributes (signed asset URLs, API-key parameters) went
into caches that projects commit to public repositories. Now HTML keeps its
body markup and text, loses ``script``/``style``/``noscript``/``template``
and comments, drops ``meta``/``link``/``base`` (they hold nothing but
attributes), and keeps only the table-structural attributes ``rowspan``,
``colspan`` and ``scope``. Plain text and XML are stored as before.

Since #102 the page is also flattened to readable text (see
``test_url_html_to_text.py``); what is dropped here is still dropped.
"""

from unittest.mock import patch

import pytest

from linkml_reference_validator.etl.extract.html import sanitize_html
from linkml_reference_validator.etl.sources.url import URLSource
from linkml_reference_validator.models import ReferenceValidationConfig

PAGE = b"""<!DOCTYPE html>
<html lang="en">
<head>
  <title>Journal | Home</title>
  <base href="https://example.org/">
  <meta name="citation_title" content="Mitochondrial Disease in Children">
  <link rel="stylesheet" href="https://cdn.example.org/site.css?token=T">
  <style>.hidden { display: none }</style>
  <script>var apiKey = "SECRET-KEY-123";</script>
  <script src="https://cdn.example.org/app.js?Signature=abc&Expires=2147483647"></script>
</head>
<body class="article" data-token="SIGNED-TOKEN">
  <!-- build 4f2a; internal note -->
  <p id="p1" onclick="track()">Patients showed <a href="https://x.org/?api_key=K">lactic acidosis</a>.</p>
  <noscript><img src="https://tracker.example.org/pixel.gif"></noscript>
  <template><p>Template body</p></template>
  <table class="t">
    <tr><th scope="col" style="color:red">Gene</th><th colspan="2">Finding</th></tr>
    <tr><td rowspan="2" data-x="1">POLG</td><td>A</td><td>B</td></tr>
  </table>
</body>
</html>
"""


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(cache_dir=tmp_path / "cache", rate_limit_delay=0.0)


def _fetch(url, body, content_type, config):
    with patch("linkml_reference_validator.etl.sources.url.ContentAcquirer") as MockAcquirer:
        MockAcquirer.return_value.fetch_bytes.return_value = (body, content_type)
        return URLSource().fetch(url, config)


@pytest.fixture
def cached(config):
    result = _fetch("https://example.org/article/1", PAGE, "text/html; charset=utf-8", config)
    assert result is not None
    return result


@pytest.mark.parametrize(
    "gone",
    [
        "SECRET-KEY-123",
        "Signature=abc",
        ".hidden",
        "tracker.example.org",
        "Template body",
        "<script",
        "<style",
        "<noscript",
        "<template",
        "<meta",
        "<link",
        "<base",
    ],
)
def test_non_content_elements_are_dropped(cached, gone):
    assert gone not in cached.content


def test_comments_are_dropped(cached):
    assert "internal note" not in cached.content
    assert "<!--" not in cached.content


@pytest.mark.parametrize(
    "gone",
    ["SIGNED-TOKEN", "api_key=K", "onclick", 'class="', 'id="', 'style="', "data-x", 'lang="'],
)
def test_attributes_are_dropped(cached, gone):
    assert gone not in cached.content


def test_body_text_survives_as_readable_text(cached):
    """Markup is no longer kept (#102): table structure becomes one line per row."""
    assert "Patients showed lactic acidosis." in cached.content.splitlines()
    assert "Gene | Finding" in cached.content.splitlines()
    assert "POLG | A | B" in cached.content.splitlines()
    assert cached.content_type == "url"


def test_title_is_read_before_attributes_are_stripped(cached):
    """citation_title lives in a <meta> attribute, so it must be read from the raw page."""
    assert cached.title == "Mitochondrial Disease in Children"


def test_html_is_sniffed_without_a_content_type(config):
    result = _fetch("https://example.org/a", PAGE, None, config)
    assert "SECRET-KEY-123" not in result.content


def test_plain_text_is_left_alone(config):
    body = b'Plain notes. <script>not really markup</script> <b class="x">'
    result = _fetch("https://example.org/notes.txt", body, "text/plain", config)
    assert result.content == body.decode()


def test_xml_is_left_alone(config):
    body = b'<?xml version="1.0"?><record id="7"><!-- c --><title>T</title></record>'
    result = _fetch("https://example.org/r.xml", body, "application/xml", config)
    assert result.content == body.decode()


def test_sanitize_html_is_idempotent():
    once = sanitize_html(PAGE.decode())
    assert sanitize_html(once) == once


SCRIPTED = b'<p>Text</p><script>var apiKey = "SECRET-KEY-123";</script>'


@pytest.mark.parametrize(
    "body",
    [
        b"\xef\xbb\xbf<!DOCTYPE html><html><body>" + SCRIPTED + b"</body></html>",
        b"<!-- saved from url=(0042)https://example.org -->\n<html><body>" + SCRIPTED,
        b"<!-- a -->\n<!-- b -->\n<!DOCTYPE html><html>" + SCRIPTED,
        b"<head><title>T</title></head><body>" + SCRIPTED,
        b"\n  <body>" + SCRIPTED,
    ],
    ids=["bom", "comment", "two-comments", "head-first", "body-first"],
)
@pytest.mark.parametrize("content_type", [None, "text/plain"])
def test_html_is_recognized_past_a_bom_or_leading_comments(config, body, content_type):
    """A mislabelled page is still a page. Its scripts must not reach the cache."""
    result = _fetch("https://example.org/a", body, content_type, config)
    assert "SECRET-KEY-123" not in result.content
    assert "Text" in result.content


def test_text_that_mentions_html_is_left_alone(config):
    body = b"Notes on the <html> element and <script> tags."
    result = _fetch("https://example.org/notes.txt", body, "text/plain", config)
    assert result.content == body.decode()
