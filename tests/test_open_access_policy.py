"""Only openly-licensed *files* are fetched into the public cache.

Two rules, one policy. Both follow from the contract PR #61 established for the
Zotero provider: material a user may lawfully read is not automatically material
a project may redistribute, and the public, checked-in reference cache is
redistribution.

**Do not scrape.** A provider that has only a landing/article *page* — an
``oa_url`` with no ``pdf_url`` — has not found a file. Fetching it means
scraping HTML from a host that did not offer it for machine retrieval, and the
hosts defend against exactly that: PMC serves a reCAPTCHA interstitial (with
HTTP 200, so nothing downstream can tell it from content). Providers now return
``None`` rather than a page URL.

**Bronze is not open.** ``oa_status: bronze`` means free to read on the
publisher's site under no open licence. The full text may be readable; it is
not redistributable. Bronze locations are marked with a non-open
``access_type``, which ``_enrich_with_full_text`` already skips for ordinary
validation — the same route Zotero's private-library material takes.

**Green is decided by its licence.** ``green`` names a repository, not a
permission, so a deposit is open when it states its terms and not when it merely
states its address.

The information needed for both decisions was already being recorded
(``oa_status``) and simply was not consulted: ``access_type`` was set by the
Zotero provider alone, so everything OpenAlex and Unpaywall returned defaulted
to ``None`` and was saved as public.
"""

import pytest
from unittest.mock import patch, MagicMock

from linkml_reference_validator.models import (
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)


@pytest.fixture
def config(tmp_path):
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache", rate_limit_delay=0.0, email="me@example.org"
    )


def _openalex_payload(
    oa_status, pdf_url, oa_url="https://oa.example.org/landing", license="cc-by"
):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "open_access": {"is_oa": True, "oa_status": oa_status, "oa_url": oa_url},
        "best_oa_location": {"pdf_url": pdf_url, "license": license},
    }
    return response


def _unpaywall_payload(
    oa_status, pdf_url, landing="https://oa.example.org/landing", license="cc-by"
):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "is_oa": True,
        "oa_status": oa_status,
        "best_oa_location": {
            "url_for_pdf": pdf_url,
            "url": landing,
            "license": license,
        },
    }
    return response


# --------------------------------------------------------------------------
# Rule 1: no landing-page scraping
# --------------------------------------------------------------------------


@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_openalex_does_not_return_a_landing_page(mock_get, config):
    """An ``oa_url`` with no ``pdf_url`` is a page, not a file.

    Asserted on what matters -- nothing fetchable comes back -- rather than on
    ``is None``. The provider reports the decline instead of returning nothing,
    so the chain can tell "we refused this" from "there is none", but a declined
    location carries no ``url`` and no ``text`` and is never fetched.
    """
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload("gold", pdf_url=None)

    location = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)

    assert location.declined == "landing_page_only"
    assert location.url is None and location.text is None


@patch("linkml_reference_validator.etl.fulltext.unpaywall.requests.get")
def test_unpaywall_does_not_return_a_landing_page(mock_get, config):
    from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

    mock_get.return_value = _unpaywall_payload("gold", pdf_url=None)

    location = UnpaywallProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)

    assert location.declined == "landing_page_only"
    assert location.url is None and location.text is None


@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_a_pdf_is_still_returned(mock_get, config):
    """The rule removes page scraping, not open-access fetching."""
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        "gold", pdf_url="https://oa.example.org/paper.pdf"
    )

    location = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)

    assert location is not None
    assert location.url == "https://oa.example.org/paper.pdf"
    assert location.format_hint == "pdf"


# --------------------------------------------------------------------------
# Rule 2: bronze is readable, not redistributable
# --------------------------------------------------------------------------


@pytest.mark.parametrize("oa_status", ["gold", "diamond", "hybrid"])
@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_openly_licensed_statuses_are_public(mock_get, config, oa_status):
    """These statuses carry an open licence by definition, licence field or not."""
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        oa_status, pdf_url="https://oa.example.org/paper.pdf", license=None
    )

    location = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)

    assert location.access_type == "open"


