"""Tests for syncing signed excerpt bundles from a private store into a public repo."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    SignedExcerptsSyncConfig,
)
from linkml_reference_validator.signed_excerpts import (
    find_cited_reference_ids,
    sync_signed_excerpts,
)

runner = CliRunner()

# Three bundles in the private store:
# - PMID_111: tagged for dismech via target_repo
# - PMID_222: tagged for another repo only
# - DOI_10.1000_abc: untagged, but cited by a dismech data file
BUNDLES = {
    "PMID_111.yaml": """\
reference_id: PMID:111
excerpts:
- text: First signed excerpt from a closed full text.
  target_repo:
  - dismech:kb/disorders/A.yaml
""",
    "PMID_222.yaml": """\
reference_id: PMID:222
excerpts:
- text: Second signed excerpt, used by another repo.
  target_repo:
  - ai-gene-review:genes/human/X/X-ai-review.yaml
""",
    "DOI_10.1000_abc.yaml": """\
reference_id: DOI:10.1000/abc
excerpts:
- text: Third signed excerpt with no target_repo tag.
""",
}


@pytest.fixture
def store(tmp_path: Path) -> Path:
    """A private store's signed_excerpts/ directory with three bundles."""
    source = tmp_path / "claimstore" / "signed_excerpts"
    source.mkdir(parents=True)
    for name, text in BUNDLES.items():
        (source / name).write_text(text)
    return source


@pytest.fixture
def downstream(tmp_path: Path) -> Path:
    """A public downstream repo whose data cites DOI:10.1000/abc and PMID:1111 (not PMID:111)."""
    repo = tmp_path / "dismech"
    kb = repo / "kb" / "disorders"
    kb.mkdir(parents=True)
    (kb / "B.yaml").write_text(
        "evidence:\n- reference: DOI:10.1000/abc\n- reference: PMID:1111\n"
    )
    return repo


def _names(directory: Path) -> set[str]:
    return {p.name for p in directory.glob("*.yaml")}


def test_sync_config_defaults():
    """Sync settings are optional and default to copying everything without pruning."""
    config = ReferenceValidationConfig()
    assert config.signed_excerpts_sync == SignedExcerptsSyncConfig()
    assert config.signed_excerpts_sync.source_dir is None
    assert config.signed_excerpts_sync.target_repo is None
    assert config.signed_excerpts_sync.referenced_in == []
    assert config.signed_excerpts_sync.prune is False


def test_find_cited_reference_ids_respects_identifier_boundaries(downstream):
    """PMID:111 must not be found inside PMID:1111; DOI matching ignores case."""
    found = find_cited_reference_ids(
        ["PMID:111", "PMID:1111", "doi:10.1000/ABC", "PMID:222"],
        [downstream / "kb" / "disorders" / "B.yaml"],
    )
    assert found == {"PMID:1111", "doi:10.1000/ABC"}


def test_sync_without_filters_copies_all_bundles_verbatim(store, tmp_path):
    """With no selection filters every bundle is copied byte-for-byte."""
    dest = tmp_path / "out"
    report = sync_signed_excerpts(store, dest)
    assert _names(dest) == set(BUNDLES)
    assert sorted(report.added) == sorted(BUNDLES)
    for name, text in BUNDLES.items():
        assert (dest / name).read_text() == text


def test_sync_selects_by_target_repo_or_citation(store, downstream):
    """A bundle is selected if tagged for the target repo OR cited in the repo's data."""
    dest = downstream / "signed_excerpts"
    report = sync_signed_excerpts(
        store,
        dest,
        target_repo="dismech",
        referenced_in=["kb/disorders/*.yaml"],
        base_dir=downstream,
    )
    assert _names(dest) == {"PMID_111.yaml", "DOI_10.1000_abc.yaml"}
    assert report.changed


def test_sync_reports_updates_and_unchanged(store, tmp_path):
    """A second sync is a no-op; editing a bundle upstream is reported as an update."""
    dest = tmp_path / "out"
    sync_signed_excerpts(store, dest)

    again = sync_signed_excerpts(store, dest)
    assert not again.changed
    assert sorted(again.unchanged) == sorted(BUNDLES)

    (store / "PMID_111.yaml").write_text(BUNDLES["PMID_111.yaml"] + "# revised\n")
    updated = sync_signed_excerpts(store, dest)
    assert updated.updated == ["PMID_111.yaml"]
    assert (dest / "PMID_111.yaml").read_text().endswith("# revised\n")


