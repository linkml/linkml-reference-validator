"""Repair subcommands for linkml-reference-validator.

This module provides CLI commands for automatically repairing supporting
text validation errors.
"""

import logging
import shutil
from pathlib import Path
from typing import Optional

import typer
from ruamel.yaml import YAML
from typing_extensions import Annotated

from linkml_reference_validator.models import RepairConfig
from linkml_reference_validator.validation.repairer import SupportingTextRepairer

from .shared import (
    CacheDirOption,
    VerboseOption,
    ConfigFileOption,
    setup_logging,
    load_validation_config,
)

logger = logging.getLogger(__name__)

# Create the repair subcommand group
repair_app = typer.Typer(
    help="Repair supporting text validation errors",
    no_args_is_help=True,
)


# Common repair options
DryRunOption = Annotated[
    bool,
    typer.Option(
        "--dry-run/--no-dry-run",
        "-n/-N",
        help="Show what would be changed without modifying files",
    ),
]

AutoFixThresholdOption = Annotated[
    float,
    typer.Option(
        "--auto-fix-threshold",
        "-a",
        help="Minimum similarity for automatic fixes (0.0-1.0, default: 0.95)",
    ),
]

OutputOption = Annotated[
    Optional[Path],
    typer.Option(
        "--output",
        "-o",
        help="Output file path (default: overwrite input with backup)",
    ),
]


@repair_app.command(name="data")
def data_command(
    data_file: Annotated[Path, typer.Argument(help="Path to data file (YAML)")],
    schema_file: Annotated[
        Path,
        typer.Option("--schema", "-s", help="Path to LinkML schema file"),
    ],
    target_class: Annotated[
        Optional[str],
        typer.Option("--target-class", "-t", help="Target class to validate"),
    ] = None,
    dry_run: DryRunOption = True,
    auto_fix_threshold: AutoFixThresholdOption = 0.95,
    output: OutputOption = None,
    cache_dir: CacheDirOption = None,
    verbose: VerboseOption = False,
    config_file: ConfigFileOption = None,
):
    """Repair supporting text in a data file.

    Validates and attempts to repair supporting text quotes that fail
    validation against their references.

    Examples:

        # Dry run - show what would be changed
        linkml-reference-validator repair data file.yaml --schema schema.yaml --dry-run

        # Auto-fix with default threshold (0.95)
        linkml-reference-validator repair data file.yaml --schema schema.yaml --no-dry-run

        # Auto-fix with custom threshold
        linkml-reference-validator repair data file.yaml --schema schema.yaml \\
            --auto-fix-threshold 0.98 --no-dry-run

        # Output to new file
        linkml-reference-validator repair data file.yaml --schema schema.yaml \\
            --output repaired.yaml --no-dry-run
    """
    setup_logging(verbose)

    if not data_file.exists():
        typer.echo(f"Error: Data file not found: {data_file}", err=True)
        raise typer.Exit(1)

    if not schema_file.exists():
        typer.echo(f"Error: Schema file not found: {schema_file}", err=True)
        raise typer.Exit(1)

    # Load repair config from file if provided
    repair_config = _load_repair_config(config_file)
    repair_config.auto_fix_threshold = auto_fix_threshold
    repair_config.dry_run = dry_run

    # Set up validation config
    val_config = load_validation_config(config_file)
    if cache_dir:
        val_config.cache_dir = cache_dir

    # Initialize repairer
    repairer = SupportingTextRepairer(
        validation_config=val_config,
        repair_config=repair_config,
    )

    if dry_run:
        typer.echo(f"[DRY RUN] Repairing {data_file}")
    else:
        typer.echo(f"Repairing {data_file}")
    typer.echo(f"  Schema: {schema_file}")
    typer.echo(f"  Auto-fix threshold: {auto_fix_threshold}")
    typer.echo(f"  Cache directory: {val_config.cache_dir}")
    typer.echo("")

    # Load data
    yaml = YAML()
    yaml.preserve_quotes = True
    with open(data_file) as f:
        data = yaml.load(f)

    # Find and repair supporting text items
    items_to_repair = _extract_evidence_items(data, target_class, schema_file)

    if not items_to_repair:
        typer.echo("No evidence items found to repair.")
        raise typer.Exit(0)

    typer.echo(f"Found {len(items_to_repair)} evidence item(s) to process\n")

    # Repair each item
    report = repairer.repair_batch(items_to_repair)

    # Display report
    typer.echo(repairer.format_report(report, verbose=verbose))

    # Apply repairs if not dry run
    if not dry_run and report.auto_fixed_count > 0:
        # Create backup
        if repair_config.create_backup:
            backup_path = data_file.with_suffix(f"{data_file.suffix}.bak")
            shutil.copy2(data_file, backup_path)
            typer.echo(f"\nBackup created: {backup_path}")

        # Apply auto-fixes to data
        changes_made = _apply_repairs_to_data(data, report, target_class)

        # Write output
        output_path = output or data_file
        with open(output_path, 'w') as f:
            yaml.dump(data, f)

        typer.echo(f"\n{'✓' if changes_made else '!'} Wrote {output_path}")
        if changes_made:
            typer.echo(f"  Applied {report.auto_fixed_count} auto-fix(es)")

    # Exit with appropriate code
    if report.removal_count > 0 or report.unverifiable_count > 0:
        typer.echo("\n⚠ Manual review required for some items")
        raise typer.Exit(1)
    elif report.suggested_count > 0:
        typer.echo("\n⚠ Some suggestions require manual review")
        raise typer.Exit(0)
    else:
        raise typer.Exit(0)


