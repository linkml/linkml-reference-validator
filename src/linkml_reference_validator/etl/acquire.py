"""Download bytes from a URL with a size cap, and resolve the content format."""

import logging
import re
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse
from urllib.request import url2pathname

import requests  # type: ignore

from linkml_reference_validator.models import ReferenceValidationConfig

logger = logging.getLogger(__name__)

_CONTENT_TYPE_FORMATS = {
    "application/pdf": "pdf",
    "text/html": "html",
    "application/xml": "xml",
    "text/xml": "xml",
    "text/plain": "text",
    "image/svg+xml": "svg",
}

_SUFFIX_FORMATS = {
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".txt": "text",
    ".svg": "svg",
}

#: How much of a payload :func:`sniff_format` reads to find an XML root element.
SNIFF_WINDOW = 64 * 1024

#: The first element of an XML document, past its declaration, comments,
#: processing instructions and doctype.
_ROOT_ELEMENT = re.compile(rb"<([A-Za-z_][\w.:-]*)")


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
        >>> sniff_format(b'<svg xmlns="http://www.w3.org/2000/svg"/>')
        'svg'
        >>> sniff_format(b"<?xml version='1.0'?><!-- by Inkscape --><svg/>")
        'svg'
        >>> sniff_format(b"<!-- Created with Inkscape -->\\n<svg/>")
        'svg'
        >>> sniff_format(b'\\xef\\xbb\\xbf<!DOCTYPE svg PUBLIC "-//W3C//DTD SVG 1.1//EN" "x"><svg/>')
        'svg'
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
    # A byte order mark is not markup; Illustrator writes one, and a bare
    # <!DOCTYPE svg ...> with no XML declaration.
    prolog = head.removeprefix(b"\xef\xbb\xbf")
    prolog_starts = (b"<svg", b"<?xml", b"<!--", b"<!doctype svg")
    if prolog.startswith(prolog_starts) and _root_element(data) in (b"svg", b"svg:svg"):
        return "svg"
    if head.startswith(b"<?xml"):
        return "xml"
    return None


def _root_element(data: bytes) -> Optional[bytes]:
    """Name the root element of an XML payload from its first 64 KB, lowercased.

    The window is wide because exporters put licence comments and doctypes
    with internal subsets ahead of the root. A comment, declaration or
    doctype the window cuts off is still not markup, so nothing after its
    start is read as the root; the root is then unknown.

    Examples:
        >>> _root_element(b'<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "b">]><svg/>')
        b'svg'
        >>> _root_element(b"<!-- <svg> in a comment --><article/>")
        b'article'
        >>> _root_element(b"<!-- cut off by the window <svg>") is None
        True
    """
    head = data[:SNIFF_WINDOW]
    position = 0
    # One forward scan, so a window of unterminated "<!--" stays linear.
    while (start := head.find(b"<", position)) != -1:
        if head.startswith(b"<!--", start):
            end, closing = head.find(b"-->", start + 4), 3
        elif head.startswith(b"<?", start):
            end, closing = head.find(b"?>", start + 2), 2
        elif head[start : start + 9].upper() == b"<!DOCTYPE":
            end, closing = _doctype_end(head, start + 9), 1
        else:
            match = _ROOT_ELEMENT.match(head, start)
            return match.group(1).lower() if match else None
        if end == -1:
            return None
        position = end + closing
    return None


def _doctype_end(head: bytes, position: int) -> int:
    """Index of the ``>`` closing a doctype, past any internal subset; -1 if absent."""
    close = head.find(b">", position)
    subset = head.find(b"[", position)
    if subset != -1 and (close == -1 or subset < close):
        subset_end = head.find(b"]", subset)
        if subset_end == -1:
            return -1
        close = head.find(b">", subset_end)
    return close


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
        manual_redirects = self._is_loopback_url(url)
        with requests.get(
            url,
            headers=headers,
            timeout=60,
            stream=True,
            allow_redirects=not manual_redirects,
        ) as response:
            if response.status_code in {301, 302, 303, 307, 308}:
                location = response.headers.get("location")
                if not location or redirects_remaining == 0:
                    logger.warning(f"Download redirect failed for {url}")
                    return None, None

                resolved_location = urljoin(url, location)
                parsed_location = urlparse(resolved_location)
                if parsed_location.scheme == "file":
                    if not self._is_loopback_url(url):
                        logger.warning(
                            f"Refusing non-local redirect to a file URI from {url}"
                        )
                        return None, None
                    return self._read_local_file(resolved_location, config)

                if parsed_location.scheme in {"http", "https"}:
                    return self._fetch_bytes(
                        resolved_location,
                        config,
                        redirects_remaining=redirects_remaining - 1,
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

        path = Path(url2pathname(parsed.path))
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
