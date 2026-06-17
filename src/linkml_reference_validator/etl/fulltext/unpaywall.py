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
)

logger = logging.getLogger(__name__)


@FullTextProviderRegistry.register
class UnpaywallProvider(FullTextProvider):
    """Locate an open-access PDF/landing page for a DOI via Unpaywall.

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
        landing = best.get("url")
        target = pdf_url or landing
        if not target:
            return None

        return FullTextLocation(
            url=target,
            format_hint="pdf" if pdf_url else "html",
            oa_status=data.get("oa_status"),
            license=best.get("license"),
            version=best.get("version"),
            provider="unpaywall",
        )
