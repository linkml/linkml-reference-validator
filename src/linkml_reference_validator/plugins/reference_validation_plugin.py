"""LinkML validation plugin for reference validation."""

import logging
from collections.abc import Iterator
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Optional

from curies import Converter

from linkml_reference_validator.field_detection import (
    FallbackSlotNames,
    is_excerpt_slot,
    is_reference_slot,
    is_title_slot,
)
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

_LINKML_AVAILABLE = (
    find_spec("linkml") is not None and find_spec("linkml.validator") is not None
)

logger = logging.getLogger(__name__)


if _LINKML_AVAILABLE:
    # NOTE: `linkml` is optional. We only import LinkML modules when available.
    # Ruff's E402 doesn't like imports in blocks, so we silence it per-import.
    from linkml.validator.plugins import ValidationPlugin  # type: ignore  # noqa: E402
    from linkml.validator.report import (  # type: ignore  # noqa: E402
        Severity,
        ValidationResult as LinkMLValidationResult,
    )
    from linkml.validator.validation_context import (  # type: ignore  # noqa: E402
        ValidationContext,
    )
    from linkml_runtime.utils.schemaview import SchemaView  # type: ignore  # noqa: E402

    class ReferenceValidationPlugin(ValidationPlugin):
        """LinkML validation plugin for supporting text and title validation.

        This plugin integrates with the LinkML validation framework to validate
        that supporting text quotes actually appear in their referenced publications
        and that reference titles match expected values.

        The plugin discovers reference, excerpt, and title fields using LinkML's
        interface mechanism (implements) or slot_uri. It supports:

        Excerpt fields (canonical: oa:exact, legacy: linkml:excerpt):
            - oa:exact (http://www.w3.org/ns/oa#exact) - W3C Web Annotation
            - linkml:excerpt (https://w3id.org/linkml/excerpt) - legacy

        Reference fields (canonical: dcterms:references, legacy: linkml:authoritative_reference):
            - dcterms:references (http://purl.org/dc/terms/references) - Dublin Core
            - dcterms:source (http://purl.org/dc/terms/source) - Dublin Core alt
            - linkml:authoritative_reference - legacy

        Title fields:
            - dcterms:title (http://purl.org/dc/terms/title) - Dublin Core

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> plugin = ReferenceValidationPlugin(config=config)
            >>> plugin.config.cache_dir
            PosixPath('references_cache')
        """

        def __init__(
            self,
            config: Optional[ReferenceValidationConfig] = None,
            cache_dir: Optional[str] = None,
        ):
            """Initialize the validation plugin.

            Args:
                config: Full configuration object (if provided, other args ignored)
                cache_dir: Directory for caching references

            Examples:
                >>> plugin = ReferenceValidationPlugin(cache_dir="/tmp/cache")
                >>> plugin.config.cache_dir
                PosixPath('/tmp/cache')
            """
            if config is None:
                config = ReferenceValidationConfig()
                if cache_dir is not None:
                    config.cache_dir = Path(cache_dir)

            self.config = config
            self.validator = SupportingTextValidator(config)
            self.schema_view: Optional[SchemaView] = None

        def pre_process(self, context: ValidationContext) -> None:
            """Pre-process hook called before validation.

            Args:
                context: Validation context from LinkML

            Examples:
                >>> from linkml.validator.validation_context import ValidationContext
                >>> config = ReferenceValidationConfig()
                >>> plugin = ReferenceValidationPlugin(config=config)
                >>> # Would be called by LinkML validator
            """
            if hasattr(context, "schema_view") and context.schema_view:
                self.schema_view = context.schema_view
            logger.info("ReferenceValidationPlugin initialized")

        def process(
            self,
            instance: dict[str, Any],
            context: ValidationContext,
        ) -> Iterator[LinkMLValidationResult]:
            """Validate an instance.

            Args:
                instance: Data instance to validate
                context: Validation context

            Yields:
                ValidationResult objects for any issues found

            Examples:
                >>> from linkml.validator.validation_context import ValidationContext
                >>> config = ReferenceValidationConfig()
                >>> plugin = ReferenceValidationPlugin(config=config)
                >>> # Would be called by LinkML validator:
                >>> # results = list(plugin.process(instance, context))
            """
            if not self.schema_view:
                logger.warning("No schema view available for validation")
                return

            target_class = (
                context.target_class if hasattr(context, "target_class") else None
            )
            if not target_class:
                logger.warning("No target class specified")
                return

            yield from self._validate_instance(instance, target_class, path="")

        def _validate_instance(  # type: ignore
            self,
            instance: dict[str, Any],
            class_name: str,
            path: str,
        ) -> Iterator[LinkMLValidationResult]:
            """Recursively validate an instance and nested objects.

            Args:
                instance: Instance data
                class_name: Class name from schema
                path: Current path in data structure

            Yields:
                ValidationResult objects
            """
            if not self.schema_view:
                return
            class_def = self.schema_view.get_class(class_name)
            if not class_def:
                return

            reference_fields = self._find_reference_fields(class_name)
            excerpt_fields = self._find_excerpt_fields(class_name)
            title_fields = self._find_title_fields(class_name)

            # Track whether we've validated with excerpt (which includes title validation)
            validated_with_excerpt = False

            for excerpt_field in excerpt_fields:
                excerpt_value = instance.get(excerpt_field)
                if not excerpt_value:
                    continue

                for ref_field in reference_fields:
                    ref_value = instance.get(ref_field)
                    if ref_value:
                        reference_id = self._extract_reference_id(ref_value)
                        # Get title from title field or from reference dict
                        expected_title = None
                        for title_field in title_fields:
                            title_value = instance.get(title_field)
                            if title_value:
                                expected_title = title_value
                                break
                        if not expected_title:
                            expected_title = self._extract_title(ref_value)
                        if reference_id:
                            validated_with_excerpt = True
                            yield from self._validate_excerpt(
                                excerpt_value,
                                reference_id,
                                expected_title,
                                f"{path}.{excerpt_field}" if path else excerpt_field,
                            )
                            # Break after first successful reference match to avoid duplicates
                            break

            # If no excerpt validation was done, validate title independently
            if not validated_with_excerpt and title_fields:
                # Validate only the first available title against the first available reference
                first_title_field: Optional[str] = None
                first_title_value: Optional[str] = None
                for title_field in title_fields:
                    title_value = instance.get(title_field)
                    if title_value:
                        first_title_field = title_field
                        first_title_value = title_value
                        break

                if first_title_field and first_title_value:
                    for ref_field in reference_fields:
                        ref_value = instance.get(ref_field)
                        if ref_value:
                            reference_id = self._extract_reference_id(ref_value)
                            if reference_id:
                                yield from self._validate_title(
                                    first_title_value,
                                    reference_id,
                                    f"{path}.{first_title_field}"
                                    if path
                                    else first_title_field,
                                )
                            # Break after processing first reference field with a value
                            break


            for slot_name, value in instance.items():
                if value is None:
                    continue

                slot = self.schema_view.induced_slot(slot_name, class_name)
                if not slot:
                    continue

                slot_path = f"{path}.{slot_name}" if path else slot_name

                if isinstance(value, dict):
                    range_class = slot.range
                    if range_class and self.schema_view.get_class(range_class):
                        yield from self._validate_instance(value, range_class, slot_path)

                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        item_path = f"{slot_path}[{i}]"
                        if isinstance(item, dict):
                            range_class = slot.range
                            if range_class and self.schema_view.get_class(range_class):
                                yield from self._validate_instance(
                                    item, range_class, item_path
                                )

        def _get_converter(self) -> Optional[Converter]:
            """Get a curies Converter from the schema for CURIE expansion.

            Returns:
                Converter instance or None if unavailable
            """
            if not self.schema_view:
                return None
            schema = self.schema_view.schema
            if schema and schema.prefixes:
                # schema.prefixes is a dict of prefix name -> Prefix object
                # The Prefix object has a prefix_reference attribute with the URI
                prefix_map = {
                    name: (
                        prefix.prefix_reference
                        if hasattr(prefix, "prefix_reference")
                        else str(prefix)
                    )
                    for name, prefix in schema.prefixes.items()
                }
                return Converter.from_prefix_map(prefix_map)
            return None

        def _find_reference_fields(self, class_name: str) -> list[str]:  # type: ignore
            """Find slots that represent authoritative references.

            Supports canonical URIs (dcterms:references, dcterms:source) and
            legacy URIs (linkml:authoritative_reference) via implements or slot_uri.
            Custom prefixes are resolved using the schema's prefix map.

            Args:
                class_name: Class to search

            Returns:
                List of slot names

            Examples:
                >>> config = ReferenceValidationConfig()
                >>> plugin = ReferenceValidationPlugin(config=config)
                >>> # Would need schema_view to actually work
            """
            fields: list[str] = []
            if not self.schema_view:
                return fields
            class_def = self.schema_view.get_class(class_name)
            if not class_def:
                return fields

            converter = self._get_converter()

            for slot_name in self.schema_view.class_slots(class_name):
                slot = self.schema_view.induced_slot(slot_name, class_name)
                if slot and is_reference_slot(slot, converter):
                    fields.append(slot_name)

            # Fallback: check for common reference slot names
            class_slots = list(self.schema_view.class_slots(class_name))
            for fallback_name in FallbackSlotNames.REFERENCE:
                if fallback_name in class_slots and fallback_name not in fields:
                    fields.append(fallback_name)

            return fields

        def _find_excerpt_fields(self, class_name: str) -> list[str]:  # type: ignore
            """Find slots that represent excerpt/supporting text fields.

            Supports canonical URI (oa:exact) and legacy URI (linkml:excerpt)
            via implements or slot_uri. Custom prefixes are resolved using
            the schema's prefix map.

            Args:
                class_name: Class to search

            Returns:
                List of slot names

            Examples:
                >>> config = ReferenceValidationConfig()
                >>> plugin = ReferenceValidationPlugin(config=config)
                >>> # Would need schema_view to actually work
            """
            fields: list[str] = []
            if not self.schema_view:
                return fields
            class_def = self.schema_view.get_class(class_name)
            if not class_def:
                return fields

            converter = self._get_converter()

            for slot_name in self.schema_view.class_slots(class_name):
                slot = self.schema_view.induced_slot(slot_name, class_name)
                if slot and is_excerpt_slot(slot, converter):
                    fields.append(slot_name)

            # Fallback: check for common excerpt slot names
            class_slots = list(self.schema_view.class_slots(class_name))
            for fallback_name in FallbackSlotNames.EXCERPT:
                if fallback_name in class_slots and fallback_name not in fields:
                    fields.append(fallback_name)

            return fields

        def _find_title_fields(self, class_name: str) -> list[str]:  # type: ignore
            """Find slots that represent title fields.

            Supports dcterms:title via implements or slot_uri. Custom prefixes
            are resolved using the schema's prefix map.

            Args:
                class_name: Class to search

            Returns:
                List of slot names

            Examples:
                >>> config = ReferenceValidationConfig()
                >>> plugin = ReferenceValidationPlugin(config=config)
                >>> # Would need schema_view to actually work
            """
            fields: list[str] = []
            if not self.schema_view:
                return fields
            class_def = self.schema_view.get_class(class_name)
            if not class_def:
                return fields

            converter = self._get_converter()

            for slot_name in self.schema_view.class_slots(class_name):
                slot = self.schema_view.induced_slot(slot_name, class_name)
                if slot and is_title_slot(slot, converter):
                    fields.append(slot_name)

            # Fallback: check for common title slot names
            class_slots = list(self.schema_view.class_slots(class_name))
            for fallback_name in FallbackSlotNames.TITLE:
                if fallback_name in class_slots and fallback_name not in fields:
                    fields.append(fallback_name)

            return fields

        def _extract_reference_id(self, reference_value: Any) -> Optional[str]:
            """Extract reference ID from various value formats.

            Supports:
            - String: "PMID:12345678"
            - Dict with 'id': {"id": "PMID:12345678", "title": "..."}

            Args:
                reference_value: Reference value from data

            Returns:
                Reference ID string or None

            Examples:
                >>> config = ReferenceValidationConfig()
                >>> plugin = ReferenceValidationPlugin(config=config)
                >>> plugin._extract_reference_id("PMID:12345678")
                'PMID:12345678'
                >>> plugin._extract_reference_id({"id": "PMID:12345678"})
                'PMID:12345678'
            """
            if isinstance(reference_value, str):
                return reference_value
            elif isinstance(reference_value, dict):
                return reference_value.get("id") or reference_value.get("reference_id")
            return None

        def _extract_title(self, reference_value: Any) -> Optional[str]:
            """Extract title from reference value.

            Args:
                reference_value: Reference value from data

            Returns:
                Title string or None

            Examples:
                >>> config = ReferenceValidationConfig()
                >>> plugin = ReferenceValidationPlugin(config=config)
                >>> plugin._extract_title({"id": "PMID:12345678", "title": "Test"})
                'Test'
            """
            if isinstance(reference_value, dict):
                return reference_value.get("title") or reference_value.get(
                    "reference_title"
                )
            return None

        def _validate_excerpt(
            self,
            excerpt: str,
            reference_id: str,
            expected_title: Optional[str],
            path: str,
        ) -> Iterator[LinkMLValidationResult]:
            """Validate an excerpt against a reference.

            Args:
                excerpt: Supporting text to validate
                reference_id: Reference identifier
                expected_title: Optional expected title
                path: Path in data structure

            Yields:
                ValidationResult if validation fails
            """
            result = self.validator.validate(
                excerpt, reference_id, expected_title=expected_title, path=path
            )

            if not result.is_valid:
                yield LinkMLValidationResult(
                    type="reference_validation",
                    severity=Severity.ERROR
                    if result.severity.value == "ERROR"
                    else Severity.WARNING,
                    message=result.message or "Supporting text validation failed",
                    instance={"supporting_text": excerpt, "reference_id": reference_id},
                    instantiates=path,
                )

        def _validate_title(
            self,
            title: str,
            reference_id: str,
            path: str,
        ) -> Iterator[LinkMLValidationResult]:
            """Validate a title against a reference.

            Uses exact matching after normalization (case, whitespace, punctuation).

            Args:
                title: Expected title to validate
                reference_id: Reference identifier
                path: Path in data structure

            Yields:
                ValidationResult if validation fails
            """
            result = self.validator.validate_title(
                reference_id, expected_title=title, path=path
            )

            if not result.is_valid:
                yield LinkMLValidationResult(
                    type="reference_validation",
                    severity=Severity.ERROR
                    if result.severity.value == "ERROR"
                    else Severity.WARNING,
                    message=result.message or "Title validation failed",
                    instance={"title": title, "reference_id": reference_id},
                    instantiates=path,
                )

        def post_process(self, context: ValidationContext) -> None:
            """Post-process hook called after validation.

            Args:
                context: Validation context

            Examples:
                >>> from linkml.validator.validation_context import ValidationContext
                >>> config = ReferenceValidationConfig()
                >>> plugin = ReferenceValidationPlugin(config=config)
                >>> # Would be called by LinkML validator
            """
            logger.info("ReferenceValidationPlugin validation complete")

else:

    class ReferenceValidationPlugin:  # type: ignore[no-redef]
        """Placeholder when `linkml` is not installed.

        This module is intentionally importable without LinkML installed (so plugin
        discovery / module scanning won't crash). Attempting to *use* this plugin
        without LinkML will fail fast.
        """

        def __init__(
            self,
            config: Optional[ReferenceValidationConfig] = None,
            cache_dir: Optional[str] = None,
        ):
            raise ImportError(
                "`linkml` is not installed; `ReferenceValidationPlugin` is unavailable."
            )
