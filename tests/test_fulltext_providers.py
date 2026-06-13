"""Tests for full-text providers and their registry."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import (
    ReferenceValidationConfig,
    ReferenceIdentifiers,
    FullTextLocation,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)


class _FakeProvider(FullTextProvider):
    @classmethod
    def name(cls):
        return "fake"

    def locate(self, ids, config):
        return FullTextLocation(text="some text", format_hint="text", provider="fake")


def test_registry_register_and_get():
    FullTextProviderRegistry.register(_FakeProvider)
    provider = FullTextProviderRegistry.get("fake")
    assert provider is not None
    loc = provider.locate(ReferenceIdentifiers(), ReferenceValidationConfig())
    assert loc.text == "some text"


def test_registry_get_unknown_returns_none():
    assert FullTextProviderRegistry.get("nope") is None
