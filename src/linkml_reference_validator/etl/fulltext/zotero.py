"""Locate user-authorized full text through Zotero's read-only API.

The first implementation targets Zotero's supported local API. It builds a
process-local exact identifier index, finds PDF children of an unambiguous
parent item, and prefers text Zotero has already indexed before returning the
attachment's file endpoint for normal PDF extraction.
"""

import re
import shutil
import sqlite3
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Optional, Protocol

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


class ZoteroBackend(Protocol):
    """Protocol implemented by both HTTP and local-directory Zotero clients."""

    def find_parent_keys(self, ids: ReferenceIdentifiers) -> set[str]:
        """Return unambiguous parent item keys matching supplied identifiers."""
        ...

    def pdf_attachments(self, parent_key: str) -> list[dict]:
        """Return PDF attachment items belonging to a parent item."""
        ...

    def indexed_full_text(self, attachment_key: str) -> Optional[str]:
        """Return Zotero-indexed attachment text, or None when unavailable."""
        ...

    def attachment_file_url(self, attachment_key: str) -> str:
        """Return the URL or file URI for downloading the attachment."""
        ...


class ZoteroDirectoryClient:
    """Read-only client backed by a local Zotero data directory (zotero.sqlite + storage/).

    Examples:
        >>> import tempfile, sqlite3
        >>> d = Path(tempfile.mkdtemp())
        >>> (d / "storage" / "K1").mkdir(parents=True)
        >>> _ = (d / "storage" / "K1" / "p.pdf").write_bytes(b"%PDF-1.4")
        >>> conn = sqlite3.connect(d / "zotero.sqlite")
        >>> _ = conn.executescript('''
        ... CREATE TABLE items (itemID INT, key TEXT);
        ... CREATE TABLE itemAttachments (itemID INT, parentItemID INT, contentType TEXT, path TEXT);
        ... CREATE TABLE fields (fieldID INT, fieldName TEXT);
        ... CREATE TABLE itemDataValues (valueID INT, value TEXT);
        ... CREATE TABLE itemData (itemID INT, fieldID INT, valueID INT);
        ... INSERT INTO items VALUES (1, 'P1'), (2, 'K1');
        ... INSERT INTO itemAttachments VALUES (2, 1, 'application/pdf', 'storage:p.pdf');
        ... INSERT INTO fields VALUES (1, 'DOI');
        ... INSERT INTO itemDataValues VALUES (1, '10.1000/abc');
        ... INSERT INTO itemData VALUES (1, 1, 1);
        ... ''')
        >>> conn.commit(); conn.close()
        >>> ZoteroDirectoryClient(d).find_parent_keys(ReferenceIdentifiers(doi="10.1000/ABC"))
        {'P1'}
    """

    def __init__(self, zotero_dir: Path):
        """Initialize with a Zotero data directory containing zotero.sqlite and storage/."""
        self.zotero_dir = Path(zotero_dir).expanduser()
        self._identifier_index: Optional[dict[tuple[str, str], set[str]]] = None
        self._attachments_by_parent: dict[str, list[dict]] = {}
        self._pdf_paths_by_key: dict[str, Path] = {}

    def find_parent_keys(self, ids: ReferenceIdentifiers) -> set[str]:
        """Return unambiguous parent candidates matching supplied identifiers."""
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
        self._get_identifier_index()
        return list(self._attachments_by_parent.get(parent_key, []))

    def indexed_full_text(self, attachment_key: str) -> Optional[str]:
        """Return Zotero's cached full-text file (.zotero-ft-cache) if present."""
        ft_cache = self.zotero_dir / "storage" / attachment_key / ".zotero-ft-cache"
        if not ft_cache.is_file():
            return None
        content = ft_cache.read_text(encoding="utf-8", errors="ignore")
        return content if content.strip() else None

    def attachment_file_url(self, attachment_key: str) -> str:
        """Return a file:// URI for the attachment PDF."""
        self._get_identifier_index()
        pdf_path = self._pdf_paths_by_key.get(attachment_key)
        if pdf_path is not None:
            return pdf_path.resolve().as_uri()
        return (self.zotero_dir / "storage" / attachment_key).resolve().as_uri()

    def _get_identifier_index(self) -> dict[tuple[str, str], set[str]]:
        """Load and cache exact identifiers and PDF attachments from a temp copy of zotero.sqlite."""
        if self._identifier_index is not None:
            return self._identifier_index

        db_path = self.zotero_dir / "zotero.sqlite"
        if not db_path.is_file():
            raise ZoteroAPIError(f"Zotero database not found: {db_path}")

        with tempfile.TemporaryDirectory() as tmpdir:
            db_copy = Path(tmpdir) / "zotero.sqlite"
            shutil.copy2(db_path, db_copy)
            conn = sqlite3.connect(f"file:{db_copy}?mode=ro", uri=True)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT p.itemID, p.key AS parent_key, a.key AS att_key, ia.path
                FROM itemAttachments ia
                JOIN items a ON ia.itemID = a.itemID
                JOIN items p ON ia.parentItemID = p.itemID
                WHERE ia.contentType = 'application/pdf' AND ia.path LIKE 'storage:%'
                """
            )
            parent_id_to_key: dict[int, str] = {}
            attachments_by_parent: dict[str, list[dict]] = defaultdict(list)
            for parent_id, parent_key, att_key, raw_path in cur.fetchall():
                if not parent_id or not parent_key or not att_key:
                    continue
                rel_name = str(raw_path).split("storage:", 1)[1]
                pdf_path = self.zotero_dir / "storage" / att_key / rel_name
                if not pdf_path.is_file():
                    continue
                parent_id_to_key[parent_id] = parent_key
                self._pdf_paths_by_key[att_key] = pdf_path
                attachments_by_parent[parent_key].append(
                    {
                        "key": att_key,
                        "data": {
                            "key": att_key,
                            "itemType": "attachment",
                            "contentType": "application/pdf",
                            "filename": rel_name,
                        },
                    }
                )

            index: dict[tuple[str, str], set[str]] = defaultdict(set)
            if parent_id_to_key:
                parent_ids = tuple(parent_id_to_key.keys())
                cur.execute(
                    f"""
                    SELECT id.itemID, f.fieldName, idv.value
                    FROM itemData id
                    JOIN fields f ON id.fieldID = f.fieldID
                    JOIN itemDataValues idv ON id.valueID = idv.valueID
                    WHERE id.itemID IN ({",".join("?" for _ in parent_ids)})
                      AND f.fieldName IN ('DOI', 'extra')
                    """,
                    parent_ids,
                )
                for item_id, field_name, val in cur.fetchall():
                    parent_key = parent_id_to_key[item_id]
                    if field_name == "DOI":
                        doi = normalize_doi(val)
                        if doi:
                            index[("doi", doi)].add(parent_key)
                    elif field_name == "extra" and isinstance(val, str):
                        for kind, pattern in _EXTRA_IDENTIFIER_PATTERNS.items():
                            match = pattern.search(val)
                            if match:
                                value = match.group(1)
                                if kind == "pmcid":
                                    value = value.upper()
                                index[(kind, value)].add(parent_key)
            conn.close()

        self._attachments_by_parent = dict(attachments_by_parent)
        self._identifier_index = dict(index)
        return self._identifier_index


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

    def __init__(self, client: Optional[ZoteroBackend] = None):
        """Initialize with an optional client for testing or custom embedding."""
        self._client = client
        self._client_is_injected = client is not None
        self._client_base_url = (
            getattr(client, "base_url", None) if client is not None else None
        )
        self._client_zotero_dir: Optional[Path] = (
            getattr(client, "zotero_dir", None) if client is not None else None
        )

    @classmethod
    def name(cls) -> str:
        """Return the provider-chain name."""
        return "zotero"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        """Return indexed text or a PDF endpoint for an exact Zotero match."""
        if not self._client_is_injected:
            if config.zotero_dir is not None:
                resolved_dir = Path(config.zotero_dir).expanduser()
                if self._client is None or self._client_zotero_dir != resolved_dir:
                    self._client = ZoteroDirectoryClient(resolved_dir)
                    self._client_zotero_dir = resolved_dir
                    self._client_base_url = None
            else:
                base_url = config.zotero_base_url.rstrip("/")
                if self._client is None or self._client_base_url != base_url:
                    self._client = ZoteroClient(config.zotero_base_url)
                    self._client_base_url = base_url
                    self._client_zotero_dir = None
        assert self._client is not None
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
                url=client.attachment_file_url(attachment_key),
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
