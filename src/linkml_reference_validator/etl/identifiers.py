"""Build cross-walked identifiers for a reference.

Most identifier data is already present on the fetched ReferenceContent (the DOI is
returned by PubMed esummary and set by the DOI source). PMC ID resolution is done
lazily inside the PMC provider, so it is not performed here.
"""

import logging
import re
from typing import Optional

from linkml_reference_validator.models import ReferenceContent, ReferenceIdentifiers

logger = logging.getLogger(__name__)


def _split_reference_id(reference_id: str) -> tuple[Optional[str], Optional[str]]:
    """Split a reference id into (prefix, identifier).

    Examples:
        >>> _split_reference_id("PMID:123")
        ('PMID', '123')
        >>> _split_reference_id("url:https://x/y")
        ('url', 'https://x/y')
        >>> _split_reference_id("nope")
        (None, None)
    """
    match = re.match(r"^([A-Za-z_]+):(.+)$", reference_id.strip())
    if match:
        return match.group(1), match.group(2)
    return None, None


def build_identifiers(content: ReferenceContent) -> ReferenceIdentifiers:
    """Build ReferenceIdentifiers from a fetched ReferenceContent.

    Examples:
        >>> from linkml_reference_validator.models import ReferenceContent
        >>> ids = build_identifiers(ReferenceContent(reference_id="PMID:9", doi="10.1/z"))
        >>> ids.pmid, ids.doi
        ('9', '10.1/z')
        >>> build_identifiers(ReferenceContent(reference_id="PPR:PPR42")).pprid
        'PPR42'
    """
    prefix, identifier = _split_reference_id(content.reference_id)

    ids = ReferenceIdentifiers(doi=content.doi or None)

    if prefix and identifier:
        upper = prefix.upper()
        if upper == "PMID":
            ids.pmid = identifier
        elif upper == "PMCID":
            ids.pmcid = identifier
        elif upper == "PPR":
            ids.pprid = identifier
        elif upper == "DOI" and not ids.doi:
            ids.doi = identifier
        elif prefix.lower() == "url":
            ids.url = identifier

    return ids
