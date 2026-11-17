"""Commands for managing signed excerpts synced from a private full-text store."""

from pathlib import Path
from typing import Optional

import typer
from ruamel.yaml import YAMLError  # type: ignore
from typing_extensions import Annotated

from linkml_reference_validator.signed_excerpts import sync_signed_excerpts
from .shared import ConfigFileOption, SignedExcerptsDirOption, load_validation_config

excerpts_app = typer.Typer(
    help="Manage signed excerpts synced from a private full-text store",
    no_args_is_help=True,
)


@excerpts_app.command(name="sync")
def sync_command(
    source: Annotated[
        Optional[Path],
        typer.Option(
            "--source",
            "-s",
            envvar="LRV_SIGNED_EXCERPTS_SOURCE",
            help=(
                "Signed excerpts directory in a local checkout of the private store "
                "(e.g. ../claimstore/signed_excerpts). Overrides signed_excerpts_sync.source_dir."
            ),
        ),
    ] = None,
    signed_excerpts_dir: SignedExcerptsDirOption = None,
    target_repo: Annotated[
        Optional[str],
        typer.Option(
            "--target-repo",
            help="Select bundles tagged for this repo in excerpt target_repo (e.g. dismech)",
        ),
    ] = None,
    referenced_in: Annotated[
        Optional[list[str]],
        typer.Option(
            "--referenced-in",
            help="Glob of data files; select bundles whose reference is cited there (repeatable)",
        ),
    ] = None,
    prune: Annotated[
        Optional[bool],
        typer.Option(
            "--prune/--no-prune",
            help="Remove destination bundles that are no longer selected",
        ),
    ] = None,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Write nothing; exit 1 if the destination is out of date",
        ),
    ] = False,
    config_file: ConfigFileOption = None,
):
    """Copy signed excerpt bundles from a private store into signed_excerpts_dir.

    Options given on the command line override the `signed_excerpts_sync`
    section of the config file.

    Examples:

        linkml-reference-validator excerpts sync --source ../claimstore/signed_excerpts

        linkml-reference-validator excerpts sync -s ../claimstore/signed_excerpts \\
            --signed-excerpts-dir signed_excerpts --target-repo dismech \\
            --referenced-in 'kb/disorders/*.yaml' --prune
    """
    config = load_validation_config(config_file, load_custom_sources=False)
    settings = config.signed_excerpts_sync

    source_dir = source or settings.source_dir
    if source_dir is None:
        typer.echo(
            "No source given: pass --source, set LRV_SIGNED_EXCERPTS_SOURCE, "
            "or set signed_excerpts_sync.source_dir in the config.",
            err=True,
        )
        raise typer.Exit(2)
    dest_dir = signed_excerpts_dir or config.signed_excerpts_dir
    if dest_dir is None:
        typer.echo(
            "No destination: pass --signed-excerpts-dir or set signed_excerpts_dir in the config.",
            err=True,
        )
        raise typer.Exit(2)
    # Problems with the private store or the selection are user errors, so
    # report them as such (exit 2) rather than as a traceback; exit 1 is
    # reserved for --check finding drift.
    try:
        report = sync_signed_excerpts(
            source_dir,
            dest_dir,
            target_repo=(target_repo if target_repo is not None else settings.target_repo)
            or None,
            referenced_in=referenced_in or settings.referenced_in,
            prune=prune if prune is not None else settings.prune,
            dry_run=check,
        )
    except FileNotFoundError as e:
        typer.echo(f"{e} (is the private store cloned there?)", err=True)
        raise typer.Exit(2)
    except (ValueError, YAMLError) as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(2)

    verb = "would be " if check else ""
    for label, names in [
        ("added", report.added),
        ("updated", report.updated),
        ("removed", report.removed),
    ]:
        for name in names:
            typer.echo(f"  {label}: {name}")
    typer.echo(
        f"{source_dir} -> {dest_dir}: {len(report.added)} {verb}added, "
        f"{len(report.updated)} {verb}updated, {len(report.removed)} {verb}removed, "
        f"{len(report.unchanged)} unchanged"
    )
    if check and report.changed:
        raise typer.Exit(1)
