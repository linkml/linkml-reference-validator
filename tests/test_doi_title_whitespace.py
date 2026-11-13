"""DOI titles are cached single-spaced even when the registry returns them wrapped.

Crossref returns some titles with literal newlines and indentation around inline
markup (issue #166), e.g. ``10.1002/mgg3.1139``. The cached title must match the
single-spaced form earlier cache files held, or a forced re-fetch shows a title
change that isn't one.
"""

from unittest.mock import MagicMock, patch

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.etl.sources.doi import DOISource
from linkml_reference_validator.models import ReferenceValidationConfig

WRAPPED = (
    "Novel variants in\n                    <i>COL2A1</i>\n"
    "                    causing rare spondyloepiphyseal dysplasia congenita"
)
CLEAN = "Novel variants in <i>COL2A1</i> causing rare spondyloepiphyseal dysplasia congenita"


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
    )


def _response(payload):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = payload
    return mock_response


@patch("linkml_reference_validator.etl.sources.utils.requests.get")
def test_crossref_title_is_cached_and_reloaded_single_spaced(mock_get, config):
    mock_get.return_value = _response(
        {
            "status": "ok",
            "message": {
                "type": "journal-article",
                "title": [WRAPPED],
                "container-title": ["Mol Genet Genomic Med"],
                "published-print": {"date-parts": [[2020]]},
            },
        }
    )

    result = DOISource().fetch("10.1002/mgg3.1139", config)
    assert result is not None
    assert result.title == CLEAN

    fetcher = ReferenceFetcher(config)
    fetcher._save_to_disk(result)
    cache_text = fetcher.get_cache_path("DOI:10.1002/mgg3.1139").read_text()
    assert "\\n" not in cache_text.split("---")[1]
    reloaded = fetcher._load_from_disk("DOI:10.1002/mgg3.1139")
    assert reloaded is not None
    assert reloaded.title == CLEAN


@patch("linkml_reference_validator.etl.sources.utils.requests.get")
def test_datacite_title_is_single_spaced(mock_get, config):
    def fake_get(url, *args, **kwargs):
        if "crossref" in url:
            return _response({"status": "error"})
        if "datacite" in url:
            return _response(
                {
                    "data": {
                        "attributes": {
                            "titles": [{"title": "A  dataset\n   of\tthings "}],
                            "publicationYear": 2021,
                        }
                    }
                }
            )
        return _response({})

    mock_get.side_effect = fake_get

    result = DOISource().fetch("10.5281/zenodo.1234567", config)
    assert result is not None
    assert result.title == "A dataset of things"
