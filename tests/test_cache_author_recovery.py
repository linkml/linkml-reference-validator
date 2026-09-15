"""Exercise legacy author recovery through real cache files and metadata export."""

import logging

import pytest

from linkml_reference_validator.etl.csl_export import reference_to_csl_json
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
)


@pytest.mark.parametrize(
    "author_yaml, expected, dropped",
    [
        (
            "- Smith J\n- Consortium. Electronic address: contact@example.org",
            ["Smith J", "Consortium. Electronic address: contact@example.org"],
            False,
        ),
        ("{First: one, Second: two}", ["First: one", "Second: two"], False),
        ('"  Smith J  "', ["  Smith J  "], False),
        (
            "- null\n- [nested, list]\n- {Bad: {nested: value}}\n- 123\n"
            "- {Good: email, Missing: null, List: [bad], 12: value}\n- Valid",
            ["Good: email", "Valid"],
            True,
        ),
        ("- null\n- {Missing: null}\n- {}\n- false", None, True),
        ("null", None, False),
        ("[]", None, False),
    ],
)
def test_legacy_authors_load_save_reload_and_export(
    tmp_path, caplog, author_yaml, expected, dropped
):
    """Recover readable pairs, skip invalid values, and export only author strings."""
    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))
    path = fetcher.get_cache_path("PMID:12345")
    author_yaml = "\n".join("  " + line for line in author_yaml.splitlines())
    path.write_text(
        "---\nreference_id: PMID:12345\ntitle: Legacy paper\nauthors:\n"
        f"{author_yaml}\nkeywords: topic\npublication_types: Article\n"
        "---\n# Legacy paper\n\n## Content\n\nOriginal abstract.\n",
        encoding="utf-8",
    )
    with caplog.at_level(logging.WARNING):
        loaded = fetcher._load_from_disk("PMID:12345", allow_stale=True)
    assert loaded is not None
    assert loaded.authors == expected
    assert loaded.keywords == ["topic"]
    assert loaded.publication_types == ["Article"]
    if dropped:
        assert "author" in caplog.text.lower()
        assert "PMID:12345" in caplog.text
    else:
        assert not caplog.records

    exported_reference = list(fetcher.iter_cached_references())[0]
    exported = reference_to_csl_json(exported_reference)
    assert exported is not None
    assert exported.get("author") == (
        [{"literal": author} for author in expected] if expected else None
    )

    fetcher._save_to_disk(loaded)
    reloaded = fetcher._load_from_disk("PMID:12345")
    assert reloaded is not None
    assert reloaded.authors == expected
    assert reloaded.content == loaded.content
    assert reference_to_csl_json(reloaded) == exported


def test_fresh_colon_author_round_trip(tmp_path, caplog):
    """The existing writer quotes colon-bearing authors and preserves their text."""
    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))
    author = "Some Study Consortium. Electronic address: someone@example.org"
    reference = ReferenceContent(reference_id="PMID:12345", authors=[author])
    fetcher._save_to_disk(reference)
    assert f'- "{author}"' in fetcher.get_cache_path(reference.reference_id).read_text()
    loaded = fetcher._load_from_disk(reference.reference_id)
    assert loaded is not None
    assert loaded.authors == [author]
    assert not caplog.records
