"""Unpaywall full-text provider.

Looks up the best open-access location for a DOI via the Unpaywall v2 API.
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
class UnpaywallProvider(FullTextProvider):
    """Locate an open-access PDF for a DOI via Unpaywall.

    Returns a location only for a ``url_for_pdf``; a landing ``url`` is a page,
    not a file, and downloading one is scraping.

    Examples:
        >>> UnpaywallProvider.name()
        'unpaywall'
    """

    @classmethod
    def name(cls) -> str:
        return "unpaywall"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        if not ids.doi:
            return None

        time.sleep(config.rate_limit_delay)
        url = f"https://api.unpaywall.org/v2/{ids.doi}"
        response = requests.get(url, params={"email": config.email}, timeout=30)
        if response.status_code != 200:
            logger.debug(f"Unpaywall returned {response.status_code} for DOI:{ids.doi}")
            return None

        data = response.json()
        best = data.get("best_oa_location")
        if not data.get("is_oa") or not best:
            return None

        pdf_url = best.get("url_for_pdf")
        if not pdf_url:
            # See OpenAlexProvider: a landing URL is a page, not a file, and
            # fetching it is scraping.
            logger.debug(
                "Unpaywall has only a landing page for DOI:%s; not scraping it",
                ids.doi,
            )
            # See OpenAlexProvider: declined, not absent.
            return FullTextLocation(
                declined="landing_page_only",
                oa_status=data.get("oa_status"),
                provider="unpaywall",
            )

        oa_status = data.get("oa_status")
        licence = best.get("license")
        return FullTextLocation(
            url=pdf_url,
            format_hint="pdf",
            oa_status=oa_status,
            access_type=access_type_for_oa_status(oa_status, licence),
            license=licence,
            version=best.get("version"),
            provider="unpaywall",
        )
