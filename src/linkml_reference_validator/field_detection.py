"""Field detection for reference validation.

This module provides the logic for identifying which schema slots represent
excerpt fields, reference fields, and title fields. This is separate from
the validation logic itself.

Schema authors can use ANY supported URI in EITHER `slot_uri` OR `implements`.
All combinations work:

Excerpt fields:
    - Canonical: oa:exact (http://www.w3.org/ns/oa#exact)
    - Legacy: linkml:excerpt (https://w3id.org/linkml/excerpt)

Reference fields:
    - Canonical: dcterms:references (http://purl.org/dc/terms/references)
    - Legacy: linkml:authoritative_reference

Title fields:
    - dcterms:title (http://purl.org/dc/terms/title)

Example schema usage (all equivalent for excerpt):
    slot_uri: oa:exact
    implements: [oa:exact]
    implements: [linkml:excerpt]
    slot_uri: linkml:excerpt

Note: Users may declare custom prefixes (e.g., `dc:` instead of `dcterms:`).
The detection functions accept an optional prefix_map to expand CURIEs to
full URIs before matching.
"""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional, Protocol

if TYPE_CHECKING:
    from curies import Converter


# =============================================================================
# URI Constants
# =============================================================================

@dataclass(frozen=True)
class ExcerptURIs:
    """URIs that identify a slot as an excerpt/supporting text field.

    Canonical URI is from W3C Web Annotation vocabulary.
    Legacy URIs are supported for backwards compatibility.

    Examples:
        >>> ExcerptURIs.CANONICAL
        'http://www.w3.org/ns/oa#exact'
        >>> ExcerptURIs.is_excerpt_uri("oa:exact")
        True
        >>> ExcerptURIs.is_excerpt_uri("linkml:excerpt")
        True
    """

    # Canonical: W3C Web Annotation - "copy of the text which is being selected"
    CANONICAL: str = "http://www.w3.org/ns/oa#exact"
    CANONICAL_PREFIXED: str = "oa:exact"

    # Legacy: LinkML excerpt
    LEGACY_LINKML: str = "https://w3id.org/linkml/excerpt"
    LEGACY_LINKML_PREFIXED: str = "linkml:excerpt"

    # Additional patterns to match (substrings)
    MATCH_PATTERNS: tuple[str, ...] = (
        "oa:exact",
        "oa#exact",
        "excerpt",
        "supporting_text",
    )

    @classmethod
    def is_excerpt_uri(cls, uri: str) -> bool:
        """Check if a URI identifies an excerpt field.

        Args:
            uri: URI string to check (can be full or prefixed)

        Returns:
            True if the URI matches any known excerpt pattern

        Examples:
            >>> ExcerptURIs.is_excerpt_uri("http://www.w3.org/ns/oa#exact")
            True
            >>> ExcerptURIs.is_excerpt_uri("oa:exact")
            True
            >>> ExcerptURIs.is_excerpt_uri("linkml:excerpt")
            True
            >>> ExcerptURIs.is_excerpt_uri("https://w3id.org/linkml/excerpt")
            True
            >>> ExcerptURIs.is_excerpt_uri("dcterms:title")
            False
        """
        uri_lower = uri.lower()
        return any(pattern in uri_lower for pattern in cls.MATCH_PATTERNS)


@dataclass(frozen=True)
class ReferenceURIs:
    """URIs that identify a slot as an authoritative reference field.

    Canonical URI is from Dublin Core.
    Legacy URIs are supported for backwards compatibility.

    Examples:
        >>> ReferenceURIs.CANONICAL
        'http://purl.org/dc/terms/references'
        >>> ReferenceURIs.is_reference_uri("dcterms:references")
        True
        >>> ReferenceURIs.is_reference_uri("linkml:authoritative_reference")
        True
    """

    # Canonical: Dublin Core - "related resource that is referenced, cited"
    CANONICAL: str = "http://purl.org/dc/terms/references"
    CANONICAL_PREFIXED: str = "dcterms:references"

    # Alternative canonical: Dublin Core source
    CANONICAL_ALT: str = "http://purl.org/dc/terms/source"
    CANONICAL_ALT_PREFIXED: str = "dcterms:source"

    # Legacy: LinkML authoritative_reference
    LEGACY_LINKML: str = "https://w3id.org/linkml/authoritative_reference"
    LEGACY_LINKML_PREFIXED: str = "linkml:authoritative_reference"

    # Additional patterns to match (substrings)
    MATCH_PATTERNS: tuple[str, ...] = (
        "dcterms:references",
        "dc/terms/references",
        "dcterms:source",
        "dc/terms/source",
        "authoritative_reference",
        "reference",
    )

    @classmethod
    def is_reference_uri(cls, uri: str) -> bool:
        """Check if a URI identifies a reference field.

        Args:
            uri: URI string to check (can be full or prefixed)

        Returns:
            True if the URI matches any known reference pattern

        Examples:
            >>> ReferenceURIs.is_reference_uri("http://purl.org/dc/terms/references")
            True
            >>> ReferenceURIs.is_reference_uri("dcterms:references")
            True
            >>> ReferenceURIs.is_reference_uri("linkml:authoritative_reference")
            True
            >>> ReferenceURIs.is_reference_uri("https://w3id.org/linkml/authoritative_reference")
            True
            >>> ReferenceURIs.is_reference_uri("oa:exact")
            False
        """
        uri_lower = uri.lower()
        return any(pattern in uri_lower for pattern in cls.MATCH_PATTERNS)


