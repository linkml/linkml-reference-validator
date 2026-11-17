"""Commands for producing and syncing signed excerpts."""

from pathlib import Path
from typing import Optional

import typer
from ruamel.yaml import YAMLError  # type: ignore
from typing_extensions import Annotated

from linkml_reference_validator.excerpt_signing import sign_excerpts
from linkml_reference_validator.signed_excerpts import sync_signed_excerpts
from .shared import ConfigFileOption, SignedExcerptsDirOption, load_validation_config

excerpts_app = typer.Typer(
    help="Sign excerpts against local full text, or sync them from a private store",
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


@excerpts_app.command(name="sign")
def sign_command(
    data_files: Annotated[
        list[Path],
        typer.Argument(help="YAML data files whose quotes should be signed"),
    ],
    reference: Annotated[
        Optional[list[str]],
        typer.Option(
            "--reference",
            "-r",
            help=(
                "Only sign quotes citing this reference (repeatable). Default: every "
                "cited reference mapped by local_full_text or local_full_text_dir."
            ),
        ),
    ] = None,
    signed_excerpts_dir: SignedExcerptsDirOption = None,
    check: Annotated[
        bool,
        typer.Option(
            "--check",
            help="Write nothing; exit 1 if any bundle is out of date",
        ),
    ] = False,
    prune: Annotated[
        bool,
        typer.Option(
            "--prune",
            help=(
                "Remove excerpts this command signed earlier that the data no longer "
                "cites; excerpts from elsewhere are kept"
            ),
        ),
    ] = False,
    config_file: ConfigFileOption = None,
):
    """Verify quotes against local full text and write snippet-only bundles.

    Quotes citing a reference that `local_full_text` or `local_full_text_dir`
    maps to a file on this machine are matched against that file, with the
    usual fair-use caps. Those that pass are written to
    `signed_excerpts_dir/<REF_ID>.yaml` with a `verification` record, so CI can
    validate the same citations without the file. Nothing else from the file
    is written.

    Exits 1 if a quote fails to verify or (with --check) a bundle is out of
    date, and 2 on a usage error.

    Examples:

        linkml-reference-validator excerpts sign kb/disorders/*.yaml

        linkml-reference-validator excerpts sign kb/disorders/X.yaml \\
            --reference DOI:10.1016/j.ajodo.2025.11.017 --check
    """
    config = load_validation_config(config_file)
    dest_dir = signed_excerpts_dir or config.signed_excerpts_dir
    if dest_dir is None:
        typer.echo(
            "No destination: pass --signed-excerpts-dir or set signed_excerpts_dir in the config.",
            err=True,
        )
        raise typer.Exit(2)
    missing = [str(p) for p in data_files if not p.is_file()]
    if missing:
        typer.echo(f"Data file not found: {', '.join(missing)}", err=True)
        raise typer.Exit(2)

    report = sign_excerpts(
        data_files,
        config,
        references=reference,
        dest_dir=dest_dir,
        dry_run=check,
        prune=prune,
    )

    verb = "would be written" if check else "written"
    for name in report.written:
        typer.echo(f"  {verb}: {name}")
    for reference_id in report.no_local_text:
        typer.echo(f"  no local full text: {reference_id}", err=True)
    for failure in report.failures:
        if failure.text:
            typer.echo(f"  NOT signed ({failure.reference_id}): {failure.text}")
            typer.echo(f"    {failure.message}")
        else:
            label = f" ({failure.reference_id})" if failure.reference_id else ""
            typer.echo(f"  NOT signed{label}: {failure.message}")
    typer.echo(
        f"{dest_dir}: {len(report.written)} {verb}, {len(report.unchanged)} unchanged, "
        f"{len(report.failures)} problem(s)"
    )
    if report.failures or report.no_local_text or (check and report.changed):
        raise typer.Exit(1)
