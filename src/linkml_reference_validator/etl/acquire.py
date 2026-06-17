"""Download bytes from a URL with a size cap, and resolve the content format."""

import logging
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import ReferenceValidationConfig

logger = logging.getLogger(__name__)

_CONTENT_TYPE_FORMATS = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/plain": "text",
}

_SUFFIX_FORMATS = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".txt": "text",
}


def sniff_format(data: bytes) -> Optional[str]:
    """Identify a format from the leading bytes of a payload, or ``None`` if unknown.

    Magic-byte detection is more reliable than the server content-type or a provider
    hint, both of which publishers frequently get wrong (e.g. a PDF served as
    ``text/html``, or a ``url_for_pdf`` that actually returns an HTML landing page).

    Examples:
        >>> sniff_format(b"%PDF-1.7\\n...")
        'pdf'
        >>> sniff_format(b"<!DOCTYPE html><html>...")
        'html'
        >>> sniff_format(b"  \\n<html>...")
        'html'
        >>> sniff_format(b"<?xml version='1.0'?><article/>")
        'xml'
        >>> sniff_format(b"just some text") is None
        True
        >>> sniff_format(b"") is None
        True
    """
    if not data:
        return None
    if data[:5] == b"%PDF-":
        return "pdf"
    head = data[:512].lstrip().lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html"):
        return "html"
    if head.startswith(b"<?xml"):
        return "xml"
    return None


def resolve_format(
    content_type: Optional[str], url: Optional[str], format_hint: Optional[str]
) -> Optional[str]:
    """Resolve a format key from content-type, then URL suffix, then provider hint.

    Examples:
        >>> resolve_format("application/pdf", "https://x/y", None)
        'pdf'
        >>> resolve_format(None, "https://x/paper.html", None)
        'html'
        >>> resolve_format(None, "https://x/y", "pdf")
        'pdf'
        >>> resolve_format(None, "https://x/y", None) is None
        True
    """
    if content_type:
        base = content_type.split(";")[0].strip().lower()
        if base in _CONTENT_TYPE_FORMATS:
            return _CONTENT_TYPE_FORMATS[base]

    if url:
        lowered = url.lower().split("?")[0]
        for suffix, fmt in _SUFFIX_FORMATS.items():
            if lowered.endswith(suffix):
                return fmt

    return format_hint


class ContentAcquirer:
    """Stream-download a URL, enforcing the configured size cap.

    Examples:
        >>> isinstance(ContentAcquirer(), object)
        True
    """

    def fetch_bytes(
        self, url: str, config: ReferenceValidationConfig
    ) -> tuple[Optional[bytes], Optional[str]]:
        """Download ``url`` and return ``(bytes, content_type)``.

        Returns ``(None, content_type)`` on non-200 responses or when the size cap
        is exceeded.
        """
        time.sleep(config.rate_limit_delay)

        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
        }
        # ``with`` guarantees the streamed connection is released on every path,
        # including the early return when the size cap is exceeded mid-stream.
        with requests.get(url, headers=headers, timeout=60, stream=True) as response:
            if response.status_code != 200:
                logger.warning(f"Download failed for {url} - status {response.status_code}")
                return None, None

            content_type = response.headers.get("content-type")
            max_size = config.max_supplementary_file_size

            chunks = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                if not chunk:
                    continue
                chunks.extend(chunk)
                if max_size and len(chunks) > max_size:
                    logger.warning(
                        f"Download for {url} exceeded size cap ({max_size} bytes); skipping"
                    )
                    return None, content_type

            return bytes(chunks), content_type
