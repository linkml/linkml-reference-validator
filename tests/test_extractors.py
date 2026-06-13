"""Tests for content extractors."""

import pytest

from linkml_reference_validator.etl.extract import ExtractorRegistry
from linkml_reference_validator.etl.extract.base import Extractor


class _FakeExtractor(Extractor):
    @classmethod
    def formats(cls):
        return ["fake"]

    def extract(self, data, *, content_type=None):
        return data.decode("utf-8")


def test_registry_register_and_get():
    ExtractorRegistry.register(_FakeExtractor)
    extractor = ExtractorRegistry.get("fake")
    assert extractor is not None
    assert extractor.extract(b"hello", content_type="text/plain") == "hello"


def test_registry_get_unknown_returns_none():
    assert ExtractorRegistry.get("does-not-exist") is None
