"""Parser settings for untrusted XML, shared by every XML-based extractor.

Internal entities are expanded, as a browser expands them: leaving ``&not;``
out of a label would change what it says. An external entity (XXE) is never
loaded, nor is a DTD or anything on the network, and libxml2's amplification
limit rejects an exponential internal entity (billion laughs). Keeping these
settings in one place means a change to them reaches every extractor.
"""

from typing import Optional, Union

from lxml import etree  # type: ignore[import-untyped]


def encode_for_parser(data: Union[bytes, str]) -> tuple[bytes, Optional[str]]:
    """Return bytes for lxml and the encoding to force, if any.

    Bytes pass through so lxml honours their BOM or declaration. Decoded text
    is re-encoded as UTF-8 and that encoding is forced, because its
    declaration no longer describes it.

    Examples:
        >>> encode_for_parser(b"<a/>")
        (b'<a/>', None)
        >>> encode_for_parser('<?xml version="1.0" encoding="ISO-8859-1"?><a>é</a>')[1]
        'utf-8'
    """
    if isinstance(data, str):
        return data.encode("utf-8"), "utf-8"
    return data, None


def untrusted_xml_parser(
    *, encoding: Optional[str] = None, recover: bool = False
) -> etree.XMLParser:
    """An lxml parser that never reads external entities, DTDs or the network.

    Args:
        encoding: Encoding to force, from :func:`encode_for_parser`.
        recover: Keep what parses from malformed input instead of raising.
            Article XML from providers is often slightly malformed; SVG and
            drawio fail closed instead.

    Examples:
        >>> parser = untrusted_xml_parser()
        >>> etree.fromstring(b'<!DOCTYPE a [<!ENTITY e "ok">]><a>&e;</a>', parser).text
        'ok'
    """
    return etree.XMLParser(
        encoding=encoding,
        resolve_entities="internal",
        no_network=True,
        load_dtd=False,
        huge_tree=False,
        remove_comments=True,
        recover=recover,
    )
