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


class _UnavailableProvider(FullTextProvider):
    """Provider representing a Zotero API that is entirely unavailable."""

    calls = 0

    @classmethod
    def name(cls) -> str:
        """Return the provider name used by the fail-fast test."""
        return "unavailable_provider"

    def locate(self, ids, config):
        """Raise the same connection failure for every attempted reference."""
        type(self).calls += 1
        raise ConnectionError("connection refused")


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


def test_cache_enrich_fails_fast_after_repeated_provider_errors(tmp_path):
    """A dead Zotero service does not produce one error for every cache entry."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for number in range(5):
        _write_cached_reference(
            cache_dir, f"DOI:10.1000/{number}", f"10.1000/{number}"
        )
    _UnavailableProvider.calls = 0
    FullTextProviderRegistry.register(_UnavailableProvider)

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "enrich",
            "--provider",
            "unavailable_provider",
            "--cache-dir",
            str(cache_dir),
        ],
    )

    assert result.exit_code == 1
    assert _UnavailableProvider.calls == 3
    assert "Stopping after 3 consecutive provider errors" in result.output
    assert "Scanned: 3" in result.output


def test_cache_enrich_filters_by_reference_and_referenced_in(tmp_path, monkeypatch):
    """--reference and --referenced-in restrict enrichment to the selected references."""
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _write_cached_reference(cache_dir, "DOI:10.1000/hit", "10.1000/hit")
    _write_cached_reference(cache_dir, "DOI:10.1000/other", "10.1000/other")
    kb_file = tmp_path / "entry.yaml"
    kb_file.write_text("reference: DOI:10.1000/hit\n", encoding="utf-8")
    FullTextProviderRegistry.register(_PrivateHitProvider)

    by_ref = CliRunner().invoke(
        app,
        [
            "cache",
            "enrich",
            "--provider",
            "private_hit",
            "--cache-dir",
            str(cache_dir),
            "--reference",
            "doi:10.1000/HIT",
            "--dry-run",
        ],
    )
    assert by_ref.exit_code == 0, by_ref.output
    assert "Scanned: 1" in by_ref.output
    assert "Found: 1" in by_ref.output
    assert "DOI:10.1000/other" not in by_ref.output

    by_glob = CliRunner().invoke(
        app,
        [
            "cache",
            "enrich",
            "--provider",
            "private_hit",
            "--cache-dir",
            str(cache_dir),
            "--referenced-in",
            "entry.yaml",
            "--dry-run",
        ],
    )
    assert by_glob.exit_code == 0, by_glob.output
    assert "Scanned: 1" in by_glob.output
    assert "Found: 1" in by_glob.output
    assert "DOI:10.1000/other" not in by_glob.output


def test_cache_enrich_referenced_in_no_matches_exits_2(tmp_path, monkeypatch):
    """--referenced-in with a glob matching no files exits with code 2."""
    monkeypatch.chdir(tmp_path)
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _write_cached_reference(cache_dir, "DOI:10.1000/hit", "10.1000/hit")
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
            "--referenced-in",
            "does_not_match_*.yaml",
            "--dry-run",
        ],
    )
    assert result.exit_code == 2
    assert "matches no files" in result.output


def test_cache_enrich_warns_when_requested_reference_not_in_cache(tmp_path):
    """--reference with an uncached ID emits a warning instead of failing silently."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _write_cached_reference(cache_dir, "DOI:10.1000/hit", "10.1000/hit")
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
            "--reference",
            "PMID:99999999",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "PMID:99999999" in result.output
    assert "Scanned: 0" in result.output


def test_cache_enrich_missing_zotero_sqlite_reports_clear_error(tmp_path):
    """A missing zotero.sqlite surfaces ZoteroAPIError in cache enrich output."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _write_cached_reference(cache_dir, "DOI:10.1000/hit", "10.1000/hit")
    empty_zotero = tmp_path / "EmptyZotero"
    empty_zotero.mkdir()

    result = CliRunner().invoke(
        app,
        [
            "cache",
            "enrich",
            "--provider",
            "zotero",
            "--cache-dir",
            str(cache_dir),
            "--zotero-dir",
            str(empty_zotero),
            "--dry-run",
        ],
    )
    assert result.exit_code == 1
    assert "Zotero database not found" in result.output

