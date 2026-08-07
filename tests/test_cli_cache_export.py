"""Tests for exporting public cache metadata for Zotero import."""

import json

from typer.testing import CliRunner

from linkml_reference_validator.cli import app


def _write_reference(
    cache_dir,
    filename: str,
    *,
    reference_id: str,
    title: str,
    content_type: str = "abstract_only",
    doi: str | None = None,
    authors: list[str] | None = None,
    journal: str | None = None,
    year: str | None = None,
) -> None:
    """Write one representative Markdown reference-cache entry."""
    fields = [
        "---",
        f'reference_id: "{reference_id}"',
        f'title: "{title}"',
        f"content_type: {content_type}",
    ]
    if doi:
        fields.append(f'doi: "{doi}"')
    if authors:
        fields.append("authors:")
        fields.extend(f'- "{author}"' for author in authors)
    if journal:
        fields.append(f'journal: "{journal}"')
    if year:
        fields.append(f"year: '{year}'")
    fields.extend(
        [
            'local_pdf_path: "files/private.pdf"',
            "---",
            "",
            "PRIVATE OR CACHED CONTENT MUST NEVER BE EXPORTED",
        ]
    )
    (cache_dir / filename).write_text("\n".join(fields), encoding="utf-8")


def test_cache_export_writes_deduplicated_metadata_only_csl_json(tmp_path):
    """Default export emits missing-full-text DOI/PMID metadata without content."""
    cache_dir = tmp_path / "references_cache"
    cache_dir.mkdir()
    _write_reference(
        cache_dir,
        "A.md",
        reference_id="DOI:10.1000/Example",
        title="Example article",
        doi="https://doi.org/10.1000/Example",
        authors=["Ada Lovelace", "Grace Hopper"],
        journal="Journal of Tests",
        year="2024",
    )
    _write_reference(
        cache_dir,
        "B.md",
        reference_id="PMID:999",
        title="Duplicate record",
        doi="10.1000/example",
    )
    _write_reference(
        cache_dir,
        "C.md",
        reference_id="PMID:12345",
        title="PubMed-only article",
        authors=["Single Name"],
        year="2020 May",
    )
    _write_reference(
        cache_dir,
        "D.md",
        reference_id="DOI:10.1000/already-full",
        title="Already full text",
        doi="10.1000/already-full",
        content_type="full_text_pdf",
    )
    _write_reference(
        cache_dir,
        "E.md",
        reference_id="NCIT:C123",
        title="Not a publication",
    )
    output = tmp_path / "dismech-zotero.json"

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "export",
            "--cache-dir",
            str(cache_dir),
            "--format",
            "csl-json",
            "--needs-full-text",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    records = json.loads(output.read_text(encoding="utf-8"))
    assert records == [
        {
            "id": "DOI:10.1000/Example",
            "type": "article-journal",
            "title": "Example article",
            "author": [{"literal": "Ada Lovelace"}, {"literal": "Grace Hopper"}],
            "container-title": "Journal of Tests",
            "issued": {"date-parts": [[2024]]},
            "DOI": "10.1000/example",
        },
        {
            "id": "PMID:12345",
            "type": "article-journal",
            "title": "PubMed-only article",
            "author": [{"literal": "Single Name"}],
            "issued": {"date-parts": [[2020]]},
            "PMID": "12345",
            "URL": "https://pubmed.ncbi.nlm.nih.gov/12345/",
        },
    ]
    exported_text = output.read_text(encoding="utf-8")
    assert "PRIVATE OR CACHED CONTENT" not in exported_text
    assert "local_pdf_path" not in exported_text
    assert "Scanned: 5" in result.output
    assert "Exported: 2" in result.output
    assert "Duplicates: 1" in result.output
    assert "Skipped with full text: 1" in result.output
    assert "Skipped without DOI/PMID: 1" in result.output


def test_cache_export_all_includes_records_that_already_have_full_text(tmp_path):
    """The explicit --all mode exports an otherwise eligible full-text record."""
    cache_dir = tmp_path / "references_cache"
    cache_dir.mkdir()
    _write_reference(
        cache_dir,
        "full.md",
        reference_id="DOI:10.1000/full",
        title="Full text record",
        doi="10.1000/full",
        content_type="full_text_pdf",
    )
    output = tmp_path / "all.json"

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "export",
            "--cache-dir",
            str(cache_dir),
            "--all",
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(output.read_text(encoding="utf-8"))[0]["DOI"] == "10.1000/full"


def test_cache_export_refuses_to_overwrite_without_force(tmp_path):
    """Export does not silently replace an existing Zotero import file."""
    cache_dir = tmp_path / "references_cache"
    cache_dir.mkdir()
    output = tmp_path / "existing.json"
    output.write_text("keep me", encoding="utf-8")

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "export",
            "--cache-dir",
            str(cache_dir),
            "--output",
            str(output),
        ],
    )

    assert result.exit_code == 2
    assert "already exists" in result.output
    assert output.read_text(encoding="utf-8") == "keep me"

    forced = CliRunner().invoke(
        app,
        [
            "cache",
            "export",
            "--cache-dir",
            str(cache_dir),
            "--output",
            str(output),
            "--force",
        ],
    )

    assert forced.exit_code == 0, forced.output
    assert json.loads(output.read_text(encoding="utf-8")) == []


def test_cache_export_rejects_unknown_format(tmp_path):
    """Only the documented CSL JSON format is accepted initially."""
    cache_dir = tmp_path / "references_cache"
    cache_dir.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "export",
            "--cache-dir",
            str(cache_dir),
            "--format",
            "ris",
            "--output",
            str(tmp_path / "output.ris"),
        ],
    )

    assert result.exit_code == 2
    assert "Unsupported export format" in result.output
