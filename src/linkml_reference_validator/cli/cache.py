"""Cache subcommands for linkml-reference-validator."""

import json
import logging
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.etl.csl_export import (
    export_identity,
    reference_to_csl_json,
)
from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
from .shared import (
    CacheDirOption,
    VerboseOption,
    ForceOption,
    ConfigFileOption,
    setup_logging,
    load_validation_config,
)

logger = logging.getLogger(__name__)

# Option for showing file content
ContentOption = Annotated[
    bool,
    typer.Option(
        "--content",
        help="Show file content instead of just the path",
    ),
]

# Option for bypassing cache
NoCacheOption = Annotated[
    bool,
    typer.Option(
        "--no-cache",
        help="Bypass disk cache and fetch fresh from source",
    ),
]

# Create the cache subcommand group
cache_app = typer.Typer(
    help="Manage reference cache",
    no_args_is_help=True,
)

ProviderOption = Annotated[
    str,
    typer.Option(
        "--provider",
        help="Registered full-text provider to use (for example: zotero)",
    ),
]

DryRunOption = Annotated[
    bool,
    typer.Option(
        "--dry-run/--apply",
        help="Report matches without changing cache files, or apply usable matches",
    ),
]

PrivateCacheDirOption = Annotated[
    Optional[Path],
    typer.Option(
        "--private-cache-dir",
        help=(
            "Destination for private full text. Defaults outside the project to "
            "~/.cache/linkml-reference-validator/private"
        ),
    ),
]

ExportOutputOption = Annotated[
    Path,
    typer.Option(
        "--output",
        "-o",
        help="Destination CSL JSON file for Zotero import",
    ),
]

ExportFormatOption = Annotated[
    str,
    typer.Option(
        "--format",
        help="Bibliographic export format (currently: csl-json)",
    ),
]

NeedsFullTextOption = Annotated[
    bool,
    typer.Option(
        "--needs-full-text/--all",
        help="Export only records needing full text, or all publication records",
    ),
]

ExportForceOption = Annotated[
    bool,
    typer.Option(
        "--force",
        "-f",
        help="Replace the output file if it already exists",
    ),
]


@cache_app.command(name="reference")
def reference_command(
    reference_id: Annotated[str, typer.Argument(help="Reference ID (e.g., PMID:12345678 or DOI:10.1234/example)")],
    config_file: ConfigFileOption = None,
    cache_dir: CacheDirOption = None,
    force: ForceOption = False,
    verbose: VerboseOption = False,
):
    """Cache a reference for offline use.

    Downloads and caches the full text of a reference for offline validation.
    Useful for pre-populating the cache or ensuring a reference is available.

    Examples:

        linkml-reference-validator cache reference PMID:12345678

        linkml-reference-validator cache reference PMID:12345678 --force --verbose

        linkml-reference-validator cache reference DOI:10.1038/nature12373
    """
    setup_logging(verbose)

    config = load_validation_config(config_file)
    if cache_dir:
        config.cache_dir = cache_dir

    fetcher = ReferenceFetcher(config)

    typer.echo(f"Fetching {reference_id}...")

    reference = fetcher.fetch(reference_id, force_refresh=force)

    if reference:
        typer.echo(f"Successfully cached {reference_id}")
        typer.echo(f"  Title: {reference.title}")
        if reference.authors:
            typer.echo(f"  Authors: {', '.join(reference.authors[:3])}")
        typer.echo(f"  Content type: {reference.content_type}")
        if reference.content:
            typer.echo(f"  Content length: {len(reference.content)} characters")
        raise typer.Exit(0)
    else:
        typer.echo(f"Failed to fetch {reference_id}", err=True)
        raise typer.Exit(1)


@cache_app.command(name="lookup")
def lookup_command(
    reference_id: Annotated[str, typer.Argument(help="Reference ID (e.g., PMID:12345678)")],
    config_file: ConfigFileOption = None,
    cache_dir: CacheDirOption = None,
    content: ContentOption = False,
    no_cache: NoCacheOption = False,
    verbose: VerboseOption = False,
):
    """Look up a cached reference and return its file path.

    Returns the path to the frontmatter file for the given reference ID.
    Use --content to display the file contents instead of just the path.
    Use --no-cache to bypass the disk cache and fetch fresh from the source.

    Examples:

        linkml-reference-validator cache lookup PMID:12345678

        linkml-reference-validator cache lookup PMID:12345678 --content

        linkml-reference-validator cache lookup PMID:12345678 --no-cache
    """
    setup_logging(verbose)

    config = load_validation_config(config_file)
    if cache_dir:
        config.cache_dir = cache_dir

    fetcher = ReferenceFetcher(config)

    # Get the cache path for this reference
    normalized_id = fetcher.normalize_reference_id(reference_id)
    cache_path = fetcher.get_cache_path(normalized_id)

    if no_cache:
        # Fetch fresh from source
        reference = fetcher.fetch(reference_id, force_refresh=True)
        if not reference:
            typer.echo(f"Reference {reference_id} not found or could not be fetched", err=True)
            raise typer.Exit(1)
        # Re-get cache path after fetch (in case it was normalized differently)
        cache_path = fetcher.get_cache_path(reference.reference_id)

    if not cache_path.exists():
        typer.echo(f"Reference {reference_id} is not cached", err=True)
        raise typer.Exit(1)

    if content:
        typer.echo(cache_path.read_text(encoding="utf-8"))
    else:
        typer.echo(str(cache_path.absolute()))


