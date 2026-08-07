"""Convert public reference-cache metadata to Zotero-importable CSL JSON."""

import re
from typing import Optional

from linkml_reference_validator.models import ReferenceContent


def normalize_doi(value: Optional[str]) -> Optional[str]:
    """Return a lowercase bare DOI suitable for identity matching.

    Examples:
        >>> normalize_doi("https://doi.org/10.1000/Example")
        '10.1000/example'
        >>> normalize_doi(None) is None
        True
    """
    if not value:
        return None
    normalized = value.strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break
    return normalized or None


def reference_pmid(reference: ReferenceContent) -> Optional[str]:
    """Return a numeric PMID when the reference ID is a PubMed identifier.

    Examples:
        >>> reference_pmid(ReferenceContent(reference_id="PMID:12345"))
        '12345'
        >>> reference_pmid(ReferenceContent(reference_id="NCIT:C123")) is None
        True
    """
    prefix, separator, identifier = reference.reference_id.partition(":")
    if separator and prefix.upper() == "PMID" and identifier.isdigit():
        return identifier
    return None


def export_identity(reference: ReferenceContent) -> Optional[str]:
    """Return the DOI-first identity used to deduplicate exported records."""
    doi = normalize_doi(reference.doi)
    if doi:
        return f"doi:{doi}"
    pmid = reference_pmid(reference)
    if pmid:
        return f"pmid:{pmid}"
    return None


def reference_to_csl_json(reference: ReferenceContent) -> Optional[dict[str, object]]:
    """Map one publication to an allowlisted CSL JSON metadata record.

    Cached content, provenance, local paths, and attachments are deliberately
    unavailable to this function and therefore cannot enter its output.

    Examples:
        >>> reference_to_csl_json(ReferenceContent(
        ...     reference_id="PMID:123", title="A paper", year="2024"
        ... ))
        {'id': 'PMID:123', 'type': 'article-journal', 'title': 'A paper', 'issued': {'date-parts': [[2024]]}, 'PMID': '123', 'URL': 'https://pubmed.ncbi.nlm.nih.gov/123/'}
    """
    doi = normalize_doi(reference.doi)
    pmid = reference_pmid(reference)
    if doi is None and pmid is None:
        return None

    record: dict[str, object] = {
        "id": reference.reference_id,
        "type": "article-journal",
    }
    if reference.title:
        record["title"] = reference.title
    if reference.authors:
        record["author"] = [{"literal": author} for author in reference.authors]
    if reference.journal:
        record["container-title"] = reference.journal
    if reference.year:
        match = re.match(r"\s*(\d{4})", reference.year)
        if match:
            record["issued"] = {"date-parts": [[int(match.group(1))]]}
    if doi:
        record["DOI"] = doi
    elif pmid:
        record["PMID"] = pmid
        record["URL"] = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    return record
