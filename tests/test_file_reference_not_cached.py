"""A ``file:`` reference is not copied into any cache unless asked for (#173).

The usual reason to cite ``file:`` rather than ``DOI:`` is that the file is a
paper the project may not redistribute. ``cache_dir`` is usually committed, so
writing the file's text there publishes it.
"""

import os

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

TEXT = "The T-appliance is a removable activator supported by both jaws."
SVG = '<svg xmlns="http://www.w3.org/2000/svg"><text>PTEN activates AKT</text></svg>'
DRAWIO = (
    '<mxfile><diagram><mxGraphModel><root><mxCell id="0"/>'
    '<mxCell id="2" value="PTEN activates AKT" vertex="1" parent="0"/>'
    "</root></mxGraphModel></diagram></mxfile>"
)


@pytest.fixture
def config(tmp_path):
    """A config with its own public and private caches and a reference base dir."""
    base = tmp_path / "refs"
    base.mkdir()
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        private_cache_dir=tmp_path / "private",
        reference_base_dir=base,
    )


def cache_files(config):
    """Every file written under either cache."""
    return [
        p
        for d in (config.cache_dir, config.private_cache_dir)
        if d.exists()
        for p in d.rglob("*")
        if p.is_file()
    ]


@pytest.mark.parametrize(
    "name,body,quote",
    [
        ("paper.md", TEXT, "removable activator"),
        ("paper.txt", TEXT, "removable activator"),
        ("fig.svg", SVG, "PTEN activates AKT"),
        ("fig.drawio", DRAWIO, "PTEN activates AKT"),
    ],
)
def test_validating_a_file_reference_writes_no_cache(config, name, body, quote):
    (config.reference_base_dir / name).write_text(body, encoding="utf-8")
    result = SupportingTextValidator(config).validate(quote, f"file:{name}")
    assert result.is_valid, result.message
    assert cache_files(config) == []


def test_cache_local_files_defaults_off():
    assert ReferenceValidationConfig().cache_local_files is False


def test_opt_in_writes_the_entry(config):
    config.cache_local_files = True
    (config.reference_base_dir / "notes.md").write_text(TEXT, encoding="utf-8")
    fetcher = ReferenceFetcher(config)
    assert fetcher.fetch("file:notes.md").content == TEXT
    written = list(config.cache_dir.glob("*.md"))
    assert len(written) == 1
    assert TEXT in written[0].read_text(encoding="utf-8")


def test_opt_in_entry_names_no_absolute_path(config):
    config.cache_local_files = True
    sub = config.reference_base_dir / "papers"
    sub.mkdir()
    (sub / "notes.md").write_text(TEXT, encoding="utf-8")
    fetcher = ReferenceFetcher(config)
    ref = fetcher.fetch(f"file:{sub / 'notes.md'}")
    assert ref.reference_id == "file:papers/notes.md"
    [written] = config.cache_dir.glob("*.md")
    assert written.name == "file_papers_notes.md.md"
    text = written.read_text(encoding="utf-8")
    assert str(config.reference_base_dir) not in text
    assert "reference_id: file:papers/notes.md" in text


def test_relative_id_without_base_dir_is_relative_to_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "notes.md").write_text(TEXT, encoding="utf-8")
    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path / "cache"))
    assert fetcher.normalize_reference_id(f"file:{tmp_path / 'notes.md'}") == "file:notes.md"
    assert fetcher.fetch("file:./notes.md").reference_id == "file:notes.md"


def test_file_outside_the_base_dir_keeps_its_absolute_path(config, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text(TEXT, encoding="utf-8")
    fetcher = ReferenceFetcher(config)
    assert fetcher.normalize_reference_id(f"file:{outside}") == f"file:{os.path.abspath(outside)}"
    assert fetcher.fetch(f"file:{outside}").content == TEXT


def test_file_reference_still_sees_edits_without_a_cache(config):
    notes = config.reference_base_dir / "notes.md"
    notes.write_text("version one", encoding="utf-8")
    fetcher = ReferenceFetcher(config)
    assert fetcher.fetch("file:notes.md").content == "version one"
    notes.write_text("version two", encoding="utf-8")
    assert fetcher.fetch("file:notes.md").content == "version two"
    notes.unlink()
    assert fetcher.fetch("file:notes.md") is None
