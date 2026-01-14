"""Tests for field detection module.

Tests that both canonical and legacy URIs are correctly identified.
"""

from unittest.mock import Mock

import pytest

from curies import Converter

from linkml_reference_validator.field_detection import (
    ExcerptURIs,
    FallbackSlotNames,
    ReferenceURIs,
    TitleURIs,
    expand_curie,
    is_excerpt_slot,
    is_reference_slot,
    is_title_slot,
)


class TestExcerptURIs:
    """Tests for ExcerptURIs detection."""

    @pytest.mark.parametrize(
        "uri,expected",
        [
            # Canonical URIs
            ("http://www.w3.org/ns/oa#exact", True),
            ("oa:exact", True),
            # Legacy URIs
            ("https://w3id.org/linkml/excerpt", True),
            ("linkml:excerpt", True),
            # Substring matches
            ("http://example.org/myExcerptField", True),
            ("supporting_text", True),
            # Non-matching URIs
            ("dcterms:title", False),
            ("dcterms:references", False),
            ("http://example.org/something", False),
            ("linkml:authoritative_reference", False),
        ],
    )
    def test_is_excerpt_uri(self, uri: str, expected: bool):
        """Test that excerpt URIs are correctly identified."""
        assert ExcerptURIs.is_excerpt_uri(uri) == expected

    def test_canonical_constant(self):
        """Test canonical URI constant."""
        assert ExcerptURIs.CANONICAL == "http://www.w3.org/ns/oa#exact"
        assert ExcerptURIs.CANONICAL_PREFIXED == "oa:exact"

    def test_legacy_constant(self):
        """Test legacy URI constant."""
        assert ExcerptURIs.LEGACY_LINKML == "https://w3id.org/linkml/excerpt"
        assert ExcerptURIs.LEGACY_LINKML_PREFIXED == "linkml:excerpt"


class TestReferenceURIs:
    """Tests for ReferenceURIs detection."""

    @pytest.mark.parametrize(
        "uri,expected",
        [
            # Canonical URIs
            ("http://purl.org/dc/terms/references", True),
            ("dcterms:references", True),
            ("http://purl.org/dc/terms/source", True),
            ("dcterms:source", True),
            # Legacy URIs
            ("https://w3id.org/linkml/authoritative_reference", True),
            ("linkml:authoritative_reference", True),
            # Substring matches
            ("http://example.org/myReferenceField", True),
            # Non-matching URIs
            ("dcterms:title", False),
            ("oa:exact", False),
            ("linkml:excerpt", False),
            ("http://example.org/something", False),
        ],
    )
    def test_is_reference_uri(self, uri: str, expected: bool):
        """Test that reference URIs are correctly identified."""
        assert ReferenceURIs.is_reference_uri(uri) == expected

    def test_canonical_constant(self):
        """Test canonical URI constant."""
        assert ReferenceURIs.CANONICAL == "http://purl.org/dc/terms/references"
        assert ReferenceURIs.CANONICAL_PREFIXED == "dcterms:references"

    def test_legacy_constant(self):
        """Test legacy URI constant."""
        assert (
            ReferenceURIs.LEGACY_LINKML
            == "https://w3id.org/linkml/authoritative_reference"
        )
        assert ReferenceURIs.LEGACY_LINKML_PREFIXED == "linkml:authoritative_reference"


class TestTitleURIs:
    """Tests for TitleURIs detection."""

    @pytest.mark.parametrize(
        "uri,expected",
        [
            # Canonical URIs
            ("http://purl.org/dc/terms/title", True),
            ("dcterms:title", True),
            # Exact match on "title" (for implements)
            ("title", True),
            # Non-matching URIs
            ("oa:exact", False),
            ("dcterms:references", False),
            ("http://example.org/something", False),
            ("linkml:excerpt", False),
        ],
    )
    def test_is_title_uri(self, uri: str, expected: bool):
        """Test that title URIs are correctly identified."""
        assert TitleURIs.is_title_uri(uri) == expected

    def test_canonical_constant(self):
        """Test canonical URI constant."""
        assert TitleURIs.CANONICAL == "http://purl.org/dc/terms/title"
        assert TitleURIs.CANONICAL_PREFIXED == "dcterms:title"


class TestIsExcerptSlot:
    """Tests for is_excerpt_slot function."""

    def test_canonical_implements(self):
        """Test slot with canonical URI in implements."""
        slot = Mock(implements=["oa:exact"], slot_uri=None)
        assert is_excerpt_slot(slot) is True

    def test_canonical_full_implements(self):
        """Test slot with canonical full URI in implements."""
        slot = Mock(implements=["http://www.w3.org/ns/oa#exact"], slot_uri=None)
        assert is_excerpt_slot(slot) is True

    def test_legacy_implements(self):
        """Test slot with legacy URI in implements."""
        slot = Mock(implements=["linkml:excerpt"], slot_uri=None)
        assert is_excerpt_slot(slot) is True

    def test_canonical_slot_uri(self):
        """Test slot with canonical URI as slot_uri."""
        slot = Mock(implements=None, slot_uri="http://www.w3.org/ns/oa#exact")
        assert is_excerpt_slot(slot) is True

    def test_non_excerpt_slot(self):
        """Test slot that is not an excerpt field."""
        slot = Mock(implements=["dcterms:title"], slot_uri=None)
        assert is_excerpt_slot(slot) is False

    def test_empty_slot(self):
        """Test slot with no implements or slot_uri."""
        slot = Mock(implements=None, slot_uri=None)
        assert is_excerpt_slot(slot) is False

    def test_multiple_implements(self):
        """Test slot with multiple implements including excerpt."""
        slot = Mock(implements=["dcterms:description", "oa:exact"], slot_uri=None)
        assert is_excerpt_slot(slot) is True