@cache_app.command(name="enrich")
def enrich_command(
    provider: ProviderOption = "zotero",
    config_file: ConfigFileOption = None,
    cache_dir: CacheDirOption = None,
    private_cache_dir: PrivateCacheDirOption = None,
    dry_run: DryRunOption = True,
    verbose: VerboseOption = False,
):
    """Inventory or enrich cached references from one full-text provider.

    Dry-run is the default and never changes cache files. Use ``--apply`` only
    after reviewing matches; private full text may be copyrighted and should not
    be committed or shared.

    Examples:

        linkml-reference-validator cache enrich --provider zotero --dry-run

        linkml-reference-validator cache enrich --provider zotero --apply
    """
    setup_logging(verbose)

    if FullTextProviderRegistry.get(provider) is None:
        typer.echo(f"Unknown full-text provider: {provider}", err=True)
        raise typer.Exit(2)

    config = load_validation_config(config_file)
    if cache_dir:
        config.cache_dir = cache_dir
    if private_cache_dir:
        config.private_cache_dir = private_cache_dir
    fetcher = ReferenceFetcher(config)

    found = 0
    applied = 0
    errors = 0
    references = fetcher.iter_cached_references()
    for reference in references:
        if not fetcher.needs_full_text(reference):
            typer.echo(f"{reference.reference_id}\talready_full_text\t-")
            continue
        try:  # provider is an external-system boundary
            location = fetcher.locate_full_text(reference, provider)
        except Exception as exc:
            errors += 1
            typer.echo(f"{reference.reference_id}\terror\t{exc}")
            continue

        if location is None:
            typer.echo(f"{reference.reference_id}\tnot_found\t-")
            continue

        found += 1
        source = f"{location.provider or provider}:{location.source_item_id or '-'}"
        if dry_run:
            typer.echo(f"{reference.reference_id}\tfound\t{source}")
            continue

        if fetcher.apply_full_text_location(
            reference, location, provider, private=True
        ):
            applied += 1
            typer.echo(f"{reference.reference_id}\tapplied\t{source}")
        else:
            typer.echo(f"{reference.reference_id}\tunusable\t{source}")

    typer.echo(f"Scanned: {len(references)}")
    typer.echo(f"Found: {found}")
    if not dry_run:
        typer.echo(f"Applied: {applied}")
        typer.echo(f"Private cache: {config.private_cache_dir.expanduser()}")
    if errors:
        typer.echo(f"Errors: {errors}", err=True)
        raise typer.Exit(1)


@cache_app.command(name="export")
def export_command(
    output: ExportOutputOption,
    export_format: ExportFormatOption = "csl-json",
    needs_full_text: NeedsFullTextOption = True,
    config_file: ConfigFileOption = None,
    cache_dir: CacheDirOption = None,
    force: ExportForceOption = False,
    verbose: VerboseOption = False,
):
    """Export public bibliographic metadata for import into Zotero.

    The export is an allowlisted CSL JSON projection. It never contains cached
    article text, excerpts, PDFs, local paths, or private-cache data. By default,
    only DOI/PMID records that still need full text are included.
    """
    setup_logging(verbose)

    if export_format != "csl-json":
        typer.echo(f"Unsupported export format: {export_format}", err=True)
        raise typer.Exit(2)
    if output.exists() and not force:
        typer.echo(
            f"Output already exists: {output}. Use --force to replace it.",
            err=True,
        )
        raise typer.Exit(2)

    config = load_validation_config(config_file)
    if cache_dir:
        config.cache_dir = cache_dir
    fetcher = ReferenceFetcher(config)
    references = fetcher.iter_cached_references()

    records: list[dict[str, object]] = []
    seen: set[str] = set()
    duplicates = 0
    skipped_full_text = 0
    skipped_identifier = 0
    for reference in references:
        if needs_full_text and not fetcher.needs_full_text(reference):
            skipped_full_text += 1
            continue
        identity = export_identity(reference)
        if identity is None:
            skipped_identifier += 1
            continue
        if identity in seen:
            duplicates += 1
            continue
        record = reference_to_csl_json(reference)
        if record is None:
            skipped_identifier += 1
            continue
        seen.add(identity)
        records.append(record)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(records, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    typer.echo(f"Scanned: {len(references)}")
    typer.echo(f"Exported: {len(records)}")
    typer.echo(f"Duplicates: {duplicates}")
    typer.echo(f"Skipped with full text: {skipped_full_text}")
    typer.echo(f"Skipped without DOI/PMID: {skipped_identifier}")
    typer.echo(f"Output: {output}")
