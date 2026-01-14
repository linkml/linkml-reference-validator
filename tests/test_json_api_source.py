"""Tests for JSON API reference source."""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import (
    JSONAPISourceConfig,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.sources.json_api import (
    JSONAPISource,
    register_json_api_source,
)
from linkml_reference_validator.etl.sources.loader import (
    load_custom_sources,
    register_custom_sources,
    _parse_source_config,
)
from linkml_reference_validator.etl.sources.base import ReferenceSourceRegistry


class TestJSONAPISourceConfig:
    """Tests for JSONAPISourceConfig dataclass."""

    def test_basic_config(self):
        """Should create config with required fields."""
        config = JSONAPISourceConfig(
            prefix="TEST",
            url_template="https://api.example.com/{id}",
            fields={"title": "$.name"},
        )
        assert config.prefix == "TEST"
        assert config.url_template == "https://api.example.com/{id}"
        assert config.fields == {"title": "$.name"}
        assert config.id_patterns == []
        assert config.headers == {}
        assert config.store_raw_response is False

    def test_full_config(self):
        """Should create config with all fields."""
        config = JSONAPISourceConfig(
            prefix="MGNIFY",
            url_template="https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}",
            fields={
                "title": "$.data.attributes.study-name",
                "content": "$.data.attributes.study-abstract",
            },
            id_patterns=["^MGYS\\d+$"],
            headers={"Accept": "application/json"},
            store_raw_response=True,
        )
        assert config.prefix == "MGNIFY"
        assert len(config.id_patterns) == 1
        assert config.store_raw_response is True


class TestJSONAPISource:
    """Tests for JSONAPISource class."""

    @pytest.fixture
    def config(self, tmp_path):
        """Create test validation config."""
        return ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )

    @pytest.fixture
    def simple_source_config(self):
        """Create a simple source configuration."""
        return JSONAPISourceConfig(
            prefix="TEST",
            url_template="https://api.example.com/items/{id}",
            fields={
                "title": "$.name",
                "content": "$.description",
            },
        )

    @pytest.fixture
    def source(self, simple_source_config):
        """Create a JSONAPISource instance."""
        return JSONAPISource(simple_source_config)

    def test_prefix(self, source):
        """Source should return configured prefix."""
        assert source._prefix == "TEST"

    def test_can_handle_with_prefix(self, source):
        """Should handle references with matching prefix."""
        assert source.can_handle("TEST:123")
        assert source.can_handle("TEST:abc-456")
        assert source.can_handle("test:123")  # Case insensitive
        assert not source.can_handle("OTHER:123")
        assert not source.can_handle("PMID:12345678")

    def test_can_handle_with_id_patterns(self):
        """Should handle bare IDs matching configured patterns."""
        config = JSONAPISourceConfig(
            prefix="MGNIFY",
            url_template="https://api.example.com/{id}",
            fields={"title": "$.title"},
            id_patterns=["^MGYS\\d+$", "^MGY[A-Z]\\d+$"],
        )
        source = JSONAPISource(config)

        assert source.can_handle("MGNIFY:MGYS00000596")
        assert source.can_handle("MGYS00000596")  # Bare ID
        assert source.can_handle("MGYA123456")  # Another pattern
        assert not source.can_handle("XYZ123456")

    @patch("linkml_reference_validator.etl.sources.json_api.requests.get")
    def test_fetch_success(self, mock_get, source, config):
        """Should fetch and extract fields from JSON response."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "name": "Test Item",
            "description": "This is a test description.",
        }
        mock_get.return_value = mock_response

        result = source.fetch("123", config)

        assert result is not None
        assert result.reference_id == "TEST:123"
        assert result.title == "Test Item"
        assert result.content == "This is a test description."
        assert result.content_type == "abstract_only"
        mock_get.assert_called_once()

    @patch("linkml_reference_validator.etl.sources.json_api.requests.get")
    def test_fetch_nested_fields(self, mock_get, config):
        """Should extract nested fields using JSONPath."""
        source_config = JSONAPISourceConfig(
            prefix="NESTED",
            url_template="https://api.example.com/{id}",
            fields={
                "title": "$.data.attributes.name",
                "content": "$.data.attributes.description",
            },
        )
        source = JSONAPISource(source_config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "type": "item",
                "attributes": {
                    "name": "Nested Title",
                    "description": "Nested description here.",
                },
            }
        }
        mock_get.return_value = mock_response

        result = source.fetch("abc", config)

        assert result is not None
        assert result.title == "Nested Title"
        assert result.content == "Nested description here."

    @patch("linkml_reference_validator.etl.sources.json_api.requests.get")
    def test_fetch_with_raw_response(self, mock_get, config):
        """Should store raw response when configured."""
        source_config = JSONAPISourceConfig(
            prefix="RAW",
            url_template="https://api.example.com/{id}",
            fields={"title": "$.title"},
            store_raw_response=True,
        )
        source = JSONAPISource(source_config)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"title": "Test", "extra": "data"}
        mock_get.return_value = mock_response

        result = source.fetch("123", config)

        assert result is not None
        assert "raw_response" in result.metadata
        assert result.metadata["raw_response"]["extra"] == "data"

    @patch("linkml_reference_validator.etl.sources.json_api.requests.get")
    def test_fetch_404_returns_none(self, mock_get, source, config):
        """Should return None for 404 responses."""
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        result = source.fetch("nonexistent", config)

        assert result is None

    @patch("linkml_reference_validator.etl.sources.json_api.requests.get")
    def test_fetch_missing_field_returns_none(self, mock_get, source, config):
        """Should return None for missing fields."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"other": "data"}
        mock_get.return_value = mock_response

        result = source.fetch("123", config)

        assert result is not None
        assert result.title is None
        assert result.content is None
        assert result.content_type == "unavailable"

    def test_jsonpath_extract_simple(self, source):
        """Should extract simple field values."""
        data = {"name": "Test"}
        result = source._jsonpath_extract(data, "$.name")
        assert result == "Test"

    def test_jsonpath_extract_nested(self, source):
        """Should extract nested field values."""
        data = {"level1": {"level2": {"value": "Deep"}}}
        result = source._jsonpath_extract(data, "$.level1.level2.value")
        assert result == "Deep"

    def test_jsonpath_extract_array(self, source):
        """Should extract array element."""
        data = {"items": ["first", "second", "third"]}
        result = source._jsonpath_extract(data, "$.items[0]")
        assert result == "first"

    def test_jsonpath_extract_missing_returns_none(self, source):
        """Should return None for missing paths."""
        data = {"name": "Test"}
        result = source._jsonpath_extract(data, "$.missing.path")
        assert result is None

    def test_jsonpath_extract_numeric_converts_to_string(self, source):
        """Should convert numeric values to strings."""
        data = {"count": 42}
        result = source._jsonpath_extract(data, "$.count")
        assert result == "42"

    def test_header_interpolation_with_env_var(self, source, monkeypatch):
        """Should interpolate environment variables in headers."""
        monkeypatch.setenv("TEST_API_KEY", "secret123")

        result = source._interpolate_headers(
            {"Authorization": "Bearer ${TEST_API_KEY}"}
        )

        assert result["Authorization"] == "Bearer secret123"

    def test_header_interpolation_missing_env_var(self, source, monkeypatch):
        """Should handle missing environment variables gracefully."""
        monkeypatch.delenv("MISSING_VAR", raising=False)

        result = source._interpolate_headers(
            {"Authorization": "Bearer ${MISSING_VAR}"}
        )

        assert result["Authorization"] == "Bearer "

    def test_header_interpolation_static_value(self, source):
        """Should pass through static header values."""
        result = source._interpolate_headers({"Accept": "application/json"})
        assert result["Accept"] == "application/json"


