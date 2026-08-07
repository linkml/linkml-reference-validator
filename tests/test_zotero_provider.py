"""Tests for Zotero private-library full-text lookup."""

from unittest.mock import MagicMock

import pytest

from linkml_reference_validator.models import (
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)


def _json_response(
    data: object, status_code: int = 200, headers: dict[str, str] | None = None
) -> MagicMock:
    """Return a response double carrying a realistic Zotero JSON payload."""
    response = MagicMock()
    response.status_code = status_code
    response.headers = headers or {}
    response.json.return_value = data
    return response


def _zotero_item(
    key: str,
    *,
    doi: str | None = None,
    extra: str = "",
    item_type: str = "journalArticle",
    content_type: str | None = None,
    filename: str | None = None,
) -> dict:
    """Build the subset of a Zotero v3 item used by the provider contract."""
    data = {"key": key, "itemType": item_type, "extra": extra}
    if doi is not None:
        data["DOI"] = doi
    if content_type is not None:
        data["contentType"] = content_type
    if filename is not None:
        data["filename"] = filename
    return {"key": key, "data": data}


def test_normalize_doi_handles_common_zotero_forms():
    """DOIs compare independently of URL form, prefix, whitespace, or case."""
    from linkml_reference_validator.etl.fulltext.zotero import normalize_doi

    assert normalize_doi(" https://doi.org/10.1000/ABC ") == "10.1000/abc"
    assert normalize_doi("doi:10.1000/ABC") == "10.1000/abc"
    assert normalize_doi("") is None


def test_client_indexes_exact_doi_pmid_and_pmcid():
    """The client builds an exact identifier index from Zotero item JSON."""
    from linkml_reference_validator.etl.fulltext.zotero import ZoteroClient

    session = MagicMock()
    session.get.return_value = _json_response(
        [
            _zotero_item(
                "PARENT1",
                doi="https://doi.org/10.1000/ABC",
                extra="PMID: 12345678\nPMCID: PMC7654321",
            ),
            _zotero_item("PARENT2", doi="10.2000/other"),
        ]
    )
    client = ZoteroClient("http://localhost:23119/api/users/0", session=session)

    assert client.find_parent_keys(ReferenceIdentifiers(doi="10.1000/abc")) == {
        "PARENT1"
    }
    assert client.find_parent_keys(ReferenceIdentifiers(pmid="12345678")) == {
        "PARENT1"
    }
    assert client.find_parent_keys(ReferenceIdentifiers(pmcid="PMC7654321")) == {
        "PARENT1"
    }


def test_client_paginates_top_level_items():
    """Identifier indexing covers every Zotero page, not only the first one."""
    from linkml_reference_validator.etl.fulltext.zotero import ZoteroClient

    session = MagicMock()
    session.get.side_effect = [
        _json_response(
            [_zotero_item("PARENT1", doi="10.1000/first")],
            headers={"Total-Results": "2"},
        ),
        _json_response(
            [_zotero_item("PARENT2", doi="10.1000/second")],
            headers={"Total-Results": "2"},
        ),
    ]
    client = ZoteroClient(
        "http://localhost:23119/api/users/0", session=session, page_size=1
    )

    assert client.find_parent_keys(ReferenceIdentifiers(doi="10.1000/second")) == {
        "PARENT2"
    }
    assert [call.kwargs["params"] for call in session.get.call_args_list] == [
        {"limit": 1, "start": 0},
        {"limit": 1, "start": 1},
    ]


def test_client_requires_all_supplied_identifiers_to_name_same_parent():
    """Conflicting exact identifiers are ambiguous rather than silently merged."""
    from linkml_reference_validator.etl.fulltext.zotero import ZoteroClient

    session = MagicMock()
    session.get.return_value = _json_response(
        [
            _zotero_item("DOI_PARENT", doi="10.1000/a"),
            _zotero_item("PMID_PARENT", extra="PMID: 123"),
        ]
    )
    client = ZoteroClient("http://localhost:23119/api/users/0", session=session)

    assert client.find_parent_keys(
        ReferenceIdentifiers(doi="10.1000/a", pmid="123")
    ) == set()


