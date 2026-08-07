"""Tests for inventorying and enriching a cache from one full-text provider."""

from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)
from linkml_reference_validator.models import FullTextLocation


class _PrivateHitProvider(FullTextProvider):
    """Test provider that finds one DOI without mocking validator internals."""

    @classmethod
    def name(cls) -> str:
        """Return the provider name used by the CLI tests."""
        return "private_hit"

    def locate(self, ids, config):
        """Return full text only for the cache fixture DOI."""
        if ids.doi != "10.1000/hit":
            return None
        return FullTextLocation(
            text="private manuscript body " * 30,
            format_hint="text",
            provider=self.name(),
            access_type="user_library",
            source_item_id="ATTACHMENT1",
        )


def _write_cached_reference(cache_dir, reference_id: str, doi: str) -> None:
    """Write a minimal valid Markdown cache entry."""
    safe_id = reference_id.replace(":", "_").replace("/", "_")
    (cache_dir / f"{safe_id}.md").write_text(
        "---\n"
        f"reference_id: {reference_id}\n"
        f"doi: {doi}\n"
        "content_type: abstract_only\n"
        "full_text_attempted: true\n"
        "---\n\n"
        "abstract text\n",
        encoding="utf-8",
    )


def _write_full_text_reference(cache_dir, reference_id: str, doi: str) -> None:
    """Write a cache entry that must not be enriched a second time."""
    safe_id = reference_id.replace(":", "_").replace("/", "_")
    (cache_dir / f"{safe_id}.md").write_text(
        "---\n"
        f"reference_id: {reference_id}\n"
        f"doi: {doi}\n"
        "content_type: full_text_pdf\n"
        "full_text_attempted: true\n"
        "---\n\n"
        "existing full text\n",
        encoding="utf-8",
    )


def test_cache_enrich_dry_run_reports_hit_without_mutating_cache(tmp_path):
    """Dry-run inventories exact provider hits and leaves cache bytes unchanged."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _write_cached_reference(cache_dir, "DOI:10.1000/hit", "10.1000/hit")
    _write_cached_reference(cache_dir, "DOI:10.1000/miss", "10.1000/miss")
    hit_path = cache_dir / "DOI_10.1000_hit.md"
    private_cache_dir = tmp_path / "private-cache"
    original = hit_path.read_bytes()
    FullTextProviderRegistry.register(_PrivateHitProvider)

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "enrich",
            "--provider",
            "private_hit",
            "--cache-dir",
            str(cache_dir),
            "--private-cache-dir",
            str(private_cache_dir),
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "DOI:10.1000/hit\tfound\tprivate_hit:ATTACHMENT1" in result.output
    assert "DOI:10.1000/miss\tnot_found\t-" in result.output
    assert "Found: 1" in result.output
    assert hit_path.read_bytes() == original
    assert not private_cache_dir.exists()


def test_cache_enrich_apply_persists_private_text_and_provenance(tmp_path):
    """Apply writes a private research cache and leaves the public source unchanged."""
    cache_dir = tmp_path / "cache"
    private_cache_dir = tmp_path / "private-cache"
    cache_dir.mkdir()
    _write_cached_reference(cache_dir, "DOI:10.1000/hit", "10.1000/hit")
    public_path = cache_dir / "DOI_10.1000_hit.md"
    original = public_path.read_bytes()
    FullTextProviderRegistry.register(_PrivateHitProvider)

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "enrich",
            "--provider",
            "private_hit",
            "--cache-dir",
            str(cache_dir),
            "--private-cache-dir",
            str(private_cache_dir),
            "--apply",
        ],
    )

    assert result.exit_code == 0, result.output
    assert public_path.read_bytes() == original
    private_path = private_cache_dir / "DOI_10.1000_hit.md"
    cached = private_path.read_text(encoding="utf-8")
    assert "content_type: full_text" in cached
    assert "full_text_provider: private_hit" in cached
    assert "full_text_access_type: user_library" in cached
    assert "full_text_source_item_id: ATTACHMENT1" in cached
    assert "private manuscript body" in cached
    assert private_path.stat().st_mode & 0o777 == 0o600
    assert private_cache_dir.stat().st_mode & 0o777 == 0o700
    assert f"Private cache: {private_cache_dir}" in result.output


def test_cache_enrich_rejects_unknown_provider(tmp_path):
    """An unknown provider is a configuration error, not a cache-wide miss."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "enrich",
            "--provider",
            "does_not_exist",
            "--cache-dir",
            str(cache_dir),
        ],
    )

    assert result.exit_code == 2
    assert "Unknown full-text provider" in result.output


def test_cache_enrich_skips_references_that_already_have_full_text(tmp_path):
    """Existing full text is never duplicated or replaced by a library scan."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _write_full_text_reference(cache_dir, "DOI:10.1000/hit", "10.1000/hit")
    path = cache_dir / "DOI_10.1000_hit.md"
    original = path.read_bytes()
    FullTextProviderRegistry.register(_PrivateHitProvider)

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "enrich",
            "--provider",
            "private_hit",
            "--cache-dir",
            str(cache_dir),
            "--apply",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "DOI:10.1000/hit\talready_full_text\t-" in result.output
    assert path.read_bytes() == original
