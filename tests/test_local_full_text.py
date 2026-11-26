"""Validate a cited reference against a local full-text file (#174, part 1).

A curator may hold the full text of a closed paper licensed for their own use.
The data cites the paper by its real identifier, quotes are matched against the
local file, and none of the file's text is written to any cache.
"""

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

DOI = "DOI:10.1016/j.ajodo.2025.11.017"
STEM = "DOI_10.1016_j.ajodo.2025.11.017"
TITLE = "A removable activator for Class II correction"
QUOTE = "The T-appliance is a removable activator supported by both the maxilla and the mandible."
BODY = f"# {TITLE}\n\nIntroduction.\n\n{QUOTE} It was worn full time.\n"


@pytest.fixture
def config(tmp_path):
    """A config whose public cache holds a metadata-only entry for ``DOI``."""
    base = tmp_path / "repo"
    base.mkdir()
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        private_cache_dir=tmp_path / "private",
        reference_base_dir=base,
        fetch_full_text=False,
    )
    ReferenceFetcher(config)._save_to_disk(
        ReferenceContent(
            reference_id=DOI,
            title=TITLE,
            content=None,
            content_type="unavailable",
            full_text_attempted=True,
        )
    )
    return config


@pytest.fixture
def paper(config):
    """The local full text, under the repo's reference base dir."""
    path = config.reference_base_dir / "papers" / "ajodo.md"
    path.parent.mkdir()
    path.write_text(BODY, encoding="utf-8")
    return path


def all_cache_text(config):
    """Concatenated text of every file in either cache."""
    return "".join(
        p.read_text(encoding="utf-8")
        for d in (config.cache_dir, config.private_cache_dir)
        if d.exists()
        for p in d.rglob("*")
        if p.is_file()
    )


def test_without_a_mapping_the_quote_has_no_content(config):
    result = SupportingTextValidator(config).validate(QUOTE, DOI)
    assert not result.is_valid
    assert "No content available" in result.message


def test_mapped_file_validates_the_doi_quote(config, paper):
    config.local_full_text = {DOI: "papers/ajodo.md"}
    result = SupportingTextValidator(config).validate(QUOTE, DOI, expected_title=TITLE)
    assert result.is_valid, result.message
    assert result.reference_id == DOI
    assert "title validated" in result.message


def test_mapped_text_is_never_cached(config, paper):
    config.local_full_text = {DOI: "papers/ajodo.md"}
    assert SupportingTextValidator(config).validate(QUOTE, DOI).is_valid
    assert "It was worn full time" not in all_cache_text(config)
    assert "supported by both the maxilla" not in all_cache_text(config)


def test_mapping_keys_are_normalized(config, paper):
    config.local_full_text = {"doi:10.1016/J.AJODO.2025.11.017": "papers/ajodo.md"}
    assert SupportingTextValidator(config).validate(QUOTE, DOI).is_valid


def test_mapping_accepts_an_absolute_path(config, paper):
    config.local_full_text = {DOI: str(paper)}
    assert SupportingTextValidator(config).validate(QUOTE, DOI).is_valid


def test_local_full_text_dir_is_keyed_by_cache_stem(config, tmp_path):
    papers = tmp_path / "private_papers"
    papers.mkdir()
    (papers / f"{STEM}.md").write_text(BODY, encoding="utf-8")
    config.local_full_text_dir = papers
    assert SupportingTextValidator(config).validate(QUOTE, DOI).is_valid


def test_local_full_text_dir_reads_txt(config, tmp_path):
    papers = tmp_path / "private_papers"
    papers.mkdir()
    (papers / f"{STEM}.txt").write_text(BODY, encoding="utf-8")
    config.local_full_text_dir = papers
    assert SupportingTextValidator(config).validate(QUOTE, DOI).is_valid


def test_missing_mapped_file_falls_back_to_the_usual_fetch(config):
    """In CI the file is absent: validation behaves as if nothing were mapped."""
    config.local_full_text = {DOI: "papers/absent.md"}
    result = SupportingTextValidator(config).validate(QUOTE, DOI)
    assert not result.is_valid
    assert "No content available" in result.message