def test_sync_prune_removes_stale_bundles_only_when_asked(store, tmp_path):
    """Bundles no longer selected are kept by default and removed with prune=True."""
    dest = tmp_path / "out"
    dest.mkdir()
    (dest / "PMID_999.yaml").write_text("reference_id: PMID:999\nexcerpts: []\n")
    (dest / "README.md").write_text("not a bundle\n")

    kept = sync_signed_excerpts(store, dest)
    assert "PMID_999.yaml" in _names(dest)
    assert kept.removed == []

    pruned = sync_signed_excerpts(store, dest, prune=True)
    assert pruned.removed == ["PMID_999.yaml"]
    assert "PMID_999.yaml" not in _names(dest)
    assert (dest / "README.md").exists()


def test_sync_dry_run_writes_nothing(store, tmp_path):
    """dry_run reports pending changes without touching the destination."""
    dest = tmp_path / "out"
    report = sync_signed_excerpts(store, dest, dry_run=True)
    assert sorted(report.added) == sorted(BUNDLES)
    assert not dest.exists()


def test_sync_missing_source_raises(tmp_path):
    """A missing private store is a clear error, not a silent empty sync."""
    with pytest.raises(FileNotFoundError, match="claimstore"):
        sync_signed_excerpts(tmp_path / "claimstore" / "signed_excerpts", tmp_path / "out")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


@pytest.fixture
def configured_downstream(downstream: Path) -> Path:
    """Downstream repo with sync settings in .linkml-reference-validator.yaml."""
    (downstream / ".linkml-reference-validator.yaml").write_text(
        """\
validation:
  signed_excerpts_dir: signed_excerpts
  signed_excerpts_sync:
    target_repo: dismech
    referenced_in:
      - kb/disorders/*.yaml
    prune: true
"""
    )
    return downstream


def test_cli_sync_uses_config_and_source_option(store, configured_downstream, monkeypatch):
    """`excerpts sync --source` copies the selected bundles into signed_excerpts_dir."""
    monkeypatch.chdir(configured_downstream)
    result = runner.invoke(app, ["excerpts", "sync", "--source", str(store)])
    assert result.exit_code == 0, result.output
    assert _names(configured_downstream / "signed_excerpts") == {
        "PMID_111.yaml",
        "DOI_10.1000_abc.yaml",
    }
    assert "added" in result.output


def test_cli_sync_source_from_environment(store, configured_downstream, monkeypatch):
    """The source directory can come from LRV_SIGNED_EXCERPTS_SOURCE."""
    monkeypatch.chdir(configured_downstream)
    monkeypatch.setenv("LRV_SIGNED_EXCERPTS_SOURCE", str(store))
    result = runner.invoke(app, ["excerpts", "sync"])
    assert result.exit_code == 0, result.output
    assert (configured_downstream / "signed_excerpts" / "PMID_111.yaml").exists()


def test_cli_sync_check_fails_when_out_of_date(store, configured_downstream, monkeypatch):
    """`--check` writes nothing and exits 1 while the copy is stale, 0 once in sync."""
    monkeypatch.chdir(configured_downstream)
    stale = runner.invoke(app, ["excerpts", "sync", "--source", str(store), "--check"])
    assert stale.exit_code == 1
    assert not (configured_downstream / "signed_excerpts").exists()

    runner.invoke(app, ["excerpts", "sync", "--source", str(store)])
    fresh = runner.invoke(app, ["excerpts", "sync", "--source", str(store), "--check"])
    assert fresh.exit_code == 0, fresh.output


def test_cli_sync_without_source_explains(configured_downstream, monkeypatch):
    """With no source configured the command fails with a helpful message."""
    monkeypatch.chdir(configured_downstream)
    monkeypatch.delenv("LRV_SIGNED_EXCERPTS_SOURCE", raising=False)
    result = runner.invoke(app, ["excerpts", "sync"])
    assert result.exit_code != 0
    assert "--source" in result.output


def test_cli_sync_missing_source_dir(tmp_path, configured_downstream, monkeypatch):
    """A source path that does not exist (e.g. private repo not cloned) fails cleanly."""
    monkeypatch.chdir(configured_downstream)
    result = runner.invoke(
        app, ["excerpts", "sync", "--source", str(tmp_path / "nope")]
    )
    assert result.exit_code == 1
    assert "not found" in result.output
