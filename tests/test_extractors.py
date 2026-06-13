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


def _build_minimal_pdf(text: str = "Hello PDF") -> bytes:
    """Build a minimal single-page PDF containing ``text`` (no external deps)."""
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
    ]
    stream = b"BT /F1 24 Tf 72 720 Td (" + text.encode("latin-1") + b") Tj ET"
    objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += str(i).encode() + b" 0 obj\n" + body + b"\nendobj\n"
    xref_pos = len(out)
    n = len(objs) + 1
    out += b"xref\n0 " + str(n).encode() + b"\n0000000000 65535 f \n"
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += (
        b"trailer\n<< /Size " + str(n).encode() + b" /Root 1 0 R >>\n"
        b"startxref\n" + str(xref_pos).encode() + b"\n%%EOF"
    )
    return bytes(out)


def test_pdf_extractor_default_backend():
    from linkml_reference_validator.etl.extract.pdf import PDFExtractor

    pdf_bytes = _build_minimal_pdf("Hello PDF")
    text = PDFExtractor().extract(pdf_bytes, content_type="application/pdf")
    assert text is not None
    assert "Hello" in text


def test_pdf_extractor_named_backend():
    from linkml_reference_validator.etl.extract.pdf import PDFExtractor

    pdf_bytes = _build_minimal_pdf("Backend Test")
    text = PDFExtractor(backend="pypdf").extract(pdf_bytes)
    assert "Backend" in text


def test_pdf_extractor_unknown_backend_raises():
    from linkml_reference_validator.etl.extract.pdf import PDFExtractor

    with pytest.raises(ValueError):
        PDFExtractor(backend="not-a-backend")
