"""Locate user-authorized full text through Zotero's read-only API.

The first implementation targets Zotero's supported local API. It builds a
process-local exact identifier index, finds PDF children of an unambiguous
parent item, and prefers text Zotero has already indexed before returning the
attachment's file endpoint for normal PDF extraction.
"""

import re
from collections import defaultdict
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)
from linkml_reference_validator.etl.identifiers import normalize_doi
from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)

MIN_ZOTERO_INDEXED_TEXT_CHARS = 500
_EXTRA_IDENTIFIER_PATTERNS = {
    "pmid": re.compile(r"^PMID\s*:\s*(\d+)\s*$", re.IGNORECASE | re.MULTILINE),
    "pmcid": re.compile(
        r"^PMCID\s*:\s*(PMC\d+)\s*$", re.IGNORECASE | re.MULTILINE
    ),
}


class ZoteroAPIError(RuntimeError):
    """Raised when Zotero's API cannot complete a read operation."""


class ZoteroClient:
    """Small read-only client for the Zotero v3 item API."""

    def __init__(
        self,
        base_url: str,
        session: Optional[requests.Session] = None,
        page_size: int = 100,
    ):
        """Initialize the client with a library base URL and optional session."""
        self.base_url = base_url.rstrip("/")
        self._session = session or requests.Session()
        self._page_size = page_size
        self._identifier_index: Optional[dict[tuple[str, str], set[str]]] = None

    def find_parent_keys(self, ids: ReferenceIdentifiers) -> set[str]:
        """Return unambiguous parent candidates matching supplied identifiers.

        Identifier types absent from Zotero metadata are ignored. When two
        supplied identifier types match different Zotero records, the empty set
        is returned instead of choosing either record.
        """
        index = self._get_identifier_index()
        requested = {
            "doi": normalize_doi(ids.doi),
            "pmid": ids.pmid.strip() if ids.pmid else None,
            "pmcid": ids.pmcid.strip().upper() if ids.pmcid else None,
        }
        matched_sets = [
            index[(kind, value)]
            for kind, value in requested.items()
            if value and index.get((kind, value))
        ]
        if not matched_sets:
            return set()
        candidates = set(matched_sets[0])
        for matches in matched_sets[1:]:
            candidates.intersection_update(matches)
        return candidates

    def pdf_attachments(self, parent_key: str) -> list[dict]:
        """Return PDF attachment items belonging to a parent item."""
        items = self._get_json(f"items/{parent_key}/children")
        if not isinstance(items, list):
            raise ZoteroAPIError("Zotero children response was not a list")
        return [
            item
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("data"), dict)
            and item["data"].get("itemType") == "attachment"
            and item["data"].get("contentType") == "application/pdf"
        ]

    def indexed_full_text(self, attachment_key: str) -> Optional[str]:
        """Return Zotero-indexed attachment text, or None when unavailable."""
        response = self._session.get(
            f"{self.base_url}/items/{attachment_key}/fulltext",
            headers={"Zotero-API-Version": "3"},
            timeout=30,
        )
        if response.status_code == 404:
            return None
        self._require_success(response.status_code, "full-text lookup")
        data = response.json()
        if not isinstance(data, dict):
            raise ZoteroAPIError("Zotero full-text response was not an object")
        content = data.get("content")
        return content if isinstance(content, str) and content.strip() else None

    def attachment_file_url(self, attachment_key: str) -> str:
        """Return the supported Zotero attachment download endpoint."""
        return f"{self.base_url}/items/{attachment_key}/file"

    def _get_identifier_index(self) -> dict[tuple[str, str], set[str]]:
        """Load and cache exact identifiers for top-level Zotero items."""
        if self._identifier_index is not None:
            return self._identifier_index

        items = self._get_paginated_items("items/top")

        index: dict[tuple[str, str], set[str]] = defaultdict(set)
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get("data"), dict):
                continue
            data = item["data"]
            key = data.get("key") or item.get("key")
            if not isinstance(key, str):
                continue

            doi = normalize_doi(data.get("DOI"))
            if doi:
                index[("doi", doi)].add(key)

            extra = data.get("extra", "")
            if isinstance(extra, str):
                for kind, pattern in _EXTRA_IDENTIFIER_PATTERNS.items():
                    match = pattern.search(extra)
                    if match:
                        value = match.group(1)
                        if kind == "pmcid":
                            value = value.upper()
                        index[(kind, value)].add(key)

        self._identifier_index = dict(index)
        return self._identifier_index

    def _get_paginated_items(self, path: str) -> list[object]:
        """GET every page from a Zotero collection endpoint."""
        items: list[object] = []
        start = 0
        while True:
            response = self._session.get(
                f"{self.base_url}/{path.lstrip('/')}",
                headers={"Zotero-API-Version": "3"},
                params={"limit": self._page_size, "start": start},
                timeout=30,
            )
            self._require_success(response.status_code, path)
            page = response.json()
            if not isinstance(page, list):
                raise ZoteroAPIError("Zotero items response was not a list")
            items.extend(page)

            total_header = response.headers.get("Total-Results")
            total = int(total_header) if total_header is not None else None
            start += len(page)
            if not page or (total is not None and start >= total):
                break
            if total is None and len(page) < self._page_size:
                break
        return items

    def _get_json(self, path: str) -> object:
        """GET a Zotero JSON resource and require a successful response."""
        response = self._session.get(
            f"{self.base_url}/{path.lstrip('/')}",
            headers={"Zotero-API-Version": "3"},
            timeout=30,
        )
        self._require_success(response.status_code, path)
        return response.json()

    @staticmethod
    def _require_success(status_code: int, operation: str) -> None:
        """Raise a descriptive error for a non-successful Zotero response."""
        if status_code != 200:
            raise ZoteroAPIError(
                f"Zotero API returned {status_code} during {operation}"
            )


