"""Precedence of custom provider and source configs: explicit > project > user.

Both loaders accept ``project_dir`` and ``user_config_dir`` so these tests can
point them at temporary directories without touching ``HOME`` or the cwd.
See https://github.com/linkml/linkml-reference-validator/issues/123.
"""

from pathlib import Path

import pytest

from linkml_reference_validator.etl.fulltext.loader import (
    load_custom_full_text_providers,
)
from linkml_reference_validator.etl.sources.loader import load_custom_sources


# --- full-text providers -----------------------------------------------------


def _provider_yaml(providers: dict[str, str]) -> str:
    """Render a full-text providers YAML body from ``{name: url_template}``."""
    lines = ["full_text_providers:"]
    for name, url in providers.items():
        lines += [f"  {name}:", f"    url_template: {url}"]
    return "\n".join(lines) + "\n"


@pytest.fixture
def ft_dirs(tmp_path: Path) -> dict[str, Path]:
    """Explicit file, project dir and user config dir all defining ``shared``."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".linkml-reference-validator-fulltext.yaml").write_text(
        _provider_yaml(
            {
                "shared": "https://project.example/{doi}",
                "proj_user": "https://project.example/pu/{doi}",
                "proj_only": "https://project.example/only/{doi}",
            }
        )
    )

    user_config_dir = tmp_path / "userconf"
    (user_config_dir / "fulltext").mkdir(parents=True)
    (user_config_dir / "fulltext" / "u.yaml").write_text(
        _provider_yaml(
            {
                "shared": "https://user.example/{doi}",
                "proj_user": "https://user.example/pu/{doi}",
                "user_only": "https://user.example/only/{doi}",
            }
        )
    )

    explicit = tmp_path / "explicit.yaml"
    explicit.write_text(
        _provider_yaml(
            {
                "shared": "https://explicit.example/{doi}",
                "explicit_only": "https://explicit.example/only/{doi}",
            }
        )
    )
    return {"project": project_dir, "user": user_config_dir, "explicit": explicit}


def _ft_by_name(**kwargs) -> dict[str, str]:
    configs = load_custom_full_text_providers(**kwargs)
    return {c.name: c.url_template for c in configs}


def test_fulltext_explicit_beats_project_and_user(ft_dirs):
    got = _ft_by_name(
        providers_file=ft_dirs["explicit"],
        project_dir=ft_dirs["project"],
        user_config_dir=ft_dirs["user"],
    )
    assert got["shared"] == "https://explicit.example/{doi}"


def test_fulltext_project_beats_user(ft_dirs):
    got = _ft_by_name(project_dir=ft_dirs["project"], user_config_dir=ft_dirs["user"])
    assert got["shared"] == "https://project.example/{doi}"
    assert got["proj_user"] == "https://project.example/pu/{doi}"


def test_fulltext_names_unique_to_each_level_are_kept(ft_dirs):
    got = _ft_by_name(
        providers_file=ft_dirs["explicit"],
        project_dir=ft_dirs["project"],
        user_config_dir=ft_dirs["user"],
    )
    assert set(got) == {"shared", "proj_user", "proj_only", "user_only", "explicit_only"}
    assert got["user_only"] == "https://user.example/only/{doi}"


def test_fulltext_user_files_later_name_wins(tmp_path):
    """Within the user dir, files load in sorted order and the later one wins."""
    user_config_dir = tmp_path / "userconf"
    (user_config_dir / "fulltext").mkdir(parents=True)
    (user_config_dir / "fulltext" / "b.yaml").write_text(
        _provider_yaml({"x": "https://b.example/{doi}"})
    )
    (user_config_dir / "fulltext" / "a.yaml").write_text(
        _provider_yaml({"x": "https://a.example/{doi}"})
    )
    got = _ft_by_name(project_dir=tmp_path, user_config_dir=user_config_dir)
    assert got == {"x": "https://b.example/{doi}"}


# --- custom sources ----------------------------------------------------------


def _sources_yaml(sources: dict[str, str]) -> str:
    """Render a sources YAML body from ``{prefix: url_template}``."""
    lines = ["sources:"]
    for prefix, url in sources.items():
        lines += [
            f"  {prefix}:",
            f'    url_template: "{url}"',
            "    fields:",
            '      title: "$.title"',
        ]
    return "\n".join(lines) + "\n"


@pytest.fixture
def src_dirs(tmp_path: Path) -> dict[str, Path]:
    """sources_file, config_file, project dir and user dir all defining SHARED."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".linkml-reference-validator-sources.yaml").write_text(
        _sources_yaml(
            {
                "SHARED": "https://project.example/{id}",
                "PROJUSER": "https://project.example/pu/{id}",
                "PROJONLY": "https://project.example/only/{id}",
            }
        )
    )

    user_config_dir = tmp_path / "userconf"
    (user_config_dir / "sources").mkdir(parents=True)
    (user_config_dir / "sources" / "u.yaml").write_text(
        _sources_yaml(
            {
                "SHARED": "https://user.example/{id}",
                "PROJUSER": "https://user.example/pu/{id}",
                "USERONLY": "https://user.example/only/{id}",
            }
        )
    )

    config_file = tmp_path / "config.yaml"
    config_file.write_text(
        "cache_dir: references_cache\n"
        + _sources_yaml(
            {
                "SHARED": "https://config.example/{id}",
                "CONFIGSRC": "https://config.example/cs/{id}",
                "CONFIGONLY": "https://config.example/only/{id}",
            }
        )
    )

    sources_file = tmp_path / "sources.yaml"
    sources_file.write_text(
        _sources_yaml(
            {
                "SHARED": "https://sourcesfile.example/{id}",
                "CONFIGSRC": "https://sourcesfile.example/cs/{id}",
            }
        )
    )
    return {
        "project": project_dir,
        "user": user_config_dir,
        "config": config_file,
        "sources": sources_file,
    }


