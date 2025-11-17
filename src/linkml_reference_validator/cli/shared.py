"""Shared CLI options and utilities."""

from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

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


def setup_logging(verbose: bool) -> None:
    """Configure logging based on verbosity flag.

    Args:
        verbose: If True, set logging level to INFO
    """
    import logging

    if verbose:
        logging.basicConfig(level=logging.INFO)
