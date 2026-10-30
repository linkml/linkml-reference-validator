"""Reading a cache file back gives what was written, or a clean miss (#133, #136).

Two read-path failures:

- A header that is empty, not valid YAML, or not a mapping crashed ``fetch()``
  and ``iter_cached_references()``. The fetch could then never replace the
  damaged entry, and one bad file stopped the whole cache walk (#133). Such an
  entry now reads as absent: the fetch rewrites it, and the walk skips it with
  a warning.
- The ``## Content`` marker was written only for titled entries, but the reader
  dropped everything up to the first line *starting with* ``## Content``. So an
  untitled entry lost all text before a heading like ``## Contents of the kit``
  (#136). The marker is now always written. The reader takes only the exact
  marker that ends the header the writer emits. A file with no such header is
  returned whole.
"""

import logging
from unittest.mock import patch

import pytest

from linkml_reference_validator.etl.reference_fetcher import (
    EXTRACTOR_CACHE_VERSION,
    ReferenceFetcher,
)
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig

FRESH_TEXT = "Freshly fetched abstract text."


@pytest.fixture
def fetcher(tmp_path):
    """A fetcher over an empty cache directory."""
    return ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))


def _fetch_with_stub(fetcher, reference_id="PMID:1"):
    """Run ``fetch`` with the source stubbed to return fresh content."""
    fresh = ReferenceContent(
        reference_id=reference_id, content=FRESH_TEXT, content_type="abstract_only",
        title="A paper",
    )

    class _Source:
        def fetch(self, identifier, config):
            return fresh

    with patch(
        "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        return fetcher.fetch(reference_id)


BAD_HEADERS = {
    "empty": "---\n\n---\n\nOld body.\n",
    "invalid_yaml": "---\nreference_id: PMID:1\ntitle: Gene X: a review: part 2\n---\n\nOld body.\n",
    "scalar": "---\njust a string\n---\n\nOld body.\n",
    "list": "---\n- PMID:1\n- PMID:2\n---\n\nOld body.\n",
    # Past the extractor_version fast path, so the full header is parsed.
    "current_stamp_then_invalid_yaml": (
        f"---\nreference_id: PMID:1\nextractor_version: {EXTRACTOR_CACHE_VERSION}\n"
        "title: Gene X: a review: part 2\n---\n\nOld body.\n"
    ),
    "current_stamp_then_list_item": (
        f"---\nextractor_version: {EXTRACTOR_CACHE_VERSION}\n- stray\n---\n\nOld body.\n"
    ),
}


@pytest.mark.parametrize("header", BAD_HEADERS.values(), ids=BAD_HEADERS.keys())
def test_fetch_replaces_a_damaged_cache_header(fetcher, header):
    """The damaged entry reads as absent, so a fresh fetch rewrites it."""
    path = fetcher.get_cache_path("PMID:1")
    path.write_text(header, encoding="utf-8")

    reference = _fetch_with_stub(fetcher)

    assert reference is not None
    assert reference.content == FRESH_TEXT
    text = path.read_text(encoding="utf-8")
    assert FRESH_TEXT in text
    assert "Old body." not in text


@pytest.mark.parametrize("header", BAD_HEADERS.values(), ids=BAD_HEADERS.keys())
def test_a_damaged_header_is_not_served_even_as_stale(fetcher, header):
    """``allow_stale`` cannot serve a header that does not load."""
    fetcher.get_cache_path("PMID:1").write_text(header, encoding="utf-8")
    assert fetcher._load_from_disk("PMID:1", allow_stale=True) is None


@pytest.mark.parametrize("header", BAD_HEADERS.values(), ids=BAD_HEADERS.keys())
def test_iter_cached_references_skips_a_damaged_file_with_a_warning(
    fetcher, tmp_path, caplog, header
):
    """One bad file no longer stops the walk; the good ones are still yielded."""
    (tmp_path / "A_bad.md").write_text(header, encoding="utf-8")
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:2", content="Good text.", title="Good")
    )

    with caplog.at_level(logging.WARNING):
        references = list(fetcher.iter_cached_references())

    assert [r.reference_id for r in references] == ["PMID:2"]
    assert "A_bad" in caplog.text


def test_is_stale_cache_entry_treats_an_unloadable_header_as_stale():
    """Past the version fast path, a header that does not load is stale, not a crash."""
    for header in (
        BAD_HEADERS["current_stamp_then_invalid_yaml"],
        BAD_HEADERS["current_stamp_then_list_item"],
    ):
        assert ReferenceFetcher._is_stale_cache_entry(header) is True


UNTITLED_ID = "clinicaltrials:NCT00000001"