@FullTextProviderRegistry.register
class ZoteroFullTextProvider(FullTextProvider):
    """Find full text in a user's Zotero library by exact identifier."""

    def __init__(self, client: Optional[ZoteroClient] = None):
        """Initialize with an optional client for testing or custom embedding."""
        self._client = client
        self._client_is_injected = client is not None
        self._client_base_url = client.base_url if client is not None else None

    @classmethod
    def name(cls) -> str:
        """Return the provider-chain name."""
        return "zotero"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        """Return indexed text or a PDF endpoint for an exact Zotero match."""
        if self._client is None or (
            not self._client_is_injected
            and self._client_base_url != config.zotero_base_url.rstrip("/")
        ):
            self._client = ZoteroClient(config.zotero_base_url)
            self._client_base_url = config.zotero_base_url.rstrip("/")
        client = self._client
        parent_keys = client.find_parent_keys(ids)
        if len(parent_keys) != 1:
            return None

        parent_key = next(iter(parent_keys))
        attachments = client.pdf_attachments(parent_key)
        if not attachments:
            return None

        keyed_attachments = []
        for attachment in attachments:
            data = attachment["data"]
            attachment_key = data.get("key") or attachment.get("key")
            if isinstance(attachment_key, str):
                keyed_attachments.append((attachment_key, attachment))
        if not keyed_attachments:
            return None
        attachment_key, _ = min(keyed_attachments, key=lambda pair: pair[0])

        text = client.indexed_full_text(attachment_key)
        if text and len(text.strip()) >= MIN_ZOTERO_INDEXED_TEXT_CHARS:
            return FullTextLocation(
                text=text,
                format_hint="text",
                provider=self.name(),
                access_type="user_library",
                source_item_id=attachment_key,
            )

        return FullTextLocation(
            url=client.attachment_file_url(attachment_key),
            format_hint="pdf",
            provider=self.name(),
            access_type="user_library",
            source_item_id=attachment_key,
        )
