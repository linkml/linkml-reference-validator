"""Cache filenames stay within filesystem limits (issue #132).

A ``url:`` reference with a long query string produced a filename longer
than the 255-byte limit of common filesystems, so ``cache_path.exists()``
raised ``OSError: [Errno 36] File name too long`` and the fetch, and the
validation run with it, crashed.
"""

from unittest.mock import patch

from linkml_reference_validator.cache import (
    MAX_CACHE_FILENAME_BYTES,
    cache_filename,
    validate_cache_file,
)
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig

LONG_URL = "url:https://www.ncbi.nlm.nih.gov/books/NBK1116/?term=" + "x" * 300


def _fetcher(tmp_path):
    return ReferenceFetcher(
        ReferenceValidationConfig(cache_dir=tmp_path, fetch_full_text=False)
    )


def _with_source(content):
    class _Source:
        def fetch(self, identifier, config):
            return content

    return patch(
        "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
        return_value=_Source,
    )


def test_long_filename_is_capped():
    """The filename fits, with room to spare, whatever the reference length."""
    name = cache_filename(LONG_URL)
    assert len(name.encode("utf-8")) <= MAX_CACHE_FILENAME_BYTES
    assert MAX_CACHE_FILENAME_BYTES < 255
    assert name.endswith(".md")
    assert name.startswith("url_https___www.ncbi.nlm.nih.gov_books_NBK1116")


def test_capped_filenames_stay_distinct_and_stable():
    """Two long references differing only past the cut get different names."""
    other = LONG_URL + "y"
    assert cache_filename(LONG_URL) != cache_filename(other)
    assert cache_filename(LONG_URL) == cache_filename(LONG_URL)


def test_short_filenames_are_unchanged():
    """Existing caches are not renamed: only over-long names change."""
    assert cache_filename("url:https://example.org/a?b=c") == "url_https___example.org_a_b_c.md"
    assert cache_filename("PMID:12345") == "PMID_12345.md"


def test_multibyte_names_are_cut_on_a_character_boundary():
    """Truncation never splits a UTF-8 sequence."""
    name = cache_filename("url:https://example.org/" + "é" * 300)
    assert len(name.encode("utf-8")) <= MAX_CACHE_FILENAME_BYTES
    name.encode("utf-8").decode("utf-8")


def test_long_doi_case_variants_share_a_casefolded_name():
    """DOI case variants still differ only in case, so the case lookup finds them."""
    suffix = "Abc" * 100
    upper = cache_filename(f"DOI:10.1234/{suffix}")
    lower = cache_filename(f"DOI:10.1234/{suffix.lower()}")
    assert upper.casefold() == lower.casefold()


def test_fetching_a_long_url_does_not_crash(tmp_path):
    """The reproduction from the issue: a miss, not an OSError."""
    with _with_source(None):
        assert _fetcher(tmp_path).fetch(LONG_URL) is None


def test_long_url_entry_round_trips_through_the_cache(tmp_path):
    """Saved under the capped name, read back without a network call, and valid."""
    content = ReferenceContent(
        reference_id=LONG_URL, title="A long page", content="Body text.", content_type="html"
    )
    with _with_source(content):
        assert _fetcher(tmp_path).fetch(LONG_URL) is not None
    (path,) = tmp_path.glob("*.md")
    assert path.name == cache_filename(LONG_URL)

    with _with_source(None):
        reloaded = _fetcher(tmp_path).fetch(LONG_URL)
    assert reloaded is not None and reloaded.content == "Body text."
    assert reloaded.reference_id == LONG_URL

    result = validate_cache_file(path)
    assert not [f for f in result.findings if f.code == "filename_mismatch"]


def test_the_cap_applies_from_one_byte_over():
    """A name of exactly the limit is left alone; one byte more is capped."""
    prefix = "PMID:"
    exact = prefix + "1" * (MAX_CACHE_FILENAME_BYTES - len("PMID_") - len(".md"))
    assert cache_filename(exact) == exact.replace(":", "_") + ".md"
    assert len(cache_filename(exact).encode()) == MAX_CACHE_FILENAME_BYTES
    over = exact + "1"
    assert cache_filename(over) != over.replace(":", "_") + ".md"
    assert len(cache_filename(over).encode()) <= MAX_CACHE_FILENAME_BYTES


def test_a_long_url_with_a_fragment_does_not_crash(tmp_path):
    """The pre-#114 fragment-keyed probe is capped too, so it cannot raise."""
    with _with_source(None):
        assert _fetcher(tmp_path).fetch(LONG_URL + "#page=4") is None
