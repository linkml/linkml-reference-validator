"""CLI interface for linkml-reference-validator."""

import typer

# Import subcommand modules
from .cache import cache_app, reference_command
from .repair import repair_app
from .validate import data_command, text_command, validate_app

# Main app
app = typer.Typer(
    name="linkml-reference-validator",
    help="Validation of supporting text from references and publications",
    no_args_is_help=True,
)

# Register subcommand groups
app.add_typer(
    validate_app,
    name="validate",
    help="Validate supporting text against references",
)

app.add_typer(
    repair_app,
    name="repair",
    help="Repair supporting text validation errors",
)

app.add_typer(
    cache_app,
    name="cache",
    help="Manage reference cache",
)

# BACKWARD COMPATIBILITY: Register old commands as hidden aliases
# This allows existing scripts to continue working
app.command(name="validate-text", hidden=True)(text_command)
app.command(name="validate-data", hidden=True)(data_command)
app.command(name="cache-reference", hidden=True)(reference_command)


def main():
    """Main entry point for the CLI."""
    app()


__all__ = ["validate_app", "repair_app", "cache_app", "main", "app"]
