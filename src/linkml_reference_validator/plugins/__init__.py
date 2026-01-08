"""LinkML validation plugins for reference validation."""

from importlib.util import find_spec

# `linkml` is an optional dependency. Expose the LinkML plugin only when LinkML is available.
__all__: list[str]
if find_spec("linkml") is not None and find_spec("linkml.validator") is not None:
    from linkml_reference_validator.plugins.reference_validation_plugin import (  # noqa: F401
        ReferenceValidationPlugin,
    )

    __all__ = ["ReferenceValidationPlugin"]
else:
    __all__ = []