@dataclass(frozen=True)
class TitleURIs:
    """URIs that identify a slot as a title field.

    Canonical URI is from Dublin Core.

    Examples:
        >>> TitleURIs.CANONICAL
        'http://purl.org/dc/terms/title'
        >>> TitleURIs.is_title_uri("dcterms:title")
        True
    """

    # Canonical: Dublin Core title
    CANONICAL: str = "http://purl.org/dc/terms/title"
    CANONICAL_PREFIXED: str = "dcterms:title"

    # Additional patterns to match (substrings)
    MATCH_PATTERNS: tuple[str, ...] = (
        "dcterms:title",
        "dc/terms/title",
    )

    @classmethod
    def is_title_uri(cls, uri: str) -> bool:
        """Check if a URI identifies a title field.

        Args:
            uri: URI string to check (can be full or prefixed)

        Returns:
            True if the URI matches any known title pattern

        Examples:
            >>> TitleURIs.is_title_uri("http://purl.org/dc/terms/title")
            True
            >>> TitleURIs.is_title_uri("dcterms:title")
            True
            >>> TitleURIs.is_title_uri("oa:exact")
            False
        """
        uri_lower = uri.lower()
        # Also match exact "title" for implements
        if uri_lower == "title":
            return True
        return any(pattern in uri_lower for pattern in cls.MATCH_PATTERNS)


# =============================================================================
# Slot Protocol (for type hints without requiring linkml dependency)
# =============================================================================

class SlotLike(Protocol):
    """Protocol for slot-like objects from LinkML SchemaView."""

    @property
    def implements(self) -> Optional[list[str]]:
        """List of interface URIs this slot implements."""
        ...

    @property
    def slot_uri(self) -> Optional[str]:
        """The URI for this slot."""
        ...


# =============================================================================
# CURIE Expansion
# =============================================================================

def expand_curie(
    curie: str,
    converter: Optional["Converter"] = None,
) -> str:
    """Expand a CURIE to a full URI using a curies Converter.

    If the CURIE cannot be expanded (no matching prefix), returns the original.

    Args:
        curie: A CURIE like "dc:references" or a full URI
        converter: A curies.Converter instance for prefix expansion

    Returns:
        Expanded URI or original string if no expansion possible

    Examples:
        >>> from curies import Converter
        >>> conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        >>> expand_curie("dc:references", conv)
        'http://purl.org/dc/terms/references'
        >>> expand_curie("http://example.org/foo", conv)
        'http://example.org/foo'
        >>> expand_curie("unknown:foo", conv)
        'unknown:foo'
        >>> expand_curie("dc:title", None)
        'dc:title'
    """
    if converter is None:
        return curie

    # Already a full URI
    if curie.startswith("http://") or curie.startswith("https://"):
        return curie

    # Try to expand using converter
    expanded = converter.expand(curie)
    return expanded if expanded is not None else curie


def _check_uri_match(
    uri: str,
    check_fn: Callable[[str], bool],
    converter: Optional["Converter"] = None,
) -> bool:
    """Check if a URI matches using the given check function, with optional CURIE expansion.

    Args:
        uri: URI or CURIE to check
        check_fn: Function like ExcerptURIs.is_excerpt_uri
        converter: Optional curies.Converter for CURIE expansion

    Returns:
        True if the URI matches (either as-is or after expansion)
    """
    # Check original form first
    if check_fn(uri):
        return True

    # Try expanded form if we have a converter
    if converter:
        expanded = expand_curie(uri, converter)
        if expanded != uri and check_fn(expanded):
            return True

    return False


# =============================================================================
# Field Detection Functions
# =============================================================================