def test_provider_prefers_zotero_indexed_full_text():
    """Usable Zotero-indexed text avoids downloading and reparsing the PDF."""
    from linkml_reference_validator.etl.fulltext.zotero import (
        ZoteroClient,
        ZoteroFullTextProvider,
    )

    session = MagicMock()
    session.get.side_effect = [
        _json_response([_zotero_item("PARENT", doi="10.1000/a")]),
        _json_response(
            [
                _zotero_item(
                    "PDF1",
                    item_type="attachment",
                    content_type="application/pdf",
                    filename="article.pdf",
                )
            ]
        ),
        _json_response({"content": "indexed full text " * 40, "indexedPages": 8}),
    ]
    client = ZoteroClient("http://localhost:23119/api/users/0", session=session)
    provider = ZoteroFullTextProvider(client=client)

    location = provider.locate(
        ReferenceIdentifiers(doi="10.1000/a"),
        ReferenceValidationConfig(rate_limit_delay=0.0),
    )

    assert location is not None
    assert location.text == "indexed full text " * 40
    assert location.format_hint == "text"
    assert location.provider == "zotero"
    assert location.access_type == "user_library"
    assert location.source_item_id == "PDF1"
    assert location.oa_status is None


def test_provider_falls_back_to_pdf_file_endpoint():
    """An unindexed attachment is returned as a PDF URL for normal extraction."""
    from linkml_reference_validator.etl.fulltext.zotero import (
        ZoteroClient,
        ZoteroFullTextProvider,
    )

    session = MagicMock()
    session.get.side_effect = [
        _json_response([_zotero_item("PARENT", extra="PMID: 123")]),
        _json_response(
            [
                _zotero_item(
                    "PDF1",
                    item_type="attachment",
                    content_type="application/pdf",
                    filename="article.pdf",
                )
            ]
        ),
        _json_response({}, status_code=404),
    ]
    client = ZoteroClient("http://localhost:23119/api/users/0", session=session)
    provider = ZoteroFullTextProvider(client=client)

    location = provider.locate(
        ReferenceIdentifiers(pmid="123"),
        ReferenceValidationConfig(rate_limit_delay=0.0),
    )

    assert location is not None
    assert location.url == "http://localhost:23119/api/users/0/items/PDF1/file"
    assert location.format_hint == "pdf"
    assert location.access_type == "user_library"
    assert location.source_item_id == "PDF1"


def test_provider_returns_none_for_ambiguous_doi():
    """Duplicate DOI records do not choose an arbitrary parent item."""
    from linkml_reference_validator.etl.fulltext.zotero import (
        ZoteroClient,
        ZoteroFullTextProvider,
    )

    session = MagicMock()
    session.get.return_value = _json_response(
        [
            _zotero_item("PARENT1", doi="10.1000/a"),
            _zotero_item("PARENT2", doi="10.1000/a"),
        ]
    )
    client = ZoteroClient("http://localhost:23119/api/users/0", session=session)

    assert ZoteroFullTextProvider(client=client).locate(
        ReferenceIdentifiers(doi="10.1000/a"),
        ReferenceValidationConfig(rate_limit_delay=0.0),
    ) is None


def test_provider_reuses_default_client_between_references(monkeypatch):
    """Scanning a cache builds the Zotero library index only once."""
    from linkml_reference_validator.etl.fulltext import zotero

    client = MagicMock()
    client.find_parent_keys.return_value = set()
    constructor = MagicMock(return_value=client)
    monkeypatch.setattr(zotero, "ZoteroClient", constructor)
    provider = zotero.ZoteroFullTextProvider()
    config = ReferenceValidationConfig(
        zotero_base_url="http://localhost:23119/api/users/0"
    )

    provider.locate(ReferenceIdentifiers(doi="10.1000/a"), config)
    provider.locate(ReferenceIdentifiers(doi="10.1000/b"), config)

    constructor.assert_called_once_with(config.zotero_base_url)


def test_provider_selects_pdf_attachment_deterministically():
    """Multiple PDFs use a stable key-based choice independent of API order."""
    from linkml_reference_validator.etl.fulltext.zotero import ZoteroFullTextProvider

    client = MagicMock()
    client.find_parent_keys.return_value = {"PARENT"}
    client.pdf_attachments.return_value = [
        _zotero_item("PDF_Z", item_type="attachment", content_type="application/pdf"),
        _zotero_item("PDF_A", item_type="attachment", content_type="application/pdf"),
    ]
    client.indexed_full_text.return_value = None
    client.attachment_file_url.side_effect = lambda key: f"file:{key}"

    location = ZoteroFullTextProvider(client=client).locate(
        ReferenceIdentifiers(doi="10.1000/a"), ReferenceValidationConfig()
    )

    assert location is not None
    assert location.source_item_id == "PDF_A"


def test_client_surfaces_disabled_local_api():
    """A disabled Zotero local API is an external error, not a library miss."""
    from linkml_reference_validator.etl.fulltext.zotero import (
        ZoteroAPIError,
        ZoteroClient,
    )

    session = MagicMock()
    session.get.return_value = _json_response({}, status_code=403)
    client = ZoteroClient("http://localhost:23119/api/users/0", session=session)

    with pytest.raises(ZoteroAPIError, match="403"):
        client.find_parent_keys(ReferenceIdentifiers(doi="10.1000/a"))