@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_green_with_a_stated_licence_is_public(mock_get, config):
    """A repository deposit that states its terms is redistributable."""
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        "green", pdf_url="https://repo.example.org/paper.pdf", license="cc-by"
    )

    assert (
        OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config).access_type
        == "open"
    )


@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_green_without_a_licence_is_not_public(mock_get, config):
    """``green`` names a repository, not a permission.

    A PMC author manuscript is free to read under a funder policy whose
    redistribution terms vary by publisher -- the same shape of claim as bronze,
    with a different host.
    """
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        "green", pdf_url="https://repo.example.org/paper.pdf", license=None
    )

    assert (
        OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config).access_type
        != "open"
    )


@patch("linkml_reference_validator.etl.fulltext.unpaywall.requests.get")
def test_unpaywall_green_without_a_licence_is_not_public(mock_get, config):
    from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

    mock_get.return_value = _unpaywall_payload(
        "green", pdf_url="https://repo.example.org/paper.pdf", license=None
    )

    assert (
        UnpaywallProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config).access_type
        != "open"
    )


@pytest.mark.parametrize("licence", ["other-oa", "implied-oa", "publisher-specific-oa"])
@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_green_with_a_non_licence_sentinel_is_not_public(mock_get, config, licence):
    """These name the *absence* of a licence statement, and they are strings.

    A truthiness test reads them as "this deposit states its terms" when they
    say the opposite. ``other-oa`` alone covers 5.9M works in OpenAlex, and
    Unpaywall's ``implied-oa`` is documented as a copy believed free with no
    licence statement found -- which is precisely the bare funder-policy
    repository deposit this rule was written about.
    """
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        "green", pdf_url="https://repo.example.org/paper.pdf", license=licence
    )

    assert (
        OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config).access_type
        != "open"
    )


@pytest.mark.parametrize(
    "licence", ["cc-by", "cc-by-nc", "cc-by-nc-nd", "cc-by-sa", "cc0", "public-domain"]
)
@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_green_with_a_real_licence_is_public(mock_get, config, licence):
    """Every CC variant grants verbatim redistribution, which is what caching is.

    ``nc`` restricts commercial use and ``nd`` restricts derivatives; neither
    restricts holding a copy, so the whole family qualifies.
    """
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        "green", pdf_url="https://repo.example.org/paper.pdf", license=licence
    )

    assert (
        OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config).access_type
        == "open"
    )


@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_a_licence_does_not_rescue_bronze(mock_get, config):
    """Only licence-dependent statuses consult the licence."""
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        "bronze", pdf_url="https://publisher.example.org/paper.pdf", license="cc-by"
    )

    assert (
        OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config).access_type
        != "open"
    )


@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_bronze_is_marked_non_open(mock_get, config):
    """Free to read on the publisher's site, under no open licence."""
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        "bronze", pdf_url="https://publisher.example.org/paper.pdf"
    )

    location = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)

    assert location is not None, "bronze is located, then declined downstream"
    assert location.oa_status == "bronze"
    assert location.access_type != "open"


@patch("linkml_reference_validator.etl.fulltext.unpaywall.requests.get")
def test_unpaywall_bronze_is_marked_non_open(mock_get, config):
    from linkml_reference_validator.etl.fulltext.unpaywall import UnpaywallProvider

    mock_get.return_value = _unpaywall_payload(
        "bronze", pdf_url="https://publisher.example.org/paper.pdf"
    )

    location = UnpaywallProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)

    assert location.access_type != "open"


@patch("linkml_reference_validator.etl.fulltext.openalex.requests.get")
def test_an_unrecognised_status_is_not_assumed_open(mock_get, config):
    """A status we do not know about must not default to redistributable."""
    from linkml_reference_validator.etl.fulltext.openalex import OpenAlexProvider

    mock_get.return_value = _openalex_payload(
        "something-new", pdf_url="https://x.example.org/paper.pdf"
    )

    location = OpenAlexProvider().locate(ReferenceIdentifiers(doi="10.1/x"), config)

    assert location.access_type != "open"


# --------------------------------------------------------------------------
# The two rules meet the enrichment chain
# --------------------------------------------------------------------------


