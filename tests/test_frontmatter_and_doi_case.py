"""Two ways a cache entry's identity or content is lost on the way to disk.

Both were found downstream, where they had been worked around with runtime
monkeypatches over this module's internals. They are ordinary defects here.

**A newline in a title produces invalid frontmatter.** ``_quote_yaml_value``
quotes on a list of special characters that does not include ``\\n``, so a
Crossref title containing a literal line break is interpolated straight into
the frontmatter and the entry no longer parses. Nothing downstream can recover
it, because re-fetching writes the same broken file.

**A DOI in two capitalizations names two files.** DOI names are
case-insensitive by specification, so ``DOI:10.1016/S0002-9440(10)63332-9`` and
``doi:10.1016/s0002-9440(10)63332-9`` are the same reference; the prefix is
normalized but the suffix is not, so each gets its own cache file. The second
one fetched is a duplicate download, and a project that commits its cache
carries both.
"""


from pathlib import Path
from unittest.mock import patch

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig


@pytest.fixture
def fetcher(tmp_path):
    return ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))


# --------------------------------------------------------------------------
# Line breaks in metadata
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "A Crossref title\nwith a literal newline",
        "Carriage return\r\nand line feed",
        "Trailing break\n",
        # ruamel's scanner treats these as line breaks too, and its reader
        # rejects the vertical-tab and form-feed outright as non-printable.
        # Rarer characters, identical unrecoverable file.
        "Next line\x85separator",
        "Line separator\u2028here",
        "Paragraph separator\u2029here",
        "Vertical tab\x0bhere",
        "Form feed\x0chere",
    ],
)
def test_a_title_containing_a_line_break_round_trips(fetcher, title):
    """The entry must still parse, and the title must survive unchanged.

    Folding the break into a space would also "work" in the sense that the file
    parses, but it silently edits the metadata -- and a title is compared
    against the fetched record elsewhere, so an edited one reads as a mismatch.
    """
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id="DOI:10.1/x",
            title=title,
            content="Body text.",
            content_type="abstract_only",
        )
    )
    path = fetcher.get_cache_path("DOI:10.1/x")

    reloaded = fetcher._load_markdown_format(path.read_text(encoding="utf-8"), "DOI:10.1/x")

    assert reloaded is not None, "the entry must still parse"
    assert reloaded.title == title


def test_quoting_is_unchanged_for_single_line_values(fetcher):
    """The escape applies to the case that needs it and nothing else."""
    assert fetcher._quote_yaml_value("Normal title") == "Normal title"
    assert fetcher._quote_yaml_value("Title: with colon") == '"Title: with colon"'
    assert fetcher._quote_yaml_value("[Cholera].") == '"[Cholera]."'


# --------------------------------------------------------------------------
# DOI capitalization
# --------------------------------------------------------------------------

UPPER = "DOI:10.1016/S0002-9440(10)63332-9"
LOWER = "doi:10.1016/s0002-9440(10)63332-9"


def test_a_doi_in_two_capitalizations_uses_one_cache_file(fetcher):
    """DOI names are case-insensitive, so these are one reference."""
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=UPPER, title="A paper", content="Body.",
            content_type="abstract_only",
        )
    )

    assert fetcher.get_cache_path(LOWER) == fetcher.get_cache_path(UPPER)


def test_the_second_capitalization_reads_the_first_one_s_entry(fetcher, tmp_path):
    """The point of sharing the path: no duplicate download, no second file."""
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=UPPER, title="A paper", content="Body text here.",
            content_type="abstract_only",
        )
    )

    path = fetcher.get_cache_path(LOWER)
    reloaded = fetcher._load_markdown_format(path.read_text(encoding="utf-8"), LOWER)

    assert reloaded.title == "A paper"
    assert len(list(tmp_path.glob("*.md"))) == 1, "one reference, one file"


