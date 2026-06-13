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


def test_html_extractor():
    from linkml_reference_validator.etl.extract.html import HTMLExtractor

    html = b"<html><head><title>T</title></head><body><p>Hello</p><p>World</p></body></html>"
    text = HTMLExtractor().extract(html, content_type="text/html")
    assert "Hello" in text
    assert "World" in text


def test_xml_extractor_jats_body():
    from linkml_reference_validator.etl.extract.xml import XMLExtractor

    xml = b"""<article><body><sec><p>First paragraph.</p><p>Second paragraph.</p></sec></body></article>"""
    text = XMLExtractor().extract(xml, content_type="application/xml")
    assert "First paragraph." in text
    assert "Second paragraph." in text


def test_xml_extractor_no_body_returns_none():
    from linkml_reference_validator.etl.extract.xml import XMLExtractor

    xml = b"<article><front><title>x</title></front></article>"
    assert XMLExtractor().extract(xml, content_type="application/xml") is None
