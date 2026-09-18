"""OpenAlex full-text provider.

Looks up an openly-licensed full-text *file* for a DOI via the OpenAlex works
API. A record whose only location is a landing page yields nothing: see
:func:`~linkml_reference_validator.etl.fulltext.base.access_type_for_oa_status`
and ``locate`` below.
"""

import logging
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
    access_type_for_oa_status,
)

logger = logging.getLogger(__name__)


@FullTextProviderRegistry.register
class OpenAlexProvider(FullTextProvider):
    """Locate an open-access PDF for a DOI via OpenAlex.

    Returns a location only for a ``pdf_url``. The ``oa_url`` fallback was
    removed: it is an article *page*, and downloading one is scraping.

    That constrains what is *asked for*, not what comes back -- a ``pdf_url``
    answering with HTML is sniffed by ``_materialize`` and routed to the HTML
    extractor. What makes that safe is the same structural defence
    ``PMCFullTextProvider._fetch_pmc_html`` relies on: ``HTMLExtractor``'s
    landing-page rejection, plus the ``html_full_text_version`` stamp that marks
    which entries it certified.

    Examples:
        >>> OpenAlexProvider.name()
        'openalex'
    """

    @classmethod
    def name(cls) -> str:
        return "openalex"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        if not ids.doi:
            return None

        time.sleep(config.rate_limit_delay)
        url = f"https://api.openalex.org/works/doi:{ids.doi}"
        response = requests.get(url, params={"mailto": config.email}, timeout=30)
        if response.status_code != 200:
            logger.debug(f"OpenAlex returned {response.status_code} for DOI:{ids.doi}")
            return None

        data = response.json()
        open_access = data.get("open_access") or {}
        if not open_access.get("is_oa"):
            return None

        best = data.get("best_oa_location") or {}
        pdf_url = best.get("pdf_url")
        if not pdf_url:
            # ``oa_url`` without ``pdf_url`` is a landing/article *page*, not a
            # file. Retrieving it means scraping HTML the host did not offer for
            # machine retrieval, and hosts defend against exactly that: PMC
            # answers with a reCAPTCHA interstitial carried on an HTTP 200, so
            # no status code downstream can tell it from article text. Decline
            # instead, and let the record stay abstract-only.
            logger.debug(
                "OpenAlex has only a landing page for DOI:%s; not scraping it",
                ids.doi,
            )
            # Declined, not absent. Returning a bare ``None`` here would let the
            # chain record that this article has no full text, and it has one --
            # it is the route that is unacceptable, and a repository deposit can
            # give it an acceptable one tomorrow.
            return FullTextLocation(
                declined="landing_page_only",
                oa_status=open_access.get("oa_status"),
                provider="openalex",
            )

        # Different objects on purpose, and the mismatch access_type_for_oa_status
        # calls a known miss: the status is the work's best across all locations,
        # the licence belongs to this one.
        oa_status = open_access.get("oa_status")
        licence = best.get("license")
        return FullTextLocation(
            url=pdf_url,
            format_hint="pdf",
            oa_status=oa_status,
            access_type=access_type_for_oa_status(oa_status, licence),
            license=licence,
            version=best.get("version"),
            provider="openalex",
        )