class TestIsReferenceSlot:
    """Tests for is_reference_slot function."""

    def test_canonical_implements(self):
        """Test slot with canonical URI in implements."""
        slot = Mock(implements=["dcterms:references"], slot_uri=None)
        assert is_reference_slot(slot) is True

    def test_canonical_source_implements(self):
        """Test slot with canonical source URI in implements."""
        slot = Mock(implements=["dcterms:source"], slot_uri=None)
        assert is_reference_slot(slot) is True

    def test_legacy_implements(self):
        """Test slot with legacy URI in implements."""
        slot = Mock(implements=["linkml:authoritative_reference"], slot_uri=None)
        assert is_reference_slot(slot) is True

    def test_canonical_slot_uri(self):
        """Test slot with canonical URI as slot_uri."""
        slot = Mock(implements=None, slot_uri="http://purl.org/dc/terms/references")
        assert is_reference_slot(slot) is True

    def test_non_reference_slot(self):
        """Test slot that is not a reference field."""
        slot = Mock(implements=["dcterms:title"], slot_uri=None)
        assert is_reference_slot(slot) is False


class TestIsTitleSlot:
    """Tests for is_title_slot function."""

    def test_canonical_implements(self):
        """Test slot with canonical URI in implements."""
        slot = Mock(implements=["dcterms:title"], slot_uri=None)
        assert is_title_slot(slot) is True

    def test_canonical_slot_uri(self):
        """Test slot with canonical URI as slot_uri."""
        slot = Mock(implements=None, slot_uri="http://purl.org/dc/terms/title")
        assert is_title_slot(slot) is True

    def test_title_exact_implements(self):
        """Test slot with 'title' exactly in implements."""
        slot = Mock(implements=["title"], slot_uri=None)
        assert is_title_slot(slot) is True

    def test_non_title_slot(self):
        """Test slot that is not a title field."""
        slot = Mock(implements=["oa:exact"], slot_uri=None)
        assert is_title_slot(slot) is False


class TestFallbackSlotNames:
    """Tests for fallback slot names."""

    def test_excerpt_fallbacks(self):
        """Test excerpt fallback names."""
        assert "supporting_text" in FallbackSlotNames.EXCERPT

    def test_reference_fallbacks(self):
        """Test reference fallback names."""
        assert "reference" in FallbackSlotNames.REFERENCE
        assert "reference_id" in FallbackSlotNames.REFERENCE

    def test_title_fallbacks(self):
        """Test title fallback names."""
        assert "title" in FallbackSlotNames.TITLE


class TestAllCombinations:
    """Test that all valid URI/mechanism combinations work.

    Schema authors can use ANY of the supported URIs in EITHER
    slot_uri OR implements. All combinations should work.
    """

    @pytest.mark.parametrize(
        "uri",
        [
            # Canonical
            "oa:exact",
            "http://www.w3.org/ns/oa#exact",
            # Legacy
            "linkml:excerpt",
            "https://w3id.org/linkml/excerpt",
        ],
    )
    def test_excerpt_via_implements(self, uri: str):
        """Any excerpt URI in implements should be detected."""
        slot = Mock(implements=[uri], slot_uri=None)
        assert is_excerpt_slot(slot) is True

    @pytest.mark.parametrize(
        "uri",
        [
            # Canonical
            "oa:exact",
            "http://www.w3.org/ns/oa#exact",
            # Legacy
            "linkml:excerpt",
            "https://w3id.org/linkml/excerpt",
        ],
    )
    def test_excerpt_via_slot_uri(self, uri: str):
        """Any excerpt URI in slot_uri should be detected."""
        slot = Mock(implements=None, slot_uri=uri)
        assert is_excerpt_slot(slot) is True

    @pytest.mark.parametrize(
        "uri",
        [
            # Canonical
            "dcterms:references",
            "http://purl.org/dc/terms/references",
            # Legacy
            "linkml:authoritative_reference",
            "https://w3id.org/linkml/authoritative_reference",
        ],
    )
    def test_reference_via_implements(self, uri: str):
        """Any reference URI in implements should be detected."""
        slot = Mock(implements=[uri], slot_uri=None)
        assert is_reference_slot(slot) is True

    @pytest.mark.parametrize(
        "uri",
        [
            # Canonical
            "dcterms:references",
            "http://purl.org/dc/terms/references",
            # Legacy
            "linkml:authoritative_reference",
            "https://w3id.org/linkml/authoritative_reference",
        ],
    )
    def test_reference_via_slot_uri(self, uri: str):
        """Any reference URI in slot_uri should be detected."""
        slot = Mock(implements=None, slot_uri=uri)
        assert is_reference_slot(slot) is True

    @pytest.mark.parametrize(
        "uri",
        [
            "dcterms:title",
            "http://purl.org/dc/terms/title",
        ],
    )
    def test_title_via_implements(self, uri: str):
        """Any title URI in implements should be detected."""
        slot = Mock(implements=[uri], slot_uri=None)
        assert is_title_slot(slot) is True

    @pytest.mark.parametrize(
        "uri",
        [
            "dcterms:title",
            "http://purl.org/dc/terms/title",
        ],
    )
    def test_title_via_slot_uri(self, uri: str):
        """Any title URI in slot_uri should be detected."""
        slot = Mock(implements=None, slot_uri=uri)
        assert is_title_slot(slot) is True


