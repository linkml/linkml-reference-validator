"""Cache subcommands for linkml-reference-validator."""

import logging

import typer
from typing_extensions import Annotated

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
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