@pytest.mark.parametrize(
    "content",
    [
        "Intro paragraph: aspirin inhibits COX-1.\n\n## Contents of the kit\n\nBuffer A.",
        "Intro paragraph: aspirin inhibits COX-1.\n\n## Content warning\n\nBuffer A.",
        "Intro paragraph: aspirin inhibits COX-1.\n\n## Content\n\nBuffer A.",
        "## Content\n\nThe record itself opens with the marker heading.",
        "# A heading in the text\n\n## Content\n\nBuffer A.",
        "**Authors:** not a header, just text.\n\n## Content\n\nBuffer A.",
    ],
)
@pytest.mark.parametrize("title", [None, "A titled record"])
def test_content_round_trips_whatever_headings_it_holds(fetcher, title, content):
    """Save then load gives back exactly the text that was saved."""
    fetcher._save_to_disk(
        ReferenceContent(reference_id=UNTITLED_ID, title=title, content=content,
                         authors=["Doe J"] if title else None, journal="J" if title else None,
                         year="2020" if title else None, doi="10.1/x" if title else None)
    )
    loaded = fetcher._load_from_disk(UNTITLED_ID, allow_stale=True)
    assert loaded is not None
    assert loaded.content == content


def test_a_title_with_a_line_break_keeps_the_header_on_one_line(fetcher):
    """A newline in a title cannot push header text into the content."""
    content = "Body text."
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:3", title="Part one\n## Content\nPart two",
                         content=content)
    )
    loaded = fetcher._load_from_disk("PMID:3", allow_stale=True)
    assert loaded is not None
    assert loaded.content == content
    assert loaded.title == "Part one\n## Content\nPart two"


@pytest.mark.parametrize(
    "body",
    [
        "Intro paragraph.\n\n## Contents of the kit\n\nBuffer A.",
        "Intro paragraph.\n\n## Content\n\nBuffer A.",
    ],
)
def test_a_legacy_untitled_file_without_a_marker_is_read_whole(fetcher, body):
    """Untitled files written before the marker was always emitted lose nothing."""
    fetcher.get_cache_path(UNTITLED_ID).write_text(
        f"---\nreference_id: {UNTITLED_ID}\ncontent_type: summary\n---\n\n{body}\n",
        encoding="utf-8",
    )
    loaded = fetcher._load_from_disk(UNTITLED_ID, allow_stale=True)
    assert loaded is not None
    assert loaded.content == body


def test_a_legacy_titled_file_still_drops_its_header(fetcher):
    """The header the writer has always emitted for a titled entry is still removed."""
    fetcher.get_cache_path("PMID:4").write_text(
        "---\nreference_id: PMID:4\ntitle: A paper\n---\n\n# A paper\n"
        "**Authors:** Doe J, Roe R\n**Journal:** J (2020)\n"
        "**DOI:** [10.1/x](https://doi.org/10.1/x)\n\n## Content\n\nThe abstract.\n",
        encoding="utf-8",
    )
    loaded = fetcher._load_from_disk("PMID:4", allow_stale=True)
    assert loaded is not None
    assert loaded.content == "The abstract."


def test_is_stale_cache_entry_treats_an_empty_header_as_stale():
    """Stale at the version check today; pinned in case that check ever moves."""
    assert ReferenceFetcher._is_stale_cache_entry(BAD_HEADERS["empty"]) is True


def test_iter_cached_references_skips_an_undecodable_file_with_a_warning(
    fetcher, tmp_path, caplog
):
    """A file that is not UTF-8 is skipped too, not only a bad header."""
    (tmp_path / "A_bad.md").write_bytes(b"---\nreference_id: PMID:9\n---\n\n\xff\xfe broken")
    fetcher._save_to_disk(
        ReferenceContent(reference_id="PMID:2", content="Good text.", title="Good")
    )

    with caplog.at_level(logging.WARNING):
        references = list(fetcher.iter_cached_references())

    assert [r.reference_id for r in references] == ["PMID:2"]
    assert "A_bad" in caplog.text


def test_the_walk_does_not_promise_a_re_fetch(fetcher, tmp_path, caplog):
    """Skipping a file during the walk does not rewrite it, so the warning says only that."""
    (tmp_path / "A_bad.md").write_text(BAD_HEADERS["empty"], encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        list(fetcher.iter_cached_references())
    assert "A_bad" in caplog.text
    assert "re-fetch" not in caplog.text


@pytest.mark.parametrize("title", [None, "Line one\nline two"])
def test_lookup_markdown_without_a_cache_file_reads_back_as_saved(fetcher, title):
    """``lookup``'s fallback output follows the cache format, marker and one-line title."""
    from linkml_reference_validator.cli.lookup import _format_as_markdown

    content = "Intro paragraph.\n\n## Contents of the kit\n\nBuffer A."
    reference = ReferenceContent(reference_id=UNTITLED_ID, title=title, content=content)
    assert not fetcher.find_cache_file(UNTITLED_ID).exists()

    markdown = _format_as_markdown(reference, fetcher)

    fetcher.get_cache_path(UNTITLED_ID).write_text(markdown, encoding="utf-8")
    loaded = fetcher._load_from_disk(UNTITLED_ID, allow_stale=True)
    assert loaded is not None
    assert loaded.content == content
