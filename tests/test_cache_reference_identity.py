"""A sanitized filename never establishes a Markdown reference's identity."""

import pytest

from linkml_reference_validator.etl.reference_fetcher import (
    ReferenceFetcher,
    URL_SOURCE_CACHE_VERSION,
)
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
)


@pytest.mark.parametrize("trust", [False, True])
def test_colliding_files_are_fetched_from_the_requested_source(tmp_path, trust):
    """Read two real files across fresh fetchers, including trusted-cache mode."""
    directory = tmp_path / "documents"
    directory.mkdir()
    first = directory / "part" / "note.md"
    first.parent.mkdir()
    second = directory / "part_note.md"
    first.write_text("First synthetic document.", encoding="utf-8")
    second.write_text("Second synthetic document.", encoding="utf-8")
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", trust_cached_entries=trust
    )
    ids = [f"file:{first}", f"file:{second}"]
    fetcher = ReferenceFetcher(config)
    assert fetcher.get_cache_path(ids[0]) == fetcher.get_cache_path(ids[1])
    for reference_id, expected in [
        (ids[0], "First synthetic document."),
        (ids[1], "Second synthetic document."),
        (ids[0], "First synthetic document."),
    ]:
        reference = ReferenceFetcher(config).fetch(reference_id)
        assert reference is not None
        assert reference.reference_id == reference_id
        assert reference.content == expected


@pytest.mark.parametrize("allow_stale", [False, True])
def test_colliding_url_is_not_loaded_as_another_reference(tmp_path, allow_stale):
    """The normal and stale read paths reject another URL's serialized text."""
    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))
    first = "url:https://example.invalid/a?b=c"
    second = "url:https://example.invalid/a/b/c"
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=first,
            title="Synthetic",
            content="First synthetic document.",
            content_type="full_text",
            metadata={"url_source_version": URL_SOURCE_CACHE_VERSION},
        )
    )
    assert fetcher.get_cache_path(first) == fetcher.get_cache_path(second)
    original = fetcher.get_cache_path(first).read_bytes()
    assert fetcher._load_from_disk(second, allow_stale=allow_stale) is None
    assert fetcher.get_cache_path(first).read_bytes() == original


@pytest.mark.parametrize(
    ("stored", "requested"),
    [
        (
            "url:https://example.invalid/r.pdf#page=1",
            "url:https://example.invalid/r.pdf#page=2",
        ),
        ("DOI:10.1234/ABC", "DOI:10.1234/abc"),
    ],
)
def test_equivalent_reference_ids_still_share_cached_content(
    tmp_path, stored, requested
):
    """Fragment sharing and DOI case equivalence keep their existing contracts."""
    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=stored,
            title="Synthetic",
            content="Shared synthetic document.",
            content_type="full_text",
            metadata={"url_source_version": URL_SOURCE_CACHE_VERSION},
        )
    )
    reference = fetcher._load_from_disk(requested)
    assert reference is not None
    assert reference.content == "Shared synthetic document."
