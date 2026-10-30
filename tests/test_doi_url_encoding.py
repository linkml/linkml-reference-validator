"""DOIs are percent-encoded in request URLs (issue #137).

A DOI interpolated raw into a URL is cut at ``#`` (a fragment) or ``?`` (a
query), so SICI-style Wiley DOIs, which use ``#`` as a check character, were
requested as a different DOI and reported as not found.
"""

from unittest.mock import MagicMock, patch

import pytest
import requests

from linkml_reference_validator.etl.fulltext.json_api import JSONAPIFullTextProvider
from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider
from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider
from linkml_reference_validator.etl.identifiers import doi_url_path
from linkml_reference_validator.etl.sources.doi import DOISource
from linkml_reference_validator.models import (
    FullTextProviderConfig,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)

SICI = "10.1002/(SICI)1097-4636(199706)35:4<461::AID-JBM6>3.0.CO;2-#"
QUERY = "10.1234/a?b=c"


def _requested_urls(module: str, call):
    """The URLs ``call`` asks for, as requests would actually send them."""
    not_found = MagicMock(status_code=404)
    with patch(f"{module}.requests.get", return_value=not_found) as get:
        call()
    return [
        requests.Request("GET", c.args[0], params=c.kwargs.get("params")).prepare().url
        for c in get.call_args_list
    ]


def _keeps_whole_doi(url: str, doi: str) -> bool:
    return requests.utils.unquote(url.split("?")[0]).endswith(doi)


def test_doi_url_path_keeps_the_slash_and_encodes_the_rest():
    assert doi_url_path("10.1/x") == "10.1/x"
    assert doi_url_path(SICI).endswith("2-%23")
    assert "%3F" in doi_url_path(QUERY)


@pytest.mark.parametrize("doi", [SICI, QUERY])
def test_crossref_and_datacite_request_the_whole_doi(doi):
    config = ReferenceValidationConfig(rate_limit_delay=0)
    urls = _requested_urls(
        "linkml_reference_validator.etl.sources.utils", lambda: DOISource().fetch(doi, config)
    )
    assert [u.split("/")[2] for u in urls] == ["api.crossref.org", "api.datacite.org"]
    assert all(_keeps_whole_doi(u, doi) for u in urls)


@pytest.mark.parametrize(
    "module,provider",
    [
        ("linkml_reference_validator.etl.fulltext.openalex", OpenAlexProvider()),
        ("linkml_reference_validator.etl.fulltext.unpaywall", UnpaywallProvider()),
    ],
)
@pytest.mark.parametrize("doi", [SICI, QUERY])
def test_full_text_providers_request_the_whole_doi(module, provider, doi):
    config = ReferenceValidationConfig(rate_limit_delay=0, email="me@example.org")
    (url,) = _requested_urls(
        module, lambda: provider.locate(ReferenceIdentifiers(doi=doi), config)
    )
    assert _keeps_whole_doi(url, doi)


def test_json_api_template_encodes_the_doi():
    provider = JSONAPIFullTextProvider(
        FullTextProviderConfig(
            name="myrepo", url_template="https://api.example.org/ft/{doi}", location_field="$.u"
        )
    )
    url = provider._build_url(ReferenceIdentifiers(doi=SICI)) or ""
    assert _keeps_whole_doi(requests.Request("GET", url).prepare().url, SICI)
