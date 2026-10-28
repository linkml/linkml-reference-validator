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
    find_spec("linkml") is not None and find_spec(
        "linkml.validator") is not None
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
            self.reset_counts()

        def reset_counts(self) -> None:
            """Reset execution counters (also called before each LinkML validation).

            Checked snippets are comparisons with fetched content, whether they
            match or fail. Skipped prefixes and unavailable content are separate.
            Blank/absent excerpts and missing references perform no comparison.
            Titles count actual comparisons, including those bundled with snippets.
            Counts describe execution, never the number of yielded issues.
            With lazy process()/iter_results() callers, counts are final only
            after the result iterator is exhausted; early stopping leaves partial
            counts. Validator.validate() consumes that iterator before returning.
            """
            self.snippets_checked = 0
            self.snippets_skipped = 0
            self.snippets_unavailable = 0
            self.titles_checked = 0

        @property
        def cache_dir(self) -> Path:
            """Return the cache directory for this plugin."""
            return self.config.cache_dir

        @cache_dir.setter
        def cache_dir(self, value: Path) -> None:
            """Update the cache directory for this plugin."""
            self.config.cache_dir = value

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
            self.reset_counts()
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
                context.target_class if hasattr(
                    context, "target_class") else None
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
                excerpt_path = f"{path}.{excerpt_field}" if path else excerpt_field

                # A multivalued excerpt slot holds a list: each item is an
                # excerpt in its own right, checked at its own [i] path (#141).
                if isinstance(excerpt_value, list):
                    items = [
                        (item, f"{excerpt_path}[{i}]")
                        for i, item in enumerate(excerpt_value)
                    ]
                else:
                    items = [(excerpt_value, excerpt_path)]
                excerpts: list[tuple[str, str]] = []
                for item, item_path in items:
                    problem = self._excerpt_problem(item, excerpt_field, item_path)
                    if problem is not None:
                        yield problem
                    elif isinstance(item, str) and item:
                        # Anything not text was reported by _excerpt_problem.
                        excerpts.append((item, item_path))

                if not excerpts:
                    continue

                # A reference given but unusable must not let the excerpt pass
                # unchecked. It is reported only if no other reference field
                # supplies a usable identifier, as the fields were always tried
                # in turn.
                unusable: list[LinkMLValidationResult] = []
                for ref_field in reference_fields:
                    ref_value = instance.get(ref_field)
                    # Absent, null or an empty list is no reference. Any other
                    # value, "" and 0 included, was meant as one.
                    if ref_value is None or ref_value == []:
                        continue
                    ref_path = f"{path}.{ref_field}" if path else ref_field
                    # A multivalued slot holds a list; a single value is a
                    # list of one, validated exactly as before.
                    items = ref_value if isinstance(ref_value, list) else [ref_value]
                    references = []
                    field_unusable = []
                    for i, item in enumerate(items):
                        reference_id = self._extract_reference_id(item)
                        if reference_id:
                            references.append((reference_id, self._extract_title(item)))
                        else:
                            item_path = (
                                f"{ref_path}[{i}]" if isinstance(ref_value, list) else ref_path
                            )
                            field_unusable.append(
                                self._unusable_reference(item, item_path, excerpt_path)
                            )
                    if not references:
                        # Deliberately the first such field only: one error
                        # is enough to say the excerpt cannot be checked.
                        unusable = unusable or field_unusable
                        continue
                    validated_with_excerpt = True
                    yield from field_unusable
                    # A title field names the paper, so it applies only when
                    # one paper is cited; listed objects carry their own.
                    if len(references) == 1:
                        reference_id, expected_title = references[0]
                        for title_field in title_fields:
                            title_value = instance.get(title_field)
                            if title_value:
                                expected_title = title_value
                                break
                        for excerpt, item_path in excerpts:
                            yield from self._validate_excerpt(
                                excerpt, reference_id, expected_title, item_path
                            )
                    else:
                        for excerpt, item_path in excerpts:
                            yield from self._validate_excerpt_any(
                                excerpt, references, item_path
                            )
                    # Break after the first field with a usable reference to avoid duplicates
                    break
                else:
                    yield from unusable

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
                            reference_id = self._extract_reference_id(
                                ref_value)
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

            # Only slots actually defined on the class can be induced; data may
            # carry extra keys (a stray ``id``, metadata, a typo) that are not
            # slots. induced_slot() raises ValueError for those, so skip them.
            class_slots = set(self.schema_view.class_slots(class_name))

            for slot_name, value in instance.items():
                if value is None or slot_name not in class_slots:
                    continue

                slot = self.schema_view.induced_slot(slot_name, class_name)
                if not slot:
                    continue

                slot_path = f"{path}.{slot_name}" if path else slot_name

                if isinstance(value, dict):
                    range_class = slot.range
                    if range_class and self.schema_view.get_class(range_class):
                        if slot.multivalued and self._is_keyed_mapping(value, range_class):
                            # A keyed mapping (inlined_as_list: false), not one
                            # object: validate every object in it (#139).
                            yield from self._validate_keyed_objects(
                                value, range_class, slot_path
                            )
                        else:
                            yield from self._validate_instance(
                                value, range_class, slot_path
                            )

                elif isinstance(value, list):
                    for i, item in enumerate(value):
                        item_path = f"{slot_path}[{i}]"
                        if isinstance(item, dict):
                            range_class = slot.range
                            if range_class and self.schema_view.get_class(range_class):
                                yield from self._validate_instance(
                                    item, range_class, item_path
                                )

        def _excerpt_problem(
            self, excerpt: Any, excerpt_field: str, path: str
        ) -> Optional[LinkMLValidationResult]:
            """Report an excerpt that cannot be evidence, or None if it may be.

            A present-but-insubstantial excerpt is evidence of nothing. It must
            be reported rather than skipped: downstream substring matching
            would accept it against almost any reference, and it may have no
            reference at all. An absent excerpt (None) is not a problem here;
            whether the slot is required is the schema's business.

            Examples:
                >>> plugin = ReferenceValidationPlugin(config=ReferenceValidationConfig())
                >>> plugin._excerpt_problem("Protein X binds Y", "supporting_text", "p") is None
                True
                >>> plugin._excerpt_problem(None, "supporting_text", "p") is None
                True
                >>> plugin._excerpt_problem(5, "supporting_text", "p").message
                "Supporting text must be text, not int (in 'supporting_text')"
            """
            if excerpt is None:
                return None
            if isinstance(excerpt, str):
                message = self.validator.check_excerpt_content(excerpt)
            else:
                message = f"Supporting text must be text, not {type(excerpt).__name__}"
            if not message:
                return None
            return LinkMLValidationResult(
                type="reference_validation",
                severity=Severity.ERROR,
                message=f"{message} (in '{excerpt_field}')",
                instance={excerpt_field: excerpt},
                instantiates=path,
                context=[path],
                source="ReferenceValidationPlugin",
            )

        def _is_keyed_mapping(self, value: dict[str, Any], class_name: str) -> bool:
            """Whether a dict in a multivalued slot maps keys to objects of ``class_name``.

            Decided by the keys: a dict any of whose keys is a slot of the class
            (or a slot's alias) is one object written without the list, and is
            validated as such, as it always was. Otherwise it is a keyed mapping,
            which only a class with an identifier or ``key`` slot can have. The
            values are not consulted, so a compact entry beside an object does
            not hide that object; :meth:`_validate_keyed_objects` skips such
            entries one by one.
            """
            if not self.schema_view or not value:
                return False
            if self.schema_view.get_identifier_slot(class_name, use_key=True) is None:
                return False
            slot_names = set(self.schema_view.class_slots(class_name))
            for slot_name in list(slot_names):
                alias = self.schema_view.induced_slot(slot_name, class_name).alias
                if alias:
                    slot_names.add(alias)
            return not any(key in slot_names for key in value)

        def _validate_keyed_objects(
            self, mapping: dict[str, Any], class_name: str, path: str
        ) -> Iterator[LinkMLValidationResult]:
            """Validate each object of a keyed mapping (``inlined_as_list: false``).

            The key is the object's identifier, so it is supplied when the
            object omits it, as LinkML loaders do. A value that is not a mapping
            is the compact form, which sets one non-key slot and so cannot hold
            both a reference and an excerpt; it is left to schema validation.
            """
            if not self.schema_view:
                return
            identifier = self.schema_view.get_identifier_slot(class_name, use_key=True)
            for key, obj in mapping.items():
                if obj is None:
                    obj = {}
                if not isinstance(obj, dict):
                    continue
                if identifier is not None and identifier.name not in obj:
                    obj = {identifier.name: key, **obj}
                yield from self._validate_instance(obj, class_name, f"{path}[{key}]")

        def _convert_severity(self, severity: Any) -> Severity:
            """Translate internal severities to LinkML Severity enum.

            Handles ValidationSeverity (uses WARNING) and falls back to ERROR
            for unknown values to avoid AttributeErrors when LinkML expects
            WARN instead of WARNING.
            """
            if isinstance(severity, Severity):
                return severity

            sev_value = getattr(severity, "value", severity)
            if hasattr(sev_value, "value"):
                sev_value = sev_value.value

            sev_str = str(sev_value).upper() if sev_value is not None else ""
            if sev_str == "ERROR":
                return Severity.ERROR
            if sev_str in {"WARN", "WARNING"}:
                return Severity.WARN
            if sev_str == "INFO":
                return Severity.INFO

            logger.warning(
                "Unknown severity %s, defaulting to ERROR", severity)
            return Severity.ERROR

        def _get_converter(self) -> Optional[Converter]:
            """Get a curies Converter from the schema for CURIE expansion.

            Returns:
                Converter instance or None if unavailable
            """
            if not self.schema_view:
                return None
            schema = self.schema_view.schema
            if schema and schema.prefixes:
                # schema.prefixes is a list of Prefix objects
                # Each Prefix object has a prefix_name and prefix_reference attribute
                prefix_map: dict[str, str] = {}
                for prefix in schema.prefixes:
                    prefix_name = getattr(prefix, "prefix_name", None)
                    prefix_reference = getattr(prefix, "prefix_reference", None)
                    if isinstance(prefix_name, str) and prefix_reference is not None:
                        prefix_map[prefix_name] = str(prefix_reference)
                if prefix_map:
                    return Converter.from_prefix_map(prefix_map)
            return None

        # type: ignore
        def _find_reference_fields(self, class_name: str) -> list[str]:
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

        # type: ignore
        def _find_excerpt_fields(self, class_name: str) -> list[str]:
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

        # type: ignore
        def _find_title_fields(self, class_name: str) -> list[str]:
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
                >>> plugin._extract_reference_id({"id": 123}) is None
                True
            """
            if isinstance(reference_value, dict):
                reference_value = reference_value.get("id") or reference_value.get(
                    "reference_id"
                )
            # Only text can be an identifier; {"id": 123} would crash parsing.
            if isinstance(reference_value, str) and reference_value:
                return reference_value
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
            if result.match_result is not None:
                self.snippets_checked += 1
            elif result.skipped:
                self.snippets_skipped += 1
            elif result.unavailable:
                self.snippets_unavailable += 1
            self.titles_checked += int(result.title_checked)

            if not result.is_valid:
                severity = self._convert_severity(result.severity)
                yield LinkMLValidationResult(
                    type="reference_validation",
                    severity=severity,
                    message=result.message or "Supporting text validation failed",
                    instance={"supporting_text": excerpt,
                              "reference_id": reference_id},
                    instantiates=path,
                    context=[path] if path else [],
                    source="ReferenceValidationPlugin",
                )

        def _validate_excerpt_any(
            self,
            excerpt: str,
            references: list[tuple[str, Optional[str]]],
            path: str,
        ) -> Iterator[LinkMLValidationResult]:
            """Validate an excerpt that may come from any of several references.

            The excerpt passes if one reference holds it; curators cite every
            paper a statement rests on, and a quote comes from one of them.
            References are tried in order and the rest are not fetched once
            one passes. A reference with a skipped prefix vouches for nothing:
            the excerpt is skipped only if every reference is. The excerpt
            counts once, however many were tried.

            Args:
                excerpt: Supporting text to validate
                references: (reference ID, expected title) pairs, in data order
                path: Path in data structure

            Yields:
                One ValidationResult naming every reference, if none holds it
            """
            results = []
            skipped = []
            for reference_id, expected_title in references:
                result = self.validator.validate(
                    excerpt, reference_id, expected_title=expected_title, path=path
                )
                # A skipped prefix is valid only in that nothing was checked;
                # it is no evidence for the excerpt, so the others still decide.
                if result.skipped:
                    skipped.append(reference_id)
                    continue
                if result.is_valid:
                    self.snippets_checked += int(result.match_result is not None)
                    self.titles_checked += int(result.title_checked)
                    return
                results.append((reference_id, result))

            if not results:
                self.snippets_skipped += 1
                return

            if any(result.match_result is not None for _, result in results):
                self.snippets_checked += 1
            elif any(result.unavailable for _, result in results):
                self.snippets_unavailable += 1
            self.titles_checked += int(any(result.title_checked for _, result in results))

            # Severity is declared most severe first; take the most severe so
            # the outcome does not depend on the order references are listed.
            severity = min(
                (self._convert_severity(result.severity) for _, result in results),
                key=list(Severity).index,
            )
            details = "; ".join(
                f"{reference_id}: {result.message or 'validation failed'}"
                for reference_id, result in results
            )
            if skipped:
                details += f"; not checked (skipped prefix): {', '.join(skipped)}"
            yield LinkMLValidationResult(
                type="reference_validation",
                severity=severity,
                message=(
                    f"Supporting text not found in any of the {len(results)} "
                    f"cited references ({details})"
                ),
                instance={
                    "supporting_text": excerpt,
                    "reference_ids": [reference_id for reference_id, _ in results],
                },
                instantiates=path,
                context=[path] if path else [],
                source="ReferenceValidationPlugin",
            )

        def _unusable_reference(
            self, value: Any, path: str, excerpt_path: str
        ) -> LinkMLValidationResult:
            """Report a reference value from which no identifier can be read.

            Examples:
                >>> plugin = ReferenceValidationPlugin(config=ReferenceValidationConfig())
                >>> plugin._unusable_reference({"title": "T"}, "reference", "supporting_text").message
                "Reference at 'reference' has no usable identifier ({'title': 'T'}), so 'supporting_text' cannot be checked"
            """
            return LinkMLValidationResult(
                type="reference_validation",
                severity=Severity.ERROR,
                message=(
                    f"Reference at '{path}' has no usable identifier ({value!r}), "
                    f"so '{excerpt_path}' cannot be checked"
                ),
                instance={"reference": value},
                instantiates=path,
                context=[path, excerpt_path],
                source="ReferenceValidationPlugin",
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
            self.titles_checked += int(result.title_checked)

            if not result.is_valid:
                severity = self._convert_severity(result.severity)
                yield LinkMLValidationResult(
                    type="reference_validation",
                    severity=severity,
                    message=result.message or "Title validation failed",
                    instance={"title": title, "reference_id": reference_id},
                    instantiates=path,
                    context=[path] if path else [],
                    source="ReferenceValidationPlugin",
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
