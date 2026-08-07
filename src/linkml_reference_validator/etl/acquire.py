"""Download bytes from a URL with a size cap, and resolve the content format."""

import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlparse

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
        return self._fetch_bytes(url, config, redirects_remaining=5)

    def _fetch_bytes(
        self,
        url: str,
        config: ReferenceValidationConfig,
        redirects_remaining: int,
    ) -> tuple[Optional[bytes], Optional[str]]:
        """Download bytes while handling bounded HTTP and Zotero file redirects."""
        time.sleep(config.rate_limit_delay)

        headers = {
            "User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})",
        }
        # ``with`` guarantees the streamed connection is released on every path,
        # including the early return when the size cap is exceeded mid-stream.
        with requests.get(
            url,
            headers=headers,
            timeout=60,
            stream=True,
            allow_redirects=False,
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location or redirects_remaining == 0:
                    logger.warning(f"Download redirect failed for {url}")
                    return None, None

                parsed_location = urlparse(location)
                if parsed_location.scheme == "file":
                    if not self._is_loopback_url(url):
                        logger.warning(
                            f"Refusing non-local redirect to a file URI from {url}"
                        )
                        return None, None
                    return self._read_local_file(location, config)

                if parsed_location.scheme in {"http", "https"}:
                    return self._fetch_bytes(
                        location, config, redirects_remaining=redirects_remaining - 1
                    )

                logger.warning(f"Unsupported redirect scheme for {url}")
                return None, None

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

    @staticmethod
    def _is_loopback_url(url: str) -> bool:
        """Return True only for an HTTP endpoint on the local machine."""
        parsed = urlparse(url)
        return parsed.scheme == "http" and parsed.hostname in {
            "localhost",
            "127.0.0.1",
            "::1",
        }

    @staticmethod
    def _read_local_file(
        file_url: str, config: ReferenceValidationConfig
    ) -> tuple[Optional[bytes], Optional[str]]:
        """Read a local-API-authorized file URI under the normal size cap."""
        parsed = urlparse(file_url)
        if parsed.netloc not in {"", "localhost"}:
            logger.warning("Refusing a non-local file URI")
            return None, None

        path = Path(unquote(parsed.path))
        content_type = "application/pdf" if path.suffix.lower() == ".pdf" else None
        if not path.is_file():
            logger.warning(f"Local redirected file does not exist: {path}")
            return None, content_type

        max_size = config.max_supplementary_file_size
        if max_size and path.stat().st_size > max_size:
            logger.warning(
                f"Local redirected file exceeded size cap ({max_size} bytes); skipping"
            )
            return None, content_type
        return path.read_bytes(), content_type