def is_excerpt_slot(
    slot: SlotLike,
    converter: Optional["Converter"] = None,
) -> bool:
    """Check if a slot represents an excerpt/supporting text field.

    Checks both `implements` list and `slot_uri`. Supports custom prefixes
    via a curies.Converter.

    Args:
        slot: A slot object with implements and slot_uri attributes
        converter: Optional curies.Converter for CURIE expansion

    Returns:
        True if the slot represents an excerpt field

    Examples:
        >>> from unittest.mock import Mock
        >>> slot = Mock(implements=["oa:exact"], slot_uri=None)
        >>> is_excerpt_slot(slot)
        True
        >>> slot = Mock(implements=["linkml:excerpt"], slot_uri=None)
        >>> is_excerpt_slot(slot)
        True
        >>> slot = Mock(implements=None, slot_uri="http://www.w3.org/ns/oa#exact")
        >>> is_excerpt_slot(slot)
        True
        >>> slot = Mock(implements=["dcterms:title"], slot_uri=None)
        >>> is_excerpt_slot(slot)
        False
        >>> from curies import Converter
        >>> conv = Converter.from_prefix_map({"ann": "http://www.w3.org/ns/oa#"})
        >>> slot = Mock(implements=["ann:exact"], slot_uri=None)
        >>> is_excerpt_slot(slot, conv)
        True
    """
    if slot.implements:
        for uri in slot.implements:
            if _check_uri_match(uri, ExcerptURIs.is_excerpt_uri, converter):
                return True

    if slot.slot_uri:
        if _check_uri_match(slot.slot_uri, ExcerptURIs.is_excerpt_uri, converter):
            return True

    return False


def is_reference_slot(
    slot: SlotLike,
    converter: Optional["Converter"] = None,
) -> bool:
    """Check if a slot represents an authoritative reference field.

    Checks both `implements` list and `slot_uri`. Supports custom prefixes
    via a curies.Converter.

    Args:
        slot: A slot object with implements and slot_uri attributes
        converter: Optional curies.Converter for CURIE expansion

    Returns:
        True if the slot represents a reference field

    Examples:
        >>> from unittest.mock import Mock
        >>> slot = Mock(implements=["dcterms:references"], slot_uri=None)
        >>> is_reference_slot(slot)
        True
        >>> slot = Mock(implements=["linkml:authoritative_reference"], slot_uri=None)
        >>> is_reference_slot(slot)
        True
        >>> slot = Mock(implements=None, slot_uri="http://purl.org/dc/terms/references")
        >>> is_reference_slot(slot)
        True
        >>> slot = Mock(implements=["oa:exact"], slot_uri=None)
        >>> is_reference_slot(slot)
        False
        >>> from curies import Converter
        >>> conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        >>> slot = Mock(implements=["dc:references"], slot_uri=None)
        >>> is_reference_slot(slot, conv)
        True
    """
    if slot.implements:
        for uri in slot.implements:
            if _check_uri_match(uri, ReferenceURIs.is_reference_uri, converter):
                return True

    if slot.slot_uri:
        if _check_uri_match(slot.slot_uri, ReferenceURIs.is_reference_uri, converter):
            return True

    return False


def is_title_slot(
    slot: SlotLike,
    converter: Optional["Converter"] = None,
) -> bool:
    """Check if a slot represents a title field.

    Checks both `implements` list and `slot_uri`. Supports custom prefixes
    via a curies.Converter.

    Args:
        slot: A slot object with implements and slot_uri attributes
        converter: Optional curies.Converter for CURIE expansion

    Returns:
        True if the slot represents a title field

    Examples:
        >>> from unittest.mock import Mock
        >>> slot = Mock(implements=["dcterms:title"], slot_uri=None)
        >>> is_title_slot(slot)
        True
        >>> slot = Mock(implements=None, slot_uri="http://purl.org/dc/terms/title")
        >>> is_title_slot(slot)
        True
        >>> slot = Mock(implements=["oa:exact"], slot_uri=None)
        >>> is_title_slot(slot)
        False
        >>> from curies import Converter
        >>> conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        >>> slot = Mock(implements=["dc:title"], slot_uri=None)
        >>> is_title_slot(slot, conv)
        True
    """
    if slot.implements:
        for uri in slot.implements:
            if _check_uri_match(uri, TitleURIs.is_title_uri, converter):
                return True

    if slot.slot_uri:
        if _check_uri_match(slot.slot_uri, TitleURIs.is_title_uri, converter):
            return True

    return False


# =============================================================================
# Fallback Slot Names
# =============================================================================

@dataclass(frozen=True)
class FallbackSlotNames:
    """Fallback slot names when no URI-based detection matches.

    These are used as a last resort when slots don't have explicit
    `implements` or `slot_uri` annotations.

    Examples:
        >>> "reference" in FallbackSlotNames.REFERENCE
        True
        >>> "supporting_text" in FallbackSlotNames.EXCERPT
        True
    """

    EXCERPT: tuple[str, ...] = ("supporting_text",)
    REFERENCE: tuple[str, ...] = ("reference", "reference_id")
    TITLE: tuple[str, ...] = ("title",)