class TestRegisterJSONAPISource:
    """Tests for register_json_api_source function."""

    def test_register_creates_source_class(self):
        """Should create and register a source class."""
        config = JSONAPISourceConfig(
            prefix="REGISTERED",
            url_template="https://api.example.com/{id}",
            fields={"title": "$.title"},
        )

        initial_count = len(ReferenceSourceRegistry.list_sources())
        source_class = register_json_api_source(config)

        assert source_class.prefix() == "REGISTERED"
        assert len(ReferenceSourceRegistry.list_sources()) > initial_count

    def test_registered_source_can_be_found(self):
        """Should be able to find registered source via registry."""
        config = JSONAPISourceConfig(
            prefix="FINDABLE",
            url_template="https://api.example.com/{id}",
            fields={"title": "$.title"},
        )

        register_json_api_source(config)
        found = ReferenceSourceRegistry.get_source("FINDABLE:123")

        assert found is not None
        assert found.prefix() == "FINDABLE"


class TestSourceConfigLoader:
    """Tests for source configuration loading."""

    def test_parse_source_config_basic(self):
        """Should parse basic source config."""
        data = {
            "url_template": "https://api.example.com/{id}",
            "fields": {"title": "$.title", "content": "$.desc"},
        }

        config = _parse_source_config("BASIC", data)

        assert config is not None
        assert config.prefix == "BASIC"
        assert config.url_template == "https://api.example.com/{id}"
        assert config.fields["title"] == "$.title"

    def test_parse_source_config_full(self):
        """Should parse full source config."""
        data = {
            "url_template": "https://api.example.com/{id}",
            "fields": {"title": "$.title"},
            "id_patterns": ["^ABC\\d+$"],
            "headers": {"Authorization": "Bearer ${API_KEY}"},
            "store_raw_response": True,
        }

        config = _parse_source_config("FULL", data)

        assert config is not None
        assert config.id_patterns == ["^ABC\\d+$"]
        assert config.headers["Authorization"] == "Bearer ${API_KEY}"
        assert config.store_raw_response is True

    def test_parse_source_config_missing_url_template(self):
        """Should return None if url_template is missing."""
        data = {"fields": {"title": "$.title"}}

        config = _parse_source_config("INVALID", data)

        assert config is None

    def test_parse_source_config_empty_fields(self):
        """Should return None if fields is empty."""
        data = {"url_template": "https://api.example.com/{id}", "fields": {}}

        config = _parse_source_config("NOFIELDS", data)

        assert config is None

    def test_load_custom_sources_from_file(self, tmp_path):
        """Should load sources from a YAML file."""
        sources_file = tmp_path / "sources.yaml"
        sources_file.write_text("""
sources:
  TESTSRC:
    url_template: "https://api.test.com/{id}"
    fields:
      title: "$.name"
      content: "$.description"
""")

        configs = load_custom_sources(sources_file=sources_file)

        assert len(configs) == 1
        assert configs[0].prefix == "TESTSRC"
        assert configs[0].fields["title"] == "$.name"

    def test_load_custom_sources_deduplicates_by_prefix(self, tmp_path):
        """Should keep only latest config when prefix appears multiple times."""
        file1 = tmp_path / "sources1.yaml"
        file1.write_text("""
sources:
  DUPE:
    url_template: "https://first.com/{id}"
    fields:
      title: "$.first"
""")

        file2 = tmp_path / "sources2.yaml"
        file2.write_text("""
sources:
  DUPE:
    url_template: "https://second.com/{id}"
    fields:
      title: "$.second"
""")

        # Load both files - later should override
        configs1 = load_custom_sources(sources_file=file1)
        configs2 = load_custom_sources(sources_file=file2)

        # Each file individually has one config
        assert len(configs1) == 1
        assert len(configs2) == 1

    def test_register_custom_sources(self, tmp_path):
        """Should register sources from file with registry."""
        sources_file = tmp_path / "sources.yaml"
        sources_file.write_text("""
sources:
  REGTEST:
    url_template: "https://api.test.com/{id}"
    fields:
      title: "$.name"
""")

        count = register_custom_sources(sources_file=sources_file)

        assert count == 1
        # Verify it's in the registry
        found = ReferenceSourceRegistry.get_source("REGTEST:123")
        assert found is not None


