"""OpenAlex full-text provider.

Looks up open-access locations for a DOI via the OpenAlex works API.
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
class OpenAlexProvider(FullTextProvider):
    """Locate an open-access PDF/landing page for a DOI via OpenAlex.

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
        oa_url = open_access.get("oa_url")
        target = pdf_url or oa_url
        if not target:
            return None

        return FullTextLocation(
            url=target,
            format_hint="pdf" if pdf_url else "html",
            oa_status=open_access.get("oa_status"),
            license=best.get("license"),
            version=best.get("version"),
            provider="openalex",
        )
