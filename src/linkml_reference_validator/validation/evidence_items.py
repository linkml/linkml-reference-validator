"""Find (excerpt, reference) pairs in loaded data without a schema.

Used by ``repair data`` and ``excerpts sign``. This is a simplified extraction
that looks for common patterns; schema-aware extraction is the LinkML plugin's.
"""

import logging
from pathlib import Path
from typing import Optional

from linkml_reference_validator.plugins.reference_validation_plugin import (
    extract_reference_id,
)

logger = logging.getLogger(__name__)


def _excerpt_keys(d: dict) -> list[str]:
    """Return every key holding an excerpt on this evidence item.

    All of them, not the best of them. The LinkML plugin iterates each excerpt
    field and checks it, so picking one key here left the second quote on an
    item silently unvalidated and unrepaired. A blank excerpt alongside a real
    one is still a defect and is still reported.

    Used by both extraction and write-back, and the excerpt key is carried in
    the reported path, so a repair cannot land in a different field than the
    quote came from.

    An item that stores the same quote under both keys is therefore checked and
    reported once per key. That is the honest reading - both fields are being
    validated - and it costs no extra fetching, since the reference is served
    from the in-process cache the second time.

    Args:
        d: A candidate evidence item

    Returns:
        The excerpt keys present as strings, in a stable order

    Examples:
        >>> _excerpt_keys({"supporting_text": "a quote"})
        ['supporting_text']
        >>> _excerpt_keys({"supporting_text": "", "snippet": "a quote"})
        ['supporting_text', 'snippet']
        >>> _excerpt_keys({"reference": "PMID:1"})
        []
    """
    return [
        key for key in ("supporting_text", "snippet") if isinstance(d.get(key), str)
    ]


def _extract_evidence_items(
    data: dict | list,
    target_class: Optional[str],
    schema_file: Optional[Path] = None,
) -> list[tuple[str, str, Optional[str]]]:
    """Extract evidence items from data for repair.

    This is a simplified extraction that looks for common patterns.
    For full schema-aware extraction, use the LinkML plugin.

    Args:
        data: Loaded YAML data
        target_class: Target class to look for
        schema_file: Schema file (for future use)

    Returns:
        List of (supporting_text, reference_id, path) tuples
    """
    items: list[tuple[str, str, Optional[str]]] = []

    def _extract_from_dict(d: dict, path: str = ""):
        # Look for evidence patterns
        if isinstance(d, dict):
            # Direct evidence item pattern. The reference may be an inlined
            # object, whose id is read with the validation plugin's own
            # extract_reference_id (#138). Unlike validation, a repair needs
            # exactly one source, so a list of references is skipped below, and
            # each key is tried in turn, so a reference object with no id does
            # not hide a usable reference_id beside it.
            ref_value = d.get("reference") or d.get("reference_id")
            ref = extract_reference_id(d.get("reference")) or extract_reference_id(
                d.get("reference_id")
            )
            if ref is None and ref_value and _excerpt_keys(d):
                # A list of references, or an object with no text id: a
                # repair needs the one reference the quote came from.
                logger.warning(
                    "Skipping evidence item at %s: its reference names no single "
                    "identifier, so its excerpt cannot be repaired",
                    path or "the top level",
                )
            if ref is not None:
                for text_key in _excerpt_keys(d):
                    key_path = f"{path}.{text_key}" if path else text_key
                    items.append((d[text_key], ref, key_path))

            # Look for evidence list
            for key in ["evidence", "supporting_evidence", "annotations"]:
                if key in d and isinstance(d[key], list):
                    for i, item in enumerate(d[key]):
                        if isinstance(item, dict):
                            _extract_from_dict(item, f"{path}.{key}[{i}]" if path else f"{key}[{i}]")

            # Recurse into other dict values
            for key, value in d.items():
                if key not in ["evidence", "supporting_evidence", "annotations"]:
                    if isinstance(value, dict):
                        _extract_from_dict(value, f"{path}.{key}" if path else key)
                    elif isinstance(value, list):
                        for i, item in enumerate(value):
                            if isinstance(item, dict):
                                _extract_from_dict(item, f"{path}.{key}[{i}]" if path else f"{key}[{i}]")

    if isinstance(data, list):
        for i, item in enumerate(data):
            if isinstance(item, dict):
                _extract_from_dict(item, f"[{i}]")
    elif isinstance(data, dict):
        _extract_from_dict(data)

    return items
