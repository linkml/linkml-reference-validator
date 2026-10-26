"""A ``file:`` reference is always read from the file, never from a cache (#135)."""

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceValidationConfig


def svg(label: str) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg"><text>{label}</text></svg>'


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", reference_base_dir=tmp_path / "refs"
    )


@pytest.fixture
def notes(config):
    config.reference_base_dir.mkdir()
    path = config.reference_base_dir / "notes.md"
    path.write_text("version one", encoding="utf-8")
    return path


def test_new_fetcher_sees_an_edited_file(config, notes):
    assert ReferenceFetcher(config).fetch(f"file:{notes}").content == "version one"
    notes.write_text("version two", encoding="utf-8")
    assert ReferenceFetcher(config).fetch(f"file:{notes}").content == "version two"


def test_same_fetcher_sees_an_edited_file(config, notes):
    fetcher = ReferenceFetcher(config)
    assert fetcher.fetch(f"file:{notes}").content == "version one"
    notes.write_text("version two", encoding="utf-8")
    assert fetcher.fetch(f"file:{notes}").content == "version two"


def test_trusted_cache_does_not_hide_an_edit(config, notes):
    config.trust_cached_entries = True
    assert ReferenceFetcher(config).fetch(f"file:{notes}").content == "version one"
    notes.write_text("version two", encoding="utf-8")
    assert ReferenceFetcher(config).fetch(f"file:{notes}").content == "version two"


def test_deleted_file_is_not_served_from_the_cache(config, notes):
    fetcher = ReferenceFetcher(config)
    assert fetcher.fetch(f"file:{notes}") is not None
    notes.unlink()
    assert fetcher.fetch(f"file:{notes}") is None
    assert ReferenceFetcher(config).fetch(f"file:{notes}") is None


def test_relative_and_absolute_ids_share_one_entry(config, notes):
    fetcher = ReferenceFetcher(config)
    relative = fetcher.fetch("file:notes.md")
    absolute = fetcher.fetch(f"file:{notes}")
    assert relative.content == absolute.content == "version one"
    assert relative.reference_id == absolute.reference_id == f"file:{notes}"
    assert fetcher.get_cache_path("file:notes.md") == fetcher.get_cache_path(f"file:{notes}")
    assert fetcher.get_cache_path("file:./notes.md") == fetcher.get_cache_path(f"file:{notes}")
    assert [p.name for p in config.cache_dir.glob("*.md")] == [
        fetcher.get_cache_path(f"file:{notes}").name
    ]


def test_relative_id_normalizes_to_the_absolute_path(config, notes):
    fetcher = ReferenceFetcher(config)
    assert fetcher.normalize_reference_id("file:./notes.md") == f"file:{notes}"
    assert fetcher.normalize_reference_id("file:sub/../notes.md") == f"file:{notes}"


def test_relative_fetch_sees_an_edit(config, notes):
    fetcher = ReferenceFetcher(config)
    assert fetcher.fetch("file:notes.md").content == "version one"
    notes.write_text("version two", encoding="utf-8")
    assert fetcher.fetch(f"file:{notes}").content == "version two"
    assert ReferenceFetcher(config).fetch("file:notes.md").content == "version two"


def test_svg_figure_sees_an_edit(config):
    config.reference_base_dir.mkdir()
    figure = config.reference_base_dir / "fig.svg"
    figure.write_text(svg("PTEN"), encoding="utf-8")
    fetcher = ReferenceFetcher(config)
    assert fetcher.fetch("file:fig.svg").content == "PTEN"
    figure.write_text(svg("AKT"), encoding="utf-8")
    assert fetcher.fetch("file:fig.svg").content == "AKT"
    assert ReferenceFetcher(config).fetch(f"file:{figure}").content == "AKT"
    assert len(list(config.cache_dir.glob("*.md"))) == 1
