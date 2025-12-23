"""Shared CLI options and utilities."""

from pathlib import Path
from typing import Optional

import typer
from ruamel.yaml import YAML  # type: ignore
from typing_extensions import Annotated

from linkml_reference_validator.models import ReferenceValidationConfig

# Common option definitions for reuse
CacheDirOption = Annotated[
    Optional[Path],
    typer.Option(
        "--cache-dir",
        "-c",
        help="Directory for caching references (default: references_cache)",
    ),
]

VerboseOption = Annotated[
    bool,
    typer.Option(
        "--verbose",
        "-v",
        help="Verbose output with detailed logging",
    ),
]

ForceOption = Annotated[
    bool,
    typer.Option(
        "--force",
        "-f",
        help="Force operation (e.g., re-fetch even if cached)",
    ),
]

ConfigFileOption = Annotated[
    Optional[Path],
    typer.Option(
        "--config",
        help="Path to validation configuration file (.yaml)",
    ),
]


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity flag.

    Args:
        verbose: If True, set logging level to INFO
    """
    import logging

    if verbose:
        logging.basicConfig(level=logging.INFO)


def load_validation_config(config_file: Optional[Path]) -> ReferenceValidationConfig:
    """Load validation configuration from file.

    Args:
        config_file: Path to config file, or None for defaults

    Returns:
        ReferenceValidationConfig instance
    """
    if config_file is None:
        for default_path in [
            Path(".linkml-reference-validator.yaml"),
            Path(".linkml-reference-validator.yml"),
        ]:
            if default_path.exists():
                config_file = default_path
                break

    if config_file is None:
        return ReferenceValidationConfig()

    yaml = YAML(typ="safe")
    with open(config_file) as f:
        config_data = yaml.load(f)

    if not config_data:
        return ReferenceValidationConfig()

    validation_data = _extract_validation_config_data(config_data)
    if validation_data is None:
        return ReferenceValidationConfig()

    return ReferenceValidationConfig(**validation_data)


def _extract_validation_config_data(config_data: object) -> Optional[dict]:
    """Extract validation settings from a config object."""
    if not isinstance(config_data, dict):
        return None

    if "validation" in config_data:
        section = config_data.get("validation")
        return section if isinstance(section, dict) else None
    if "reference_validation" in config_data:
        section = config_data.get("reference_validation")
        return section if isinstance(section, dict) else None

    validation_keys = set(ReferenceValidationConfig.model_fields.keys())
    if validation_keys.intersection(config_data.keys()):
        return config_data

    return None
