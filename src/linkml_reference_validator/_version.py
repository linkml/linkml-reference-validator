from importlib.metadata import version, PackageNotFoundError
from typing import Union

try:
    __version__ = version("linkml-reference-validator")
except PackageNotFoundError:
    # package not installed
    __version__ = "0.0.0"
__version_tuple__: tuple[Union[int, str], ...] = tuple(
    int(part) if part.isdigit() else part for part in __version__.split(".")
)
