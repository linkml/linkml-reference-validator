"""Validate subcommands for linkml-reference-validator."""

import logging
from pathlib import Path
from typing import Optional

import typer
from linkml.validator import Validator  # type: ignore
from ruamel.yaml import YAML
from typing_extensions import Annotated

from linkml_reference_validator.etl.text_extractor import TextExtractor
from linkml_reference_validator.models import ValidationReport
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

from .shared import (
    CacheDirOption,
    VerboseOption,
    ConfigFileOption,
    setup_logging,
    load_validation_config,
)

logger = logging.getLogger(__name__)

# Create the validate subcommand group
validate_app = typer.Typer(
    help="Validate supporting text against references",
    no_args_is_help=True,
)


@validate_app.command(name="text")
def text_command(
    text: Annotated[str, typer.Argument(help="Supporting text to validate")],
    reference_id: Annotated[str, typer.Argument(help="Reference ID (e.g., PMID:12345678 or DOI:10.1234/example)")],
    config_file: ConfigFileOption = None,
    cache_dir: CacheDirOption = None,
    verbose: VerboseOption = False,
):
    """Validate a single supporting text quote against a reference.

    Uses deterministic substring matching. Supports [...] for editorial notes
    and ... for omitted text.

    Examples:

        linkml-reference-validator validate text "protein functions in cells" PMID:12345678

        linkml-reference-validator validate text "protein [X] functions ... cells" PMID:12345678 --verbose

        linkml-reference-validator validate text "some text from article" DOI:10.1038/nature12373
    """
    setup_logging(verbose)

    config = load_validation_config(config_file)
    if cache_dir:
        config.cache_dir = cache_dir

    validator = SupportingTextValidator(config)

    typer.echo(f"Validating text against {reference_id}...")
    typer.echo(f"  Text: {text}")

    result = validator.validate(text, reference_id)

    typer.echo("\nResult:")
    typer.echo(f"  Valid: {result.is_valid}")
    typer.echo(f"  Message: {result.message}")

    if result.match_result:
        if result.match_result.matched_text:
            typer.echo(f"  Matched text: {result.match_result.matched_text[:100]}...")
        if result.match_result.suggested_fix:
            typer.echo(f"  Suggestion: {result.match_result.suggested_fix}")
        if verbose and result.match_result.best_match:
            typer.echo(f"  Best match: {result.match_result.best_match[:100]}...")

    if result.is_valid:
        raise typer.Exit(0)
    else:
        raise typer.Exit(1)


@validate_app.command(name="text-file")
def text_file_command(
    file_path: Annotated[Path, typer.Argument(help="Path to text file (e.g., OBO, plain text)")],
    regex: Annotated[
        str,
        typer.Option(
            "--regex",
            "-r",
            help=r'Regular expression with capture groups for text and reference ID (e.g., \'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"\')',
        ),
    ],
    text_group: Annotated[
        int,
        typer.Option(
            "--text-group",
            "-t",
            help="Capture group number for supporting text (default: 1)",
        ),
    ] = 1,
    ref_group: Annotated[
        int,
        typer.Option(
            "--ref-group",
            "-R",
            help="Capture group number for reference ID (default: 2)",
        ),
    ] = 2,
    summary: Annotated[
        bool,
        typer.Option(
            "--summary",
            "-s",
            help="Show only summary statistics, not individual results",
        ),
    ] = False,
    config_file: ConfigFileOption = None,
    cache_dir: CacheDirOption = None,
    verbose: VerboseOption = False,
):
    r"""Validate supporting text in a plain text file using regex extraction.

    This command extracts supporting text and reference IDs from text files
    (such as OBO format ontologies) using a regular expression, then validates
    each extracted quote against its reference.

    Examples:

        # Validate OBO file with axiom annotations
        linkml-reference-validator validate text-file sample.obo \
            --regex 'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"' \
            --text-group 1 --ref-group 2

        # Show only summary
        linkml-reference-validator validate text-file sample.obo \
            --regex 'ex:supporting_text="([^"]*)\[(\S+:\S+)\]"' \
            --summary
    """
    setup_logging(verbose)

    if not file_path.exists():
        typer.echo(f"Error: File not found: {file_path}", err=True)
        raise typer.Exit(1)

    config = load_validation_config(config_file)
    if cache_dir:
        config.cache_dir = cache_dir

    typer.echo(f"Extracting text from {file_path}")
    typer.echo(f"  Regex pattern: {regex}")
    typer.echo(f"  Text group: {text_group}, Reference group: {ref_group}")
    typer.echo(f"  Cache directory: {config.cache_dir}\n")

    # Extract matches from file
    extractor = TextExtractor(
        regex_pattern=regex, text_group=text_group, ref_group=ref_group
    )
    matches = extractor.extract_from_file(file_path)

    if not matches:
        typer.echo("No matches found in file.")
        raise typer.Exit(0)

    typer.echo(f"Found {len(matches)} match(es) to validate\n")

    # Validate each match
    validator = SupportingTextValidator(config)
    report = ValidationReport()

    for match in matches:
        if not summary:
            typer.echo(f"Line {match.line_number}: {match.original_line[:80]}...")

        result = validator.validate(match.supporting_text, match.reference_id)
        result.path = f"line {match.line_number}"
        report.add_result(result)

        if not summary:
            status = "✓ VALID" if result.is_valid else "✗ INVALID"
            typer.echo(f"  {status}: {result.message}")
            if result.match_result:
                if result.match_result.suggested_fix:
                    typer.echo(f"    Suggestion: {result.match_result.suggested_fix}")
                if verbose and result.match_result.matched_text:
                    typer.echo(f"    Matched: {result.match_result.matched_text[:100]}...")
                if verbose and result.match_result.best_match:
                    typer.echo(f"    Best match: {result.match_result.best_match[:100]}...")
            typer.echo()

    # Print summary
    typer.echo("=" * 60)
    typer.echo("Validation Summary:")
    typer.echo(f"  Total validations: {report.total_validations}")
    typer.echo(f"  Valid: {report.valid_count}")
    typer.echo(f"  Invalid: {report.invalid_count}")
    typer.echo(f"  Errors: {report.error_count}")

    if report.is_valid:
        typer.echo("\n✓ All validations passed!")
        raise typer.Exit(0)
    else:
        typer.echo("\n✗ Some validations failed")
        raise typer.Exit(1)