def test_an_existing_entry_keeps_its_own_capitalization(fetcher, tmp_path):
    """Backwards compatible: a committed cache is not renamed underneath anyone.

    Resolution finds whatever spelling is already on disk rather than imposing
    one, so a project that has committed thousands of DOI entries sees no diff.
    """
    written = tmp_path / "DOI_10.1016_S0002-9440(10)63332-9.md"
    written.write_text(
        "---\nreference_id: DOI:10.1016/S0002-9440(10)63332-9\n"
        "title: A paper\ncontent_type: abstract_only\n---\n\n## Content\n\nBody.\n",
        encoding="utf-8",
    )

    assert fetcher.get_cache_path(LOWER).name == written.name


def test_a_non_doi_reference_is_not_case_folded(fetcher):
    """Only DOI names are case-insensitive; a PMID or an NCT id is not.

    Folding those would merge references that are genuinely distinct, so the
    rule is scoped to the identifier type the specification covers.
    """
    assert fetcher.get_cache_path("PMID:123") != fetcher.get_cache_path("PMID:123X")
    assert "PMID_123" in fetcher.get_cache_path("PMID:123").name


def test_both_spellings_on_disk_resolve_deterministically(fetcher, tmp_path):
    """The mixed state is not hypothetical -- it is what a case-sensitive
    checkout of an already-duplicated cache looks like.

    ``iterdir()`` order is arbitrary, so returning the first match makes the
    answer depend on inode order: two checkouts of the same repository can
    disagree, and asking for one spelling can hand back the other.
    """
    upper = tmp_path / "DOI_10.1016_S0002-9440(10)63332-9.md"
    lower = tmp_path / "doi_10.1016_s0002-9440(10)63332-9.md"
    for path, who in ((upper, "upper"), (lower, "lower")):
        try:
            path.write_text(f"---\nreference_id: x\n---\n\n## Content\n\n{who}\n")
        except OSError:  # pragma: no cover - case-insensitive filesystem
            pytest.skip("filesystem cannot hold both spellings")
    if not (upper.exists() and lower.exists()) or upper.read_text() == lower.read_text():
        pytest.skip("filesystem folded the two names together")

    assert fetcher.get_cache_path(UPPER).name == upper.name, "exact spelling wins"
    assert fetcher.get_cache_path(LOWER).name == lower.name
    # ...and repeated resolution is stable
    assert fetcher.get_cache_path(UPPER) == fetcher.get_cache_path(UPPER)


def test_saving_under_the_second_spelling_does_not_create_a_second_file(fetcher, tmp_path):
    """A single save was not enough to catch a second write."""
    for rid in (UPPER, LOWER):
        fetcher._save_to_disk(
            ReferenceContent(
                reference_id=rid, title="A paper", content="Body.",
                content_type="abstract_only",
            )
        )

    assert len(list(tmp_path.glob("*.md"))) == 1, "one reference, one file"


def test_a_cross_spelling_refetch_keeps_the_stored_reference_id(fetcher, tmp_path):
    """The filename stops churning; the frontmatter must too.

    Rewriting ``reference_id`` under the caller's spelling would leave a
    one-line diff in a committed cache on every re-fetch -- the same churn this
    change exists to remove, one layer in.
    """
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=UPPER, title="A paper", content="Body.",
            content_type="abstract_only",
        )
    )
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=LOWER, title="A paper", content="Body.",
            content_type="abstract_only",
        )
    )

    stored = fetcher.get_cache_path(UPPER).read_text(encoding="utf-8")
    assert f"reference_id: {UPPER}" in stored


def test_resolution_does_not_scan_the_directory_per_call(fetcher, tmp_path):
    """A scan per resolution is quadratic over a cache.

    ``_cache_path`` is on the read *and* write paths, so a run touching every
    reference scanned the whole directory once per reference: measured at 6.7 ms
    a call against a 6,721-entry cache, or 45 seconds of pure path resolution.
    """
    for i in range(50):
        (tmp_path / f"DOI_10.1000_paper{i}.md").write_text("x")

    scans = 0
    real_iterdir = Path.iterdir

    def counting_iterdir(self):
        nonlocal scans
        scans += 1
        return real_iterdir(self)

    with patch.object(Path, "iterdir", counting_iterdir):
        for i in range(20):
            fetcher.get_cache_path(f"DOI:10.1000/paper{i}")

    assert scans <= 1, f"expected at most one directory scan, got {scans}"