def test_mapped_file_takes_precedence_over_cached_text(config, paper):
    fetcher = ReferenceFetcher(config)
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=DOI,
            title=TITLE,
            content="An abstract that does not contain the quote.",
            content_type="abstract_only",
            full_text_attempted=True,
        )
    )
    config.local_full_text = {DOI: "papers/ajodo.md"}
    ref = ReferenceFetcher(config).fetch(DOI)
    assert QUOTE in ref.content
    assert ref.content_type == "local_full_text"
    assert ref.title == TITLE
    assert "An abstract that does not contain" in all_cache_text(config)


def test_local_text_does_not_leak_into_the_memory_cache(config, paper):
    """Re-reading picks up an edit, as with ``file:``."""
    config.local_full_text = {DOI: "papers/ajodo.md"}
    fetcher = ReferenceFetcher(config)
    assert QUOTE in fetcher.fetch(DOI).content
    paper.write_text("Rewritten.", encoding="utf-8")
    assert fetcher.fetch(DOI).content == "Rewritten."


def test_local_full_text_path_lookup(config, paper, tmp_path):
    config.local_full_text = {DOI: "papers/ajodo.md"}
    fetcher = ReferenceFetcher(config)
    assert fetcher.local_full_text_path(DOI) == paper
    assert fetcher.local_full_text_path("PMID:1") is None


def test_local_full_text_dir_expands_home(config, tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    papers = tmp_path / "private_papers"
    papers.mkdir()
    (papers / f"{STEM}.md").write_text(BODY, encoding="utf-8")
    config.local_full_text_dir = "~/private_papers"
    assert SupportingTextValidator(config).validate(QUOTE, DOI).is_valid


def test_relative_local_full_text_dir_resolves_against_base_dir(config, tmp_path, monkeypatch):
    papers = config.reference_base_dir / "private_papers"
    papers.mkdir()
    (papers / f"{STEM}.md").write_text(BODY, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    config.local_full_text_dir = "private_papers"
    assert SupportingTextValidator(config).validate(QUOTE, DOI).is_valid


def test_cache_reference_reports_the_cached_text_not_the_local_file(config, paper):
    from typer.testing import CliRunner

    from linkml_reference_validator.cli import app

    cfg = config.reference_base_dir / "lrv.yaml"
    cfg.write_text(
        "validation:\n"
        f"  cache_dir: {config.cache_dir}\n"
        f"  reference_base_dir: {config.reference_base_dir}\n"
        "  fetch_full_text: false\n"
        "  local_full_text:\n"
        f"    {DOI}: papers/ajodo.md\n",
        encoding="utf-8",
    )
    result = CliRunner().invoke(app, ["cache", "reference", DOI, "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert "Content type: unavailable" in result.output
    assert "local_full_text" not in result.output


def test_local_full_text_strips_cache_frontmatter_and_header(config, tmp_path):
    """A cache-formatted .md file in local_full_text_dir exposes only its Content body."""
    private_dir = tmp_path / "private_cache"
    private_dir.mkdir()
    (private_dir / f"{STEM}.md").write_text(
        "---\n"
        f"reference_id: {DOI}\n"
        f"title: {TITLE}\n"
        "authors:\n"
        "- Secret Author Name\n"
        "content_type: full_text_pdf\n"
        "---\n\n"
        f"# {TITLE}\n"
        "**Authors:** Secret Author Name\n\n"
        "## Content\n\n"
        f"{QUOTE}\n",
        encoding="utf-8",
    )
    config.local_full_text_dir = private_dir
    validator = SupportingTextValidator(config)
    assert validator.validate(QUOTE, DOI).is_valid
    assert not validator.validate("Secret Author Name", DOI).is_valid


def test_local_full_text_extracts_pdf_files(config, tmp_path):
    """A .pdf file in local_full_text_dir is extracted via PDFExtractor."""
    from tests.test_extractors import _build_minimal_pdf

    papers = tmp_path / "pdf_papers"
    papers.mkdir()
    pdf_bytes = _build_minimal_pdf(QUOTE)
    (papers / f"{STEM}.pdf").write_bytes(pdf_bytes)
    config.local_full_text_dir = papers
    assert SupportingTextValidator(config).validate(QUOTE, DOI).is_valid