def test_bronze_is_skipped_by_ordinary_validation(tmp_path):
    """``_enrich_with_full_text`` already declines non-open locations.

    This pins the join: marking bronze non-open is only useful because that
    gate exists, and it is the same gate Zotero's private material uses.
    """
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.models import (
        FullTextLocation,
        ReferenceContent,
    )

    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))
    content = ReferenceContent(
        reference_id="DOI:10.1/x",
        content="Abstract only.",
        content_type="abstract_only",
        doi="10.1/x",
    )
    bronze = FullTextLocation(
        url="https://publisher.example.org/paper.pdf",
        format_hint="pdf",
        oa_status="bronze",
        access_type="publisher_free",
        provider="openalex",
    )

    with patch.object(fetcher, "_apply_full_text_location") as apply_location:
        with patch(
            "linkml_reference_validator.etl.fulltext.base.FullTextProviderRegistry.get"
        ) as get_provider:
            provider = MagicMock()
            provider.locate.return_value = bronze
            get_provider.return_value = provider
            fetcher._enrich_with_full_text(content)

    apply_location.assert_not_called()
    assert content.content_type == "abstract_only"


# --------------------------------------------------------------------------
# Provenance for a non-open location
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("access_type", "expected_url"),
    [
        ("open", "https://oa.example.org/paper.pdf"),
        ("publisher_free", "https://oa.example.org/paper.pdf"),
        ("user_library", None),
        ("institutional", None),
        # An access type this version has not heard of stays fail-closed, the
        # same way an unknown oa_status and an unknown licence do.
        ("some-future-scheme", None),
    ],
)
def test_a_public_url_is_recorded_even_when_the_licence_is_not_open(
    tmp_path, access_type, expected_url
):
    """Not redistributable is not the same as not citable.

    The rule that drops ``full_text_url`` was written for a private-library
    endpoint -- a localhost Zotero attachment, which is session-specific and
    meaningless to anyone else. A bronze publisher PDF link is neither: it is a
    stable public URL to a free-to-read article, and the reason its *content*
    stays out of the public cache is licensing, not secrecy. Dropping it would
    lose real provenance for no privacy gain.
    """
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.models import FullTextLocation, ReferenceContent

    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path))
    content = ReferenceContent(
        reference_id="DOI:10.1/x", content="Abstract.", content_type="abstract_only"
    )
    location = FullTextLocation(
        url="https://oa.example.org/paper.pdf",
        format_hint="pdf",
        oa_status="bronze",
        access_type=access_type,
        provider="openalex",
    )

    with patch.object(
        fetcher, "_materialize", return_value=("body text " * 200, "pdf", None, False)
    ):
        fetcher._apply_full_text_location(content, "Abstract.", location, "openalex")

    assert content.full_text_url == expected_url


# --------------------------------------------------------------------------
# A decision we made is not a fact about the article
# --------------------------------------------------------------------------


def _fetch_with_location(tmp_path, location):
    """Fetch a DOI whose provider chain yields ``location`` (or nothing)."""
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.models import ReferenceContent

    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(cache_dir=tmp_path, email="me@example.org")
    )
    abstract = ReferenceContent(
        reference_id="DOI:10.1/x",
        content="An abstract.",
        content_type="abstract_only",
        doi="10.1/x",
    )

    provider = MagicMock()
    provider.locate.return_value = location
    with patch(
        "linkml_reference_validator.etl.fulltext.base.FullTextProviderRegistry.get",
        return_value=provider,
    ):
        fetcher._enrich_with_full_text(abstract)
    return abstract


def test_a_bronze_decline_does_not_record_that_no_full_text_exists(tmp_path):
    """This PR's own thesis, one layer up.

    ``full_text_attempted`` means "a prior clean run concluded none is
    available", and ``_maybe_retry_full_text`` uses it to never run the chain
    again. A bronze location was not absent — it was found, and declined on
    licence. Recording that decision as an absence means a bronze article that
    later converts to gold is never noticed.
    """
    from linkml_reference_validator.models import FullTextLocation

    reference = _fetch_with_location(
        tmp_path,
        FullTextLocation(
            url="https://publisher.example.org/paper.pdf",
            format_hint="pdf",
            oa_status="bronze",
            access_type="publisher_free",
            provider="openalex",
        ),
    )

    assert reference.content_type == "abstract_only", "the text is still declined"
    assert not reference.full_text_attempted, (
        "a licence decision must stay retryable, as a transient error does"
    )