class TestExpandCurie:
    """Tests for CURIE expansion."""

    def test_expand_with_matching_prefix(self):
        """CURIE is expanded when prefix matches."""
        conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        result = expand_curie("dc:references", conv)
        assert result == "http://purl.org/dc/terms/references"

    def test_expand_preserves_full_uri(self):
        """Full URIs are returned unchanged."""
        conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        uri = "http://purl.org/dc/terms/title"
        result = expand_curie(uri, conv)
        assert result == uri

    def test_expand_unknown_prefix(self):
        """CURIEs with unknown prefixes are returned unchanged."""
        conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        result = expand_curie("unknown:foo", conv)
        assert result == "unknown:foo"

    def test_expand_no_converter(self):
        """CURIEs are returned unchanged when no converter provided."""
        result = expand_curie("dc:title", None)
        assert result == "dc:title"

    def test_expand_https_uri(self):
        """HTTPS URIs are preserved."""
        conv = Converter.from_prefix_map({"linkml": "https://w3id.org/linkml/"})
        uri = "https://w3id.org/linkml/excerpt"
        result = expand_curie(uri, conv)
        assert result == uri


class TestCustomPrefixes:
    """Tests for custom prefix support in field detection.

    Users may declare custom prefixes like 'dc' instead of 'dcterms'.
    The detection functions should handle these via CURIE expansion.
    """

    def test_excerpt_with_custom_prefix(self):
        """Excerpt field detected with custom prefix for oa namespace."""
        slot = Mock(implements=["ann:exact"], slot_uri=None)
        conv = Converter.from_prefix_map({"ann": "http://www.w3.org/ns/oa#"})
        assert is_excerpt_slot(slot, conv) is True

    def test_excerpt_with_custom_prefix_slot_uri(self):
        """Excerpt field detected via slot_uri with custom prefix."""
        slot = Mock(implements=None, slot_uri="annotation:exact")
        conv = Converter.from_prefix_map({"annotation": "http://www.w3.org/ns/oa#"})
        assert is_excerpt_slot(slot, conv) is True

    def test_reference_with_dc_prefix(self):
        """Reference field detected with 'dc' prefix instead of 'dcterms'."""
        slot = Mock(implements=["dc:references"], slot_uri=None)
        conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        assert is_reference_slot(slot, conv) is True

    def test_reference_with_dct_prefix(self):
        """Reference field detected with 'dct' prefix."""
        slot = Mock(implements=["dct:source"], slot_uri=None)
        conv = Converter.from_prefix_map({"dct": "http://purl.org/dc/terms/"})
        assert is_reference_slot(slot, conv) is True

    def test_title_with_dc_prefix(self):
        """Title field detected with 'dc' prefix instead of 'dcterms'."""
        slot = Mock(implements=["dc:title"], slot_uri=None)
        conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        assert is_title_slot(slot, conv) is True

    def test_title_with_custom_slot_uri(self):
        """Title field detected via slot_uri with custom prefix."""
        slot = Mock(implements=None, slot_uri="mydcterms:title")
        conv = Converter.from_prefix_map({"mydcterms": "http://purl.org/dc/terms/"})
        assert is_title_slot(slot, conv) is True

    def test_unknown_prefix_not_matched(self):
        """Unknown prefix without mapping is not matched."""
        slot = Mock(implements=["unknown:exact"], slot_uri=None)
        conv = Converter.from_prefix_map({"dc": "http://purl.org/dc/terms/"})
        # Should not match because 'unknown' prefix is not in map
        # and doesn't match any pattern directly
        assert is_excerpt_slot(slot, conv) is False

    def test_standard_prefix_works_without_converter(self):
        """Standard prefixes like 'dcterms:' work even without converter."""
        slot = Mock(implements=["dcterms:references"], slot_uri=None)
        assert is_reference_slot(slot, None) is True
        assert is_reference_slot(slot) is True
