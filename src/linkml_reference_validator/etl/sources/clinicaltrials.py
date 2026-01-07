"""ClinicalTrials.gov reference source.

Provides access to clinical trial data via the ClinicalTrials.gov API.

Examples:
    >>> from linkml_reference_validator.etl.sources.clinicaltrials import ClinicalTrialsSource
    >>> ClinicalTrialsSource.prefix()
    'NCT'
    >>> ClinicalTrialsSource.can_handle("NCT:NCT00000001")
    True
    >>> ClinicalTrialsSource.can_handle("NCT00000001")
    True
"""

import logging
import re
import time
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry

logger = logging.getLogger(__name__)

# ClinicalTrials.gov API v2 endpoint
CLINICALTRIALS_API_URL = "https://clinicaltrials.gov/api/v2/studies/{nct_id}"


@ReferenceSourceRegistry.register
class ClinicalTrialsSource(ReferenceSource):
    """Fetch clinical trial data from ClinicalTrials.gov.

    Supports NCT identifiers (e.g., NCT00000001) with or without prefix.

    Examples:
        >>> ClinicalTrialsSource.prefix()
        'NCT'
        >>> ClinicalTrialsSource.can_handle("NCT:NCT00000001")
        True
        >>> ClinicalTrialsSource.can_handle("NCT00000001")
        True
        >>> ClinicalTrialsSource.can_handle("PMID:12345")
        False
    """

    @classmethod
    def prefix(cls) -> str:
        """Return the prefix this source handles.

        Examples:
            >>> ClinicalTrialsSource.prefix()
            'NCT'
        """
        return "NCT"

    @classmethod
    def can_handle(cls, reference_id: str) -> bool:
        """Check if this source can handle the given reference ID.

        Supports both prefixed (NCT:NCT00000001) and bare (NCT00000001) identifiers.

        Examples:
            >>> ClinicalTrialsSource.can_handle("NCT:NCT00000001")
            True
            >>> ClinicalTrialsSource.can_handle("nct:NCT12345678")
            True
            >>> ClinicalTrialsSource.can_handle("NCT00000001")
            True
            >>> ClinicalTrialsSource.can_handle("PMID:12345")
            False
        """
        # Check for prefix (NCT:...)
        if super().can_handle(reference_id):
            return True
        # Check for bare NCT ID (NCT followed by 8 digits)
        return bool(re.match(r"^NCT\d{8}$", reference_id, re.IGNORECASE))

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch clinical trial data from ClinicalTrials.gov API.

        Args:
            identifier: NCT identifier (e.g., NCT00000001)
            config: Configuration including rate limiting

        Returns:
            ReferenceContent if successful, None otherwise

        Examples:
            >>> source = ClinicalTrialsSource()
            >>> # This would require network access in real usage
            >>> source.prefix()
            'NCT'
        """
        time.sleep(config.rate_limit_delay)

        # Normalize identifier - ensure it starts with NCT
        nct_id = identifier.upper()
        if not nct_id.startswith("NCT"):
            nct_id = f"NCT{nct_id}"

        url = CLINICALTRIALS_API_URL.format(nct_id=nct_id)

        try:
            response = requests.get(url, timeout=30)
        except requests.RequestException as exc:
            logger.warning(f"Failed to fetch clinical trial {nct_id}: {exc}")
            return None

        if response.status_code != 200:
            logger.warning(
                f"ClinicalTrials.gov API returned status {response.status_code} for {nct_id}"
            )
            return None

        try:
            data = response.json()
        except ValueError as exc:
            logger.warning(f"Failed to parse JSON response for {nct_id}: {exc}")
            return None

        return self._parse_response(nct_id, data)

    def _parse_response(self, nct_id: str, data: dict) -> Optional[ReferenceContent]:
        """Parse the ClinicalTrials.gov API response into ReferenceContent.

        Args:
            nct_id: The NCT identifier
            data: The JSON response from the API

        Returns:
            ReferenceContent with trial information
        """
        protocol_section = data.get("protocolSection", {})
        identification = protocol_section.get("identificationModule", {})
        description = protocol_section.get("descriptionModule", {})
        status_module = protocol_section.get("statusModule", {})
        sponsor_module = protocol_section.get("sponsorCollaboratorsModule", {})

        # Extract title (prefer officialTitle, fall back to briefTitle)
        title = identification.get("officialTitle") or identification.get("briefTitle")

        # Extract content (prefer briefSummary, fall back to detailedDescription)
        content = description.get("briefSummary") or description.get("detailedDescription")

        # Build metadata
        metadata: dict = {}

        status = status_module.get("overallStatus")
        if status:
            metadata["status"] = status

        lead_sponsor = sponsor_module.get("leadSponsor", {})
        sponsor_name = lead_sponsor.get("name")
        if sponsor_name:
            metadata["sponsor"] = sponsor_name

        content_type = "summary" if content else "unavailable"

        return ReferenceContent(
            reference_id=f"NCT:{nct_id}",
            title=title,
            content=content,
            content_type=content_type,
            metadata=metadata,
        )