def test_a_landing_page_only_record_does_not_record_that_no_full_text_exists(tmp_path):
    """The other new arrival: the provider declined to scrape, so returned nothing.

    A DOI whose only location is an article page is not a DOI with no full text.
    It gains a ``pdf_url`` the day a repository copy is deposited.
    """
    from linkml_reference_validator.models import FullTextLocation

    reference = _fetch_with_location(
        tmp_path,
        FullTextLocation(
            declined="landing_page_only", oa_status="gold", provider="openalex"
        ),
    )

    assert reference.content_type == "abstract_only"
    assert not reference.full_text_attempted


def test_a_genuine_absence_is_still_recorded(tmp_path):
    """The flag must keep meaning something, or the chain re-runs forever.

    A provider that ran cleanly and found nothing at all — no location, no
    decline — is the case the flag was introduced for.
    """
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.models import ReferenceContent

    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(cache_dir=tmp_path, email="me@example.org")
    )
    abstract = ReferenceContent(
        reference_id="DOI:10.1/x", content="An abstract.",
        content_type="abstract_only", doi="10.1/x",
    )

    # A provider that ran and found nothing -- not an unregistered one, which
    # is skipped before it is ever consulted and would pass this test even if a
    # bare ``None`` also counted as a decline.
    provider = MagicMock()
    provider.locate.return_value = None
    with patch(
        "linkml_reference_validator.etl.fulltext.base.FullTextProviderRegistry.get",
        return_value=provider,
    ):
        fetcher._enrich_with_full_text(abstract)

    provider.locate.assert_called()
    assert abstract.full_text_attempted


def test_a_decline_is_remembered_so_the_chain_is_not_rewalked_every_run(tmp_path):
    """Retryable must not mean re-walked on every run, forever.

    A transient error clears itself: the next run succeeds. A policy decline
    never does — bronze stays bronze until the publisher changes it, which may
    be never. Leaving nothing recorded means every run re-enters the chain for
    every such reference: four providers, each opening with a
    ``rate_limit_delay`` sleep, against the same hosts whose rate limiting
    produces the interstitial this change exists to defend against.

    Measured on a real corpus, 23,465 cached entries are eligible; at ~2s of
    sleep apiece that is around thirteen hours per validation run, before the
    HTTP requests. So the decline is recorded against the extractor version:
    retried when that moves, not every run.
    """
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.models import FullTextLocation, ReferenceContent

    declined = FullTextLocation(
        declined="landing_page_only", oa_status="gold", provider="openalex"
    )
    calls = []

    def _run():
        fetcher = ReferenceFetcher(
            ReferenceValidationConfig(cache_dir=tmp_path, email="me@example.org")
        )
        source = MagicMock()
        source.return_value.fetch.return_value = ReferenceContent(
            reference_id="DOI:10.1/x", content="An abstract.",
            content_type="abstract_only", doi="10.1/x",
        )
        provider = MagicMock()
        provider.locate.side_effect = lambda *a, **k: (calls.append(1), declined)[1]
        with patch(
            "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
            return_value=source,
        ), patch(
            "linkml_reference_validator.etl.fulltext.base.FullTextProviderRegistry.get",
            return_value=provider,
        ):
            return fetcher.fetch("DOI:10.1/x")

    _run()
    first = len(calls)
    assert first >= 1, "the first run consults the chain"

    _run()
    assert len(calls) == first, (
        "a second run, in a fresh fetcher, must not re-walk the chain"
    )