@repair_app.command(name="text")
def text_command(
    text: Annotated[str, typer.Argument(help="Supporting text to repair")],
    reference_id: Annotated[str, typer.Argument(help="Reference ID (e.g., PMID:12345678 or DOI:10.1234/example)")],
    cache_dir: CacheDirOption = None,
    verbose: VerboseOption = False,
    auto_fix_threshold: AutoFixThresholdOption = 0.95,
    config_file: ConfigFileOption = None,
):
    """Attempt to repair a single supporting text quote.

    Examples:

        # Try to repair a quote
        linkml-reference-validator repair text "CO2 levels were measured" PMID:12345678

        # With verbose output
        linkml-reference-validator repair text "protein functions" PMID:12345678 --verbose

        # Repair quote from a DOI
        linkml-reference-validator repair text "some text" DOI:10.1038/nature12373
    """
    setup_logging(verbose)

    val_config = load_validation_config(config_file)
    if cache_dir:
        val_config.cache_dir = cache_dir

    repair_config = RepairConfig(auto_fix_threshold=auto_fix_threshold)
    repairer = SupportingTextRepairer(
        validation_config=val_config,
        repair_config=repair_config,
    )

    typer.echo(f"Attempting repair for {reference_id}...")
    typer.echo(f"  Text: {text}")
    typer.echo("")

    result = repairer.repair_single(text, reference_id)

    typer.echo("Result:")
    if result.was_valid:
        typer.echo("  ✓ Text already valid - no repair needed")
    elif result.is_repaired:
        typer.echo("  ✓ Repaired successfully")
        typer.echo(f"    Original: {result.original_text}")
        typer.echo(f"    Repaired: {result.repaired_text}")
        for action in result.actions:
            typer.echo(f"    Action: {action.action_type.value} ({action.description})")
            typer.echo(f"    Confidence: {action.confidence.value}")
    else:
        typer.echo(f"  ✗ Could not repair: {result.message}")
        for action in result.actions:
            typer.echo(f"    Suggestion: {action.action_type.value}")
            typer.echo(f"    Confidence: {action.confidence.value} ({action.similarity_score*100:.0f}%)")
            if action.repaired_text:
                typer.echo(f"    Best match: {action.repaired_text[:80]}...")

    if result.was_valid or result.is_repaired:
        raise typer.Exit(0)
    else:
        raise typer.Exit(1)