def _src_by_prefix(**kwargs) -> dict[str, str]:
    configs = load_custom_sources(**kwargs)
    return {c.prefix: c.url_template for c in configs}


def test_sources_file_beats_everything(src_dirs):
    got = _src_by_prefix(
        sources_file=src_dirs["sources"],
        config_file=src_dirs["config"],
        project_dir=src_dirs["project"],
        user_config_dir=src_dirs["user"],
    )
    assert got["SHARED"] == "https://sourcesfile.example/{id}"
    assert got["CONFIGSRC"] == "https://sourcesfile.example/cs/{id}"


def test_sources_file_beats_project_and_user(src_dirs):
    got = _src_by_prefix(
        sources_file=src_dirs["sources"],
        project_dir=src_dirs["project"],
        user_config_dir=src_dirs["user"],
    )
    assert got["SHARED"] == "https://sourcesfile.example/{id}"


def test_config_file_beats_project_and_user(src_dirs):
    got = _src_by_prefix(
        config_file=src_dirs["config"],
        project_dir=src_dirs["project"],
        user_config_dir=src_dirs["user"],
    )
    assert got["SHARED"] == "https://config.example/{id}"


def test_sources_project_beats_user(src_dirs):
    got = _src_by_prefix(project_dir=src_dirs["project"], user_config_dir=src_dirs["user"])
    assert got["SHARED"] == "https://project.example/{id}"
    assert got["PROJUSER"] == "https://project.example/pu/{id}"


def test_sources_prefixes_unique_to_each_level_are_kept(src_dirs):
    got = _src_by_prefix(
        sources_file=src_dirs["sources"],
        config_file=src_dirs["config"],
        project_dir=src_dirs["project"],
        user_config_dir=src_dirs["user"],
    )
    assert set(got) == {
        "SHARED",
        "CONFIGSRC",
        "CONFIGONLY",
        "PROJUSER",
        "PROJONLY",
        "USERONLY",
    }
    assert got["USERONLY"] == "https://user.example/only/{id}"
    assert got["CONFIGONLY"] == "https://config.example/only/{id}"


def test_sources_user_files_sorted_later_name_wins(tmp_path):
    """User-dir files (.yaml and .yml together) load in sorted order; later wins."""
    user_config_dir = tmp_path / "userconf"
    (user_config_dir / "sources").mkdir(parents=True)
    (user_config_dir / "sources" / "c.yml").write_text(
        _sources_yaml({"X": "https://c.example/{id}"})
    )
    (user_config_dir / "sources" / "b.yaml").write_text(
        _sources_yaml({"X": "https://b.example/{id}"})
    )
    (user_config_dir / "sources" / "a.yaml").write_text(
        _sources_yaml({"X": "https://a.example/{id}"})
    )
    got = _src_by_prefix(project_dir=tmp_path, user_config_dir=user_config_dir)
    assert got == {"X": "https://c.example/{id}"}


def test_sources_project_yaml_beats_project_yml(tmp_path):
    """If both project files exist, the canonical ``.yaml`` one wins."""
    (tmp_path / ".linkml-reference-validator-sources.yml").write_text(
        _sources_yaml({"X": "https://yml.example/{id}"})
    )
    (tmp_path / ".linkml-reference-validator-sources.yaml").write_text(
        _sources_yaml({"X": "https://yaml.example/{id}"})
    )
    got = _src_by_prefix(project_dir=tmp_path, user_config_dir=tmp_path / "none")
    assert got == {"X": "https://yaml.example/{id}"}