def test_a_recorded_decline_still_reads_as_retryable_not_as_an_absence(tmp_path):
    """The distinction round 11 established must survive being remembered.

    Suppressing the re-walk must not be done by setting ``full_text_attempted``,
    whose meaning is "a clean run concluded none is available". The decline is
    recorded as itself.
    """
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.models import FullTextLocation, ReferenceContent

    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(cache_dir=tmp_path, email="me@example.org")
    )
    abstract = ReferenceContent(
        reference_id="DOI:10.1/x", content="An abstract.",
        content_type="abstract_only", doi="10.1/x",
    )
    provider = MagicMock()
    provider.locate.return_value = FullTextLocation(
        declined="landing_page_only", oa_status="gold", provider="openalex"
    )
    with patch(
        "linkml_reference_validator.etl.fulltext.base.FullTextProviderRegistry.get",
        return_value=provider,
    ):
        fetcher._enrich_with_full_text(abstract)

    assert not abstract.full_text_attempted, "still not an absence"
    assert abstract.full_text_declined == "landing_page_only", "but it is remembered"


@pytest.mark.parametrize("failure", ["rate_limit", "elink_outage"])
def test_a_transient_pmc_failure_is_not_recorded_as_an_absence(tmp_path, failure):
    """The defect this release is about, in the host that motivated it.

    PMC answers a rate-limited client with 429, and an Entrez ``elink`` outage
    raises. Both used to return ``None`` from ``locate``, which the chain reads
    as a clean absence and records as ``full_text_attempted`` -- so an article
    that *does* have a PMC body, fetched during a rate-limit window, is
    permanently marked as having none.
    """
    from contextlib import ExitStack

    from linkml_reference_validator.etl.fulltext.pmc import PMCFullTextProvider
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.models import ReferenceContent

    fetcher = ReferenceFetcher(
        ReferenceValidationConfig(
            cache_dir=tmp_path, email="me@example.org", rate_limit_delay=0
        )
    )
    content = ReferenceContent(
        reference_id="PMID:1", content="An abstract.", content_type="abstract_only"
    )

    rate_limited = MagicMock()
    rate_limited.status_code = 429

    with ExitStack() as stack:
        stack.enter_context(
            patch(
                "linkml_reference_validator.etl.fulltext.base."
                "FullTextProviderRegistry.get",
                return_value=PMCFullTextProvider(),
            )
        )
        stack.enter_context(
            patch.object(PMCFullTextProvider, "_fetch_pmc_xml_source", return_value=None)
        )
        if failure == "rate_limit":
            stack.enter_context(
                patch.object(PMCFullTextProvider, "_resolve_pmcid", return_value="123456")
            )
            stack.enter_context(
                patch(
                    "linkml_reference_validator.etl.fulltext.pmc.requests.get",
                    return_value=rate_limited,
                )
            )
        else:
            stack.enter_context(
                patch.object(
                    PMCFullTextProvider,
                    "_resolve_pmcid",
                    side_effect=RuntimeError("elink down"),
                )
            )
        fetcher._enrich_with_full_text(content)

    assert not content.full_text_attempted, f"{failure} is not an absence"


def test_cache_enrich_does_not_count_a_declined_location_as_found(tmp_path):
    """``cache enrich``'s entire output is an inventory, so a refusal is not a find.

    A declined location carries no ``url`` and no ``text``; counting it inflates
    ``Found:`` by exactly the references the provider refused, and under
    ``--apply`` it reports ``unusable`` rather than crashing, which reads as a
    provider fault rather than a decision.
    """
    from typer.testing import CliRunner

    from linkml_reference_validator.cli import app
    from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
    from linkml_reference_validator.models import FullTextLocation, ReferenceContent

    cache_dir = tmp_path / "cache"
    fetcher = ReferenceFetcher(ReferenceValidationConfig(cache_dir=cache_dir))
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id="DOI:10.1/x", content="An abstract.",
            content_type="abstract_only", doi="10.1/x", title="A paper",
        )
    )

    declined = FullTextLocation(
        declined="landing_page_only", oa_status="gold", provider="openalex"
    )
    with patch.object(ReferenceFetcher, "locate_full_text", return_value=declined):
        result = CliRunner().invoke(
            app,
            ["cache", "enrich", "--provider", "openalex", "--dry-run",
             "--cache-dir", str(cache_dir)],
        )

    assert "\tfound\t" not in result.output, result.output
    assert "declined" in result.output, result.output
