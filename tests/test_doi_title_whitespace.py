"""DOI titles are cached as plain, single-spaced text.

Crossref returns some titles with literal newlines and indentation around inline
markup (issue #166), e.g. ``10.1002/mgg3.1139``, and keeps the HTML/JATS tags
themselves in the title (issue #168), e.g. ``10.18637/jss.v079.i04``. Both made a
correct curated title fail ``validate_title`` or show a spurious cache diff.
"""

from unittest.mock import MagicMock, patch

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.etl.sources.doi import DOISource
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

WRAPPED = (
    "Novel variants in\n                    <i>COL2A1</i>\n"
    "                    causing rare spondyloepiphyseal dysplasia congenita"
)
CLEAN = "Novel variants in COL2A1 causing rare spondyloepiphyseal dysplasia congenita"


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
    )


HTTK_RAW = (
    "<b>httk</b>\n                    :\n                    <i>R</i>\n"
    "                    Package for High-Throughput Toxicokinetics"
)
HTTK = "httk: R Package for High-Throughput Toxicokinetics"


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


def _crossref(title):
    return _response(
        {
            "status": "ok",
            "message": {
                "type": "journal-article",
                "title": [title],
                "container-title": ["J Stat Softw"],
                "published-print": {"date-parts": [[2017]]},
            },
        }
    )


@pytest.mark.parametrize(
    "raw, expected",
    [
        (HTTK_RAW, HTTK),
        ("Uptake of H<sub>2</sub>O and CO<sup>2+</sup>", "Uptake of H2O and CO2+"),
        (
            "<jats:italic>BRCA1, BRCA2</jats:italic>\n , and PALB2 &amp; more",
            "BRCA1, BRCA2, and PALB2 & more",
        ),
        ("<scp>MRI</scp> findings ; a review", "MRI findings; a review"),
        # Double-escaped markup, as some Crossref records carry it.
        ("&amp;lt;i&amp;gt;R&amp;lt;/i&amp;gt; Package", "R Package"),
        # A literal "<" in the text is not markup and survives.
        ("Mortality when p &lt; 0.05", "Mortality when p < 0.05"),
    ],
)
@patch("linkml_reference_validator.etl.sources.utils.requests.get")
def test_crossref_title_markup_is_stripped(mock_get, config, raw, expected):
    mock_get.return_value = _crossref(raw)
    result = DOISource().fetch("10.18637/jss.v079.i04", config)
    assert result is not None
    assert result.title == expected


@patch("linkml_reference_validator.etl.sources.utils.requests.get")
def test_published_title_validates_against_cached_crossref_title(mock_get, config):
    """The published httk title matches what a fresh fetch caches (#168)."""
    mock_get.return_value = _crossref(HTTK_RAW)
    result = DOISource().fetch("10.18637/jss.v079.i04", config)
    assert result is not None

    validator = SupportingTextValidator(config)
    validator.fetcher._save_to_disk(result)

    outcome = validator.validate_title("DOI:10.18637/jss.v079.i04", HTTK)
    assert outcome.is_valid, outcome.message
