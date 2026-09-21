"""An entry that claims no content must be re-testable after the extractor improves.

Issue #88: the extractor read only ``Abstract`` and ignored ``OtherAbstract``,
so a record whose abstract PubMed keeps under ``OtherAbstract`` was written as
``content_type: unavailable`` -- deleting, on refresh, the abstract the cache
already held.

Fixing the extractor does not by itself recover those entries. They carry the
current ``extractor_version``, so ``_is_stale_cache_entry`` calls them fresh and
they are never re-fetched: the text stays deleted permanently. They need their
own staleness stamp, scoped the way ``html_full_text_version`` and
``xml_extraction_version`` already are, so the refresh cost falls on the
entries that could be wrong rather than on the whole cache.
"""

from __future__ import annotations

from linkml_reference_validator.etl.reference_fetcher import (
    ABSENT_CONTENT_CACHE_VERSION,
    EXTRACTOR_CACHE_VERSION,
    HTML_FULL_TEXT_CACHE_VERSION,
    XML_EXTRACTION_CACHE_VERSION,
    ReferenceFetcher,
)


def _entry(content_type: str, *, absent_version: int | None = None) -> str:
    """A cache entry that is current in every respect except what a test varies.

    The per-content-type stamps are filled in so a test of the absent-content
    rule is not accidentally measuring the pre-existing HTML or XML rules.
    """
    lines = [
        "---",
        "reference_id: PMID:5697815",
        f"extractor_version: {EXTRACTOR_CACHE_VERSION}",
    ]
    if absent_version is not None:
        lines.append(f"absent_content_version: {absent_version}")
    if content_type == "full_text_html":
        lines.append(f"html_full_text_version: {HTML_FULL_TEXT_CACHE_VERSION}")
    if content_type == "full_text_xml":
        lines.append(f"xml_extraction_version: {XML_EXTRACTION_CACHE_VERSION}")
    lines += [f"content_type: {content_type}", "---", "", "## Content", ""]
    return "\n".join(lines)


def test_unavailable_entry_without_the_stamp_is_stale():
    """This is the entry #88 damaged: current extractor stamp, but no content."""
    assert ReferenceFetcher._is_stale_cache_entry(_entry("unavailable"))


def test_unavailable_entry_with_the_current_stamp_is_fresh():
    """Once re-tested by a fixed extractor it must stop being re-fetched."""
    assert not ReferenceFetcher._is_stale_cache_entry(
        _entry("unavailable", absent_version=ABSENT_CONTENT_CACHE_VERSION)
    )


def test_a_newer_stamp_is_not_stale():
    """An older tool reading a newer cache leaves it alone, as elsewhere."""
    assert not ReferenceFetcher._is_stale_cache_entry(
        _entry("unavailable", absent_version=ABSENT_CONTENT_CACHE_VERSION + 1)
    )


def test_entries_that_do_have_content_are_untouched():
    """The stamp is scoped to ``unavailable`` so the blast radius stays small.

    A blanket ``EXTRACTOR_CACHE_VERSION`` bump would invalidate every cached
    reference -- 57,551 files in the dismech cache against the 1,735 that claim
    no content -- for a bug that can only have produced the latter.
    """
    for content_type in (
        "abstract_only",
        "full_text_xml",
        "full_text_html",
        "full_text_pdf",
        "summary",
        "structured_record",
    ):
        assert not ReferenceFetcher._is_stale_cache_entry(_entry(content_type)), (
            f"{content_type} should not be invalidated by the absent-content stamp"
        )


def test_a_freshly_written_absent_entry_is_not_immediately_stale(tmp_path):
    """The emitter and the staleness rule must agree, or the fix does nothing.

    Without the emitted stamp every ``unavailable`` entry would be re-fetched on
    every run forever; without the staleness rule the already-damaged ones would
    never be re-fetched at all. This is the round trip.
    """
    from linkml_reference_validator.models import (
        ReferenceContent,
        ReferenceValidationConfig,
    )

    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id="PMID:4869291",
            content_type="unavailable",
            title="A record with no abstract anywhere",
            content="",
        )
    )

    written = next(tmp_path.glob("*.md")).read_text()
    assert f"absent_content_version: {ABSENT_CONTENT_CACHE_VERSION}" in written
    assert not ReferenceFetcher._is_stale_cache_entry(written)