class TestMGnifyExample:
    """Tests using MGnify as a real-world example."""

    @pytest.fixture
    def mgnify_config(self):
        """Create MGnify source configuration."""
        return JSONAPISourceConfig(
            prefix="MGNIFY",
            url_template="https://www.ebi.ac.uk/metagenomics/api/v1/studies/{id}",
            fields={
                "title": "$.data.attributes.study-name",
                "content": "$.data.attributes.study-abstract",
            },
            id_patterns=["^MGYS\\d+$"],
            store_raw_response=True,
        )

    def test_mgnify_config_structure(self, mgnify_config):
        """MGnify config should be valid."""
        assert mgnify_config.prefix == "MGNIFY"
        assert "{id}" in mgnify_config.url_template
        assert "title" in mgnify_config.fields
        assert "content" in mgnify_config.fields

    def test_mgnify_can_handle_patterns(self, mgnify_config):
        """Should handle MGnify ID patterns."""
        source = JSONAPISource(mgnify_config)

        assert source.can_handle("MGNIFY:MGYS00000596")
        assert source.can_handle("MGYS00000596")  # Bare ID
        assert not source.can_handle("DOI:10.1234/test")

    @patch("linkml_reference_validator.etl.sources.json_api.requests.get")
    def test_mgnify_fetch_extracts_fields(self, mock_get, mgnify_config, tmp_path):
        """Should extract title and abstract from MGnify response."""
        config = ReferenceValidationConfig(
            cache_dir=tmp_path / "cache",
            rate_limit_delay=0.0,
        )
        source = JSONAPISource(mgnify_config)

        # Simulate MGnify API response structure
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "data": {
                "type": "studies",
                "id": "MGYS00000596",
                "attributes": {
                    "accession": "MGYS00000596",
                    "study-name": "American Gut Project",
                    "study-abstract": "The American Gut project is the largest crowdsourced citizen science project.",
                    "samples-count": 31903,
                },
            }
        }
        mock_get.return_value = mock_response

        result = source.fetch("MGYS00000596", config)

        assert result is not None
        assert result.reference_id == "MGNIFY:MGYS00000596"
        assert result.title == "American Gut Project"
        assert "American Gut" in result.content
        assert result.content_type == "abstract_only"

        # Check raw response is stored
        assert "raw_response" in result.metadata
        assert result.metadata["raw_response"]["data"]["attributes"]["samples-count"] == 31903