def _load_repair_config(config_file: Optional[Path]) -> RepairConfig:
    """Load repair configuration from file.

    Args:
        config_file: Path to config file, or None for defaults

    Returns:
        RepairConfig instance
    """
    if config_file is None:
        # Check for default config files
        for default_path in [
            Path(".linkml-reference-validator.yaml"),
            Path(".linkml-reference-validator.yml"),
        ]:
            if default_path.exists():
                config_file = default_path
                break

    if config_file is None:
        return RepairConfig()

    yaml = YAML(typ="safe")
    with open(config_file) as f:
        config_data = yaml.load(f)

    if config_data is None:
        return RepairConfig()

    if not isinstance(config_data, dict):
        return RepairConfig()

    # Extract repair section if present
    if "repair" in config_data:
        repair_data = config_data.get("repair")
        if isinstance(repair_data, dict):
            return RepairConfig(**repair_data)
        return RepairConfig()

    repair_keys = set(RepairConfig.model_fields.keys())
    if repair_keys.intersection(config_data.keys()):
        return RepairConfig(**config_data)

    return RepairConfig()


def _extract_evidence_items(
    data: dict,
    target_class: Optional[str],
    schema_file: Path,
) -> list[tuple[str, str, Optional[str]]]:
    """Extract evidence items from data for repair.

    This is a simplified extraction that looks for common patterns.
    For full schema-aware extraction, use the LinkML plugin.

    Args:
        data: Loaded YAML data
        target_class: Target class to look for
        schema_file: Schema file (for future use)

    Returns:
        List of (supporting_text, reference_id, path) tuples
    """
    items: list[tuple[str, str, Optional[str]]] = []

    def _extract_from_dict(d: dict, path: str = ""):
        # Look for evidence patterns
        if isinstance(d, dict):
            # Direct evidence item pattern
            if "supporting_text" in d or "snippet" in d:
                text = d.get("supporting_text") or d.get("snippet")
                ref = d.get("reference") or d.get("reference_id")
                if text and ref:
                    items.append((text, ref, path))

            # Look for evidence list
            for key in ["evidence", "supporting_evidence", "annotations"]:
                if key in d and isinstance(d[key], list):
                    for i, item in enumerate(d[key]):
                        if isinstance(item, dict):
                            _extract_from_dict(item, f"{path}.{key}[{i}]" if path else f"{key}[{i}]")

            # Recurse into other dict values
            for key, value in d.items():
                if key not in ["evidence", "supporting_evidence", "annotations"]:
                    if isinstance(value, dict):
                        _extract_from_dict(value, f"{path}.{key}" if path else key)
                    elif isinstance(value, list):
                        for i, item in enumerate(value):
                            if isinstance(item, dict):
                                _extract_from_dict(item, f"{path}.{key}[{i}]" if path else f"{key}[{i}]")

    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                _extract_from_dict(item, f"[{i}]")
    elif isinstance(data, dict):
        _extract_from_dict(data)

    return items


def _apply_repairs_to_data(
    data: dict,
    report,
    target_class: Optional[str],
) -> bool:
    """Apply auto-fixes from repair report to data.

    Args:
        data: Data to modify in-place
        report: RepairReport with results
        target_class: Target class (for future use)

    Returns:
        True if any changes were made
    """
    changes_made = False

    # Build a map of paths to repairs
    repairs_by_path = {}
    for result in report.results:
        if result.is_repaired and result.path:
            for action in result.actions:
                if action.can_auto_fix:
                    repairs_by_path[result.path] = result.repaired_text
                    break

    def _apply_to_dict(d: dict, path: str = ""):
        nonlocal changes_made

        if isinstance(d, dict):
            # Check if this item needs repair
            if "supporting_text" in d or "snippet" in d:
                text_key = "supporting_text" if "supporting_text" in d else "snippet"
                if path in repairs_by_path:
                    d[text_key] = repairs_by_path[path]
                    changes_made = True

            # Recurse
            for key in ["evidence", "supporting_evidence", "annotations"]:
                if key in d and isinstance(d[key], list):
                    for i, item in enumerate(d[key]):
                        if isinstance(item, dict):
                            _apply_to_dict(item, f"{path}.{key}[{i}]" if path else f"{key}[{i}]")

            for key, value in d.items():
                if key not in ["evidence", "supporting_evidence", "annotations"]:
                    if isinstance(value, dict):
                        _apply_to_dict(value, f"{path}.{key}" if path else key)
                    elif isinstance(value, list):
                        for i, item in enumerate(value):
                            if isinstance(item, dict):
                                _apply_to_dict(item, f"{path}.{key}[{i}]" if path else f"{key}[{i}]")

    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                _apply_to_dict(item, f"[{i}]")
    elif isinstance(data, dict):
        _apply_to_dict(data)

    return changes_made
