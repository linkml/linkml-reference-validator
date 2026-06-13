"""Tests for declarative custom full-text providers."""

from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import (
    FullTextProviderConfig,
    ReferenceValidationConfig,
    ReferenceIdentifiers,
)
from linkml_reference_validator.etl.fulltext.json_api import JSONAPIFullTextProvider
from linkml_reference_validator.etl.fulltext.loader import (
    load_custom_full_text_providers,
    register_custom_full_text_providers,
)
from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry


def test_config_dataclass():
    cfg = FullTextProviderConfig(
        name="myrepo",
        url_template="https://api.example.org/ft/{doi}",
        location_field="$.pdf_url",
        format_hint="pdf",
    )
    assert cfg.name == "myrepo"
    assert cfg.location_field == "$.pdf_url"


@patch("linkml_reference_validator.etl.fulltext.json_api.requests.get")
def test_json_api_provider_locates_url(mock_get):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"pdf_url": "https://api.example.org/x.pdf"}
    mock_get.return_value = mock_response

    cfg = FullTextProviderConfig(
        name="myrepo",
        url_template="https://api.example.org/ft/{doi}",
        location_field="$.pdf_url",
        format_hint="pdf",
    )
    provider = JSONAPIFullTextProvider(cfg)
    loc = provider.locate(ReferenceIdentifiers(doi="10.1/x"), ReferenceValidationConfig())
    assert loc.url == "https://api.example.org/x.pdf"
    assert loc.format_hint == "pdf"
    assert loc.provider == "myrepo"


def test_loader_reads_yaml_file(tmp_path):
    yaml_file = tmp_path / "providers.yaml"
    yaml_file.write_text(
        "full_text_providers:\n"
        "  myrepo:\n"
        "    url_template: https://api.example.org/ft/{doi}\n"
        "    location_field: $.pdf_url\n"
        "    format_hint: pdf\n"
    )
    configs = load_custom_full_text_providers(providers_file=yaml_file)
    assert len(configs) == 1
    assert configs[0].name == "myrepo"


def test_register_custom_provider(tmp_path):
    yaml_file = tmp_path / "providers.yaml"
    yaml_file.write_text(
        "full_text_providers:\n"
        "  myrepo2:\n"
        "    url_template: https://api.example.org/ft/{doi}\n"
        "    location_field: $.pdf_url\n"
    )
    count = register_custom_full_text_providers(providers_file=yaml_file)
    assert count == 1
    assert FullTextProviderRegistry.get("myrepo2") is not None