@validate_app.command(name="data")
def data_command(
    data_file: Annotated[Path, typer.Argument(help="Path to data file (YAML/JSON)")],
    schema_file: Annotated[
        Path,
        typer.Option("--schema", "-s", help="Path to LinkML schema file"),
    ],
    target_class: Annotated[
        Optional[str],
        typer.Option("--target-class", "-t", help="Target class to validate"),
    ] = None,
    config_file: ConfigFileOption = None,
    cache_dir: CacheDirOption = None,
    verbose: VerboseOption = False,
):
    """Validate supporting text in data against references.

    This command validates that quoted text (supporting_text) in your data
    actually appears in the referenced publications using deterministic substring matching.

    Examples:

        linkml-reference-validator validate data data.yaml --schema schema.yaml

        linkml-reference-validator validate data data.yaml --schema schema.yaml --target-class Statement --verbose
    """
    setup_logging(verbose)

    config = load_validation_config(config_file)
    if cache_dir:
        config.cache_dir = cache_dir

    plugin = ReferenceValidationPlugin(config=config)

    typer.echo(f"Validating {data_file} against schema {schema_file}")
    typer.echo(f"Cache directory: {config.cache_dir}")

    validator = Validator(
        schema=str(schema_file),
        validation_plugins=[plugin],
    )

    yaml = YAML(typ="safe")
    with open(data_file) as f:
        data = yaml.load(f)

    # Validate each instance
    all_results = []
    if isinstance(data, list):
        for instance in data:
            report = validator.validate(instance, target_class=target_class)
            all_results.extend(report.results)
    elif isinstance(data, dict):
        report = validator.validate(data, target_class=target_class)
        all_results = report.results
    else:
        typer.echo(f"Error: Unexpected data format in {data_file}", err=True)
        raise typer.Exit(1)

    if all_results:
        typer.echo(f"\nValidation Issues ({len(all_results)}):")
        for result in all_results:
            severity = result.severity.value if hasattr(result.severity, "value") else result.severity
            typer.echo(f"  [{severity}] {result.message}")
            if hasattr(result, "instantiates") and result.instantiates:
                typer.echo(f"    Location: {result.instantiates}")
            # Show reference ID if available in instance data
            if hasattr(result, "instance") and result.instance:
                if isinstance(result.instance, dict) and "reference_id" in result.instance:
                    typer.echo(f"    Reference: {result.instance['reference_id']}")

    typer.echo("\nValidation Summary:")
    typer.echo(f"  Total checks: {len(all_results)}")

    if all_results:
        typer.echo(f"  Issues found: {len(all_results)}")
        raise typer.Exit(1)
    else:
        typer.echo("  All validations passed!")
        raise typer.Exit(0)
