"""The public cache contract checks real files without fetching or rewriting."""

from pathlib import Path

import pytest
from pydantic import ValidationError
from ruamel.yaml import YAML

from linkml_reference_validator import (
    CacheFrontmatter,
    scan_cache_dir,
    validate_cache_file,
)
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
    SupplementaryFile,
)


def write_cache(tmp_path: Path, metadata: str, name: str = "PMID_1.md") -> Path:
    """Write a cache with a real YAML header and Markdown body."""
    path = tmp_path / name
    path.write_text(
        f"---\n{metadata}\n---\n\n## Content\n\nEvidence.\n", encoding="utf-8"
    )
    return path


def test_public_model_preserves_extensions():
    """Consumers can layer policy onto parsed metadata without mirroring fields."""
    model = CacheFrontmatter.model_validate(
        {
            "reference_id": "PMID:1",
            "content_type": "future_content_type",
            "database": "Orphanet",
            "future_field": {"nested": [1, True]},
        }
    )
    assert model.model_dump()["database"] == "Orphanet"
    assert model.model_dump()["future_field"] == {"nested": [1, True]}
    assert CacheFrontmatter.model_json_schema()["additionalProperties"] is True
    with pytest.raises(ValidationError):
        CacheFrontmatter.model_validate({"reference_id": "PMID:1"})


@pytest.mark.parametrize(
    "stamp", ["", "extractor_version: 0", "extractor_version: 999"]
)
def test_extensions_and_old_or_future_stamps_are_valid(tmp_path, stamp):
    """Format validity is independent of freshness and local metadata policy."""
    path = write_cache(
        tmp_path,
        f"reference_id: PMID:1\ncontent_type: abstract_only\n{stamp}\n"
        "database: Orphanet\ntitle: a---b\nyear: 2024",
    )
    before = path.read_bytes()
    result = validate_cache_file(str(path))
    assert result.is_valid
    assert result.path == path
    assert result.frontmatter.reference_id == "PMID:1"
    assert result.frontmatter.year == 2024
    assert result.frontmatter.model_extra == {"database": "Orphanet"}
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    "metadata, code, field",
    [
        ("content_type: abstract_only", "invalid_field", "reference_id"),
        ("reference_id: PMID:1", "invalid_field", "content_type"),
        (
            "reference_id: ''\ncontent_type: abstract_only",
            "invalid_field",
            "reference_id",
        ),
        ("reference_id: PMID:1\ncontent_type: []", "invalid_field", "content_type"),
        (
            "reference_id: PMID:1\ncontent_type: abstract_only\nauthors: [123]",
            "invalid_field",
            "authors.0",
        ),
        (
            "reference_id: PMID:1\ncontent_type: abstract_only\nextractor_version: true",
            "invalid_field",
            "extractor_version",
        ),
        (
            "reference_id: PMID:1\ncontent_type: abstract_only\nfull_text_attempted: 'false'",
            "invalid_field",
            "full_text_attempted",
        ),
        (
            "reference_id: PMID:1\ncontent_type: abstract_only\nsupplementary_files: [{filename: x, size_bytes: false}]",
            "invalid_field",
            "supplementary_files.0.size_bytes",
        ),
        ("reference_id: PMID:1\nreference_id: PMID:2", "invalid_yaml", None),
        ("reference_id: [", "invalid_yaml", None),
        ("- item", "invalid_frontmatter", None),
        ("null", "invalid_frontmatter", None),
        ("", "invalid_frontmatter", None),
    ],
)
def test_structured_findings_for_malformed_metadata(tmp_path, metadata, code, field):
    """Malformed external input yields findings, including nested field locations."""
    result = validate_cache_file(write_cache(tmp_path, metadata))
    assert not result.is_valid
    assert any(
        f.code == code and f.field == field and f.message for f in result.findings
    )


@pytest.mark.parametrize(
    "text",
    ["No frontmatter", "---\nreference_id: PMID:1", "Preamble\n---\na: b\n---\n"],
)
def test_missing_or_misplaced_delimiters(tmp_path, text):
    """Only a delimited header at the beginning is cache frontmatter."""
    path = tmp_path / "PMID_1.md"
    path.write_text(text, encoding="utf-8")
    assert validate_cache_file(path).findings[0].code == "invalid_frontmatter"


def test_io_and_encoding_errors_are_findings(tmp_path):
    """A damaged or missing individual file does not abort a gate."""
    path = tmp_path / "PMID_1.md"
    assert validate_cache_file(path).findings[0].code == "read_error"
    path.write_bytes(b"\xff")
    assert validate_cache_file(path).findings[0].code == "read_error"


