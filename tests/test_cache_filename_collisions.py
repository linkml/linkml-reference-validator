"""Distinct references never share a cache file, nor read each other's text (issue #131).

Sanitizing a reference ID into a filename maps ``:`` ``/`` ``?`` and ``=`` to
``_``, so distinct references can sanitize alike:
``url:https://ex.org/a?b=c`` and ``url:https://ex.org/a/b/c``. The second was
then served the first one's text, so quotes from one validated against the
other. Existing filenames are kept as they are; only a reference whose name is
already taken by a different one gets a disambiguated name.
"""

from pathlib import Path
from unittest.mock import patch

from linkml_reference_validator.cache import cache_filename, validate_cache_file
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig

FIRST = "url:https://ex.org/a?b=c"
SECOND = "url:https://ex.org/a/b/c"


def _fetcher(tmp_path):
    return ReferenceFetcher(
        ReferenceValidationConfig(cache_dir=tmp_path, fetch_full_text=False)
    )


class _Calls:
    """A stub source returning the given text for each identifier, and counting calls."""

    def __init__(self, texts: dict[str, str]):
        self.texts = texts
        self.calls: list[str] = []
        outer = self

        class _Source:
            def fetch(self, identifier, config):
                outer.calls.append(identifier)
                for reference_id, text in outer.texts.items():
                    if reference_id.split(":", 1)[1] == identifier:
                        return ReferenceContent(
                            reference_id=reference_id, title="T", content=text,
                            content_type="html",
                        )
                return None

        self.source = _Source

    def __enter__(self):
        self._patch = patch(
            "linkml_reference_validator.etl.reference_fetcher"
            ".ReferenceSourceRegistry.get_source",
            return_value=self.source,
        )
        self._patch.start()
        return self

    def __exit__(self, *exc):
        self._patch.stop()


def test_the_names_really_collide():
    """The premise: both references sanitize to one filename."""
    assert cache_filename(FIRST) == cache_filename(SECOND)


def test_second_reference_is_fetched_not_served_the_first(tmp_path):
    """The reproduction from the issue."""
    with _Calls({FIRST: "Page one says aspirin cures headaches."}):
        _fetcher(tmp_path).fetch(FIRST)
    with _Calls({SECOND: "Page two is about something else."}) as stub:
        second = _fetcher(tmp_path).fetch(SECOND)
    assert stub.calls == ["https://ex.org/a/b/c"]
    assert second is not None
    assert second.reference_id == SECOND
    assert second.content == "Page two is about something else."


def test_both_entries_coexist_and_reload_their_own_text(tmp_path):
    """Neither overwrites the other; each reads back its own text, offline."""
    with _Calls({FIRST: "First text.", SECOND: "Second text."}):
        _fetcher(tmp_path).fetch(FIRST)
        _fetcher(tmp_path).fetch(SECOND)
    files = sorted(tmp_path.glob("*.md"))
    assert len(files) == 2
    assert (tmp_path / cache_filename(FIRST)) in files  # the first keeps its name

    with _Calls({}) as stub:
        assert _fetcher(tmp_path).fetch(FIRST).content == "First text."
        assert _fetcher(tmp_path).fetch(SECOND).content == "Second text."
    assert stub.calls == []
    for path in files:
        result = validate_cache_file(path)
        assert not [f for f in result.findings if f.code == "filename_mismatch"], path


def test_an_entry_written_for_another_reference_is_never_served(tmp_path):
    """A cache that already collided: the file names another reference, so it is a miss."""
    (tmp_path / cache_filename(FIRST)).write_text(
        f"---\nreference_id: {SECOND}\ntitle: T\ncontent_type: html\n"
        "extractor_version: 1\nurl_source_version: 2\n---\n\n## Content\n\nSecond text.\n",
        encoding="utf-8",
    )
    with _Calls({}):
        assert _fetcher(tmp_path).fetch(FIRST) is None
        assert _fetcher(tmp_path).fetch(SECOND).content == "Second text."


def test_file_paths_that_sanitize_alike_get_their_own_entries(tmp_path):
    """``file:/x/a/b.md`` and ``file:/x/a_b.md`` collide the same way."""
    nested, flat = tmp_path / "docs" / "a" / "b.md", tmp_path / "docs" / "a_b.md"
    nested.parent.mkdir(parents=True)
    nested.write_text("Nested file text.", encoding="utf-8")
    flat.write_text("Flat file text.", encoding="utf-8")
    cache = tmp_path / "cache"
    first, second = _fetcher(cache).fetch(f"file:{nested}"), _fetcher(cache).fetch(f"file:{flat}")
    assert first is not None and second is not None
    assert "Nested file text." in (first.content or "")
    assert "Flat file text." in (second.content or "")
    assert len(list(Path(cache).glob("*.md"))) == 2


def test_ids_the_yaml_writer_quotes_are_still_recognised_as_their_own(tmp_path):
    """A reference_id written quoted or escaped is read back as the same reference.

    Read as raw text, ``reference_id: 'url:https://ex.org/a b: c'`` would name
    a "different" reference and the entry would be re-fetched under a second
    name on every run.
    """
    fetcher = _fetcher(tmp_path)
    for reference_id in (
        "url:https://ex.org/a b: c",
        "url:https://ex.org/x #y",
        "DOI:10.1/'quoted'",
        'DOI:10.1/"dq"',
        "file:/tmp/a, b.md",
    ):
        fetcher._save_to_disk(
            ReferenceContent(reference_id=reference_id, title="T", content="c", content_type="html")
        )
        assert fetcher.get_cache_path(reference_id).name == cache_filename(
            fetcher._canonical_cache_id(reference_id)
        ), reference_id


def test_deleting_the_holder_does_not_orphan_the_disambiguated_entry(tmp_path):
    """Once written under its own name, a reference keeps reading and writing there."""
    with _Calls({FIRST: "First text.", SECOND: "Second text."}):
        _fetcher(tmp_path).fetch(FIRST)
        _fetcher(tmp_path).fetch(SECOND)
    (tmp_path / cache_filename(FIRST)).unlink()

    with _Calls({}) as stub:
        assert _fetcher(tmp_path).fetch(SECOND).content == "Second text."
    assert stub.calls == []
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_fragment_reference_whose_usual_name_is_held_elsewhere(tmp_path):
    """A url: fragment shares its URL's entry, disambiguated or not."""
    with _Calls({FIRST: "First text.", SECOND: "Second text."}):
        _fetcher(tmp_path).fetch(FIRST)
        _fetcher(tmp_path).fetch(SECOND)
    with _Calls({}) as stub:
        page = _fetcher(tmp_path).fetch(SECOND + "#page=3")
    assert stub.calls == []
    assert page is not None and page.content == "Second text."
    assert page.reference_id == SECOND + "#page=3"
