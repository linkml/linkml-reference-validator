"""Top-level lookup command for quick reference lookups."""

import json
import logging
from enum import Enum
from io import StringIO

import typer
from ruamel.yaml import YAML
from typing_extensions import Annotated

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceContent
from .shared import (
    CacheDirOption,
    VerboseOption,
    ConfigFileOption,
    setup_logging,
    load_validation_config,
)

logger = logging.getLogger(__name__)


class OutputFormat(str, Enum):
    """Output format options for lookup command."""

    md = "md"
    json = "json"
    yaml = "yaml"
    text = "text"


# Format option
FormatOption = Annotated[
    OutputFormat,
    typer.Option(
        "--format",
        "-f",
        help="Output format (md, json, yaml, text)",
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


def _reference_to_dict(reference: ReferenceContent) -> dict:
    """Convert ReferenceContent to a dictionary."""
    return {
        "reference_id": reference.reference_id,
        "title": reference.title,
        "authors": reference.authors,
        "journal": reference.journal,
        "year": reference.year,
        "doi": reference.doi,
        "content_type": reference.content_type,
        "content": reference.content,
    }


def _format_as_markdown(reference: ReferenceContent, fetcher: ReferenceFetcher) -> str:
    """Format reference as markdown with YAML frontmatter.

    Reads from the cache file which is created by fetch().

    Args:
        reference: The reference data (used for reference_id)
        fetcher: Used to get the cache path

    Returns:
        Markdown content with YAML frontmatter
    """
    cache_path = fetcher.get_cache_path(reference.reference_id)
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8")

    # Fallback: build from reference data using YAML for proper escaping
    yaml_obj = YAML()
    yaml_obj.default_flow_style = False
    stream = StringIO()
    frontmatter: dict[str, str | list[str] | None] = {
        "reference_id": reference.reference_id,
        "content_type": reference.content_type,
    }
    if reference.title:
        frontmatter["title"] = reference.title
    if reference.authors:
        frontmatter["authors"] = reference.authors
    if reference.journal:
        frontmatter["journal"] = reference.journal
    if reference.year:
        frontmatter["year"] = str(reference.year)
    if reference.doi:
        frontmatter["doi"] = reference.doi

    yaml_obj.dump(frontmatter, stream)

    lines = ["---", stream.getvalue().rstrip(), "---", ""]
    if reference.title:
        lines.append(f"# {reference.title}")
        if reference.authors:
            lines.append(f"**Authors:** {', '.join(reference.authors)}")
        if reference.journal:
            journal_info = reference.journal
            if reference.year:
                journal_info += f" ({reference.year})"
            lines.append(f"**Journal:** {journal_info}")
        if reference.doi:
            lines.append(f"**DOI:** [{reference.doi}](https://doi.org/{reference.doi})")
        lines.append("")
        lines.append("## Content")
        lines.append("")
    if reference.content:
        lines.append(reference.content)
    return "\n".join(lines)


def _format_as_json(references: list[ReferenceContent], single: bool = False) -> str:
    """Format references as JSON."""
    data = [_reference_to_dict(r) for r in references]
    if single and len(data) == 1:
        return json.dumps(data[0], indent=2)
    return json.dumps(data, indent=2)


def _format_as_yaml(references: list[ReferenceContent], single: bool = False) -> str:
    """Format references as YAML."""
    data_list = [_reference_to_dict(r) for r in references]
    output_data: list[dict] | dict = data_list
    if single and len(data_list) == 1:
        output_data = data_list[0]

    yaml = YAML()
    yaml.default_flow_style = False
    stream = StringIO()
    yaml.dump(output_data, stream)
    return stream.getvalue()


def _format_as_text(reference: ReferenceContent) -> str:
    """Format reference as pretty text."""
    lines = []
    lines.append(f"Reference: {reference.reference_id}")
    if reference.title:
        lines.append(f"Title: {reference.title}")
    if reference.authors:
        lines.append(f"Authors: {', '.join(reference.authors)}")
    if reference.journal:
        journal_info = reference.journal
        if reference.year:
            journal_info += f" ({reference.year})"
        lines.append(f"Journal: {journal_info}")
    if reference.doi:
        lines.append(f"DOI: {reference.doi}")
    lines.append(f"Content type: {reference.content_type}")
    if reference.content:
        lines.append("")
        lines.append("--- Content ---")
        lines.append(reference.content)
    return "\n".join(lines)


def lookup_command(
    reference_ids: Annotated[
        list[str],
        typer.Argument(help="Reference ID(s) (e.g., PMID:12345678, DOI:10.1234/example)"),
    ],
    config_file: ConfigFileOption = None,
    cache_dir: CacheDirOption = None,
    format: FormatOption = OutputFormat.md,
    no_cache: NoCacheOption = False,
    verbose: VerboseOption = False,
):
    """Look up reference(s) and display their information.

    Fetches reference metadata and content, using cache when available.
    Useful for quick "what is this PMID?" lookups from the command line.

    Examples:

        linkml-reference-validator lookup PMID:12345678

        linkml-reference-validator lookup PMID:12345678 PMID:23456789

        linkml-reference-validator lookup PMID:12345678 --format json

        linkml-reference-validator lookup PMID:12345678 --format yaml

        linkml-reference-validator lookup PMID:12345678 --no-cache
    """
    setup_logging(verbose)

    config = load_validation_config(config_file)
    if cache_dir:
        config.cache_dir = cache_dir

    fetcher = ReferenceFetcher(config)

    # Fetch all references
    results: list[ReferenceContent] = []
    errors: list[str] = []

    for ref_id in reference_ids:
        reference = fetcher.fetch(ref_id, force_refresh=no_cache)
        if reference:
            results.append(reference)
        else:
            errors.append(ref_id)
            typer.echo(f"Could not fetch reference: {ref_id}", err=True)

    # If no results at all, exit with error
    if not results:
        raise typer.Exit(1)

    # Output based on format
    single = len(reference_ids) == 1

    if format == OutputFormat.json:
        typer.echo(_format_as_json(results, single=single))
    elif format == OutputFormat.yaml:
        typer.echo(_format_as_yaml(results, single=single))
    elif format == OutputFormat.text:
        for i, ref in enumerate(results):
            if i > 0:
                typer.echo("\n" + "=" * 60 + "\n")
            typer.echo(_format_as_text(ref))
    else:  # md (default)
        for i, ref in enumerate(results):
            if i > 0:
                typer.echo("\n" + "=" * 60 + "\n")
            typer.echo(_format_as_markdown(ref, fetcher))

    # Exit success if at least one reference was found
    # (errors already printed to stderr)