@pytest.mark.parametrize(
    "reference_id,name,valid",
    [
        ("PMID:1", "PMID_1.md", True),
        ("PMID:1", "PMID_2.md", False),
        ("DOI:10.1/ABC", "doi_10.1_abc.md", True),
        ("url:https://example.org/a?b=c", "url_https___example.org_a_b_c.md", True),
        ("CUSTOM:Abc", "CUSTOM_abc.md", False),
        ("clinicaltrials:NCT01234567", "clinicaltrials_NCT01234567.md", True),
    ],
)
def test_filename_identity(tmp_path, reference_id, name, valid):
    """Use the writer's sanitization and the established DOI case policy."""
    result = validate_cache_file(
        write_cache(
            tmp_path, f"reference_id: {reference_id}\ncontent_type: unknown", name
        )
    )
    assert result.is_valid is valid
    if not valid:
        assert result.frontmatter.reference_id == reference_id
        assert result.findings[0].code == "filename_mismatch"


def test_directory_scan_is_sorted_and_continues_past_bad_files(tmp_path):
    """Every Markdown entry gets a result, without modifying any files."""
    write_cache(tmp_path, "reference_id: PMID:2\ncontent_type: unknown", "PMID_2.md")
    write_cache(tmp_path, "bad: [", "PMID_1.md")
    (tmp_path / "download.xml").write_text("<article/>")
    (tmp_path / "legacy.txt").write_text("Legacy cache")
    nested = tmp_path / "nested"
    nested.mkdir()
    write_cache(nested, "reference_id: PMID:3\ncontent_type: unknown", "PMID_3.md")
    results = scan_cache_dir(tmp_path)
    assert [r.path.name for r in results] == ["PMID_1.md", "PMID_2.md"]
    assert [r.is_valid for r in results] == [False, True]
    assert len(scan_cache_dir(tmp_path, recursive=True)) == 3
    with pytest.raises(FileNotFoundError):
        scan_cache_dir(tmp_path / "missing")
    with pytest.raises(NotADirectoryError):
        scan_cache_dir(tmp_path / "PMID_1.md")


@pytest.mark.parametrize(
    "content_type", ["full_text_html", "full_text_xml", "unavailable"]
)
def test_every_emitted_field_is_owned_by_the_public_model(tmp_path, content_type):
    """The real writer must never grow fields that only downstream models know."""
    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))
    reference = ReferenceContent(
        reference_id="PMID:1",
        title="Title: a---b\nNext line",
        content="Evidence.",
        content_type=content_type,
        authors=["Consortium: Contact", "123"],
        journal="Journal",
        year="2024",
        doi="10.1/example",
        keywords=["on", "123"],
        publication_types=["Journal Article"],
        is_preprint=False,
        peer_review_status="peer_reviewed",
        full_text_attempted=True,
        full_text_declined="access_type: publisher_free",
        full_text_provider="provider",
        full_text_url="https://example.org/paper",
        oa_status="gold",
        license="CC-BY",
        local_pdf_path="/tmp/paper.pdf",
        full_text_access_type="open",
        full_text_source_item_id="123",
        metadata={
            "html_full_text_version": 1,
            "xml_extraction_version": 1,
            "url_source_version": 1,
            "extra_fields_captured": ["outcomes"],
        },
        supplementary_files=[
            SupplementaryFile(
                filename="data.csv",
                download_url="https://example.org/data",
                content_type="text/csv",
                size_bytes=0,
                checksum="abc",
                description="Data: measurements",
                local_path="data.csv",
            )
        ],
    )
    fetcher._save_to_disk(reference)
    path = fetcher.get_cache_path(reference.reference_id)
    result = validate_cache_file(path)
    assert result.is_valid, result.findings
    assert result.frontmatter.model_extra == {}
    assert result.frontmatter.title == reference.title
    assert result.frontmatter.authors == reference.authors
    assert result.frontmatter.keywords == reference.keywords
    assert result.frontmatter.full_text_source_item_id == "123"
    metadata = YAML(typ="safe").load(path.read_text().split("\n---\n", 1)[0][4:])
    assert set(metadata) <= set(CacheFrontmatter.model_fields)
    loaded = fetcher._load_markdown_format(path.read_text(), reference.reference_id)
    assert loaded.authors == reference.authors
    assert loaded.content == reference.content


def test_committed_cache_fixtures_remain_valid(fixtures_dir):
    """Existing cache files satisfy the new contract without migration."""
    results = scan_cache_dir(fixtures_dir)
    assert results
    assert all(result.is_valid for result in results), [
        (result.path, result.findings) for result in results if not result.is_valid
    ]


def test_nested_extensions_and_windows_newlines(tmp_path):
    """Attachment extensions and body delimiters do not confuse the checker."""
    path = tmp_path / "PMID_1.md"
    path.write_bytes(
        b"---\r\nreference_id: PMID:1\r\ncontent_type: unavailable\r\n"
        b"supplementary_files:\r\n- filename: data.csv\r\n  database: ICEES\r\n"
        b"---\r\nBody\r\n---\r\nMore body\r\n"
    )
    before = path.read_bytes()
    result = validate_cache_file(path)
    assert result.is_valid, result.findings
    assert result.frontmatter.supplementary_files[0].model_extra == {
        "database": "ICEES"
    }
    assert path.read_bytes() == before


def test_empty_directory_is_an_empty_scan(tmp_path):
    """An existing empty cache differs from a mistyped directory path."""
    assert scan_cache_dir(tmp_path) == []
