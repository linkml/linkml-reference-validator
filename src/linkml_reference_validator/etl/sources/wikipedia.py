"""Wikipedia reference source.

Reads an English Wikipedia article as plain text through the MediaWiki Action
API's ``extracts`` module, so a quote that runs through a link or bold text in
the rendered page still matches. The article title is the identifier, as it
appears in the article's URL: ``WIKIPEDIA:Saanen_goat``.

Wikipedia text is licensed CC BY-SA 4.0 and changes over time. The cached entry
records the revision that was read, so a committed cache shows what was quoted.

Examples:
    >>> from linkml_reference_validator.etl.sources.wikipedia import WikipediaSource
    >>> WikipediaSource.prefix()
    'WIKIPEDIA'
    >>> WikipediaSource.can_handle("WIKIPEDIA:Saanen_goat")
    True
    >>> WikipediaSource.can_handle("url:https://en.wikipedia.org/wiki/Saanen_goat")
    False
"""

import logging
import re
import time
from typing import Any, Optional
from urllib.parse import unquote, urlencode

from linkml_reference_validator.etl.sources.base import ReferenceSource, ReferenceSourceRegistry
from linkml_reference_validator.etl.sources.utils import get_json
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig

logger = logging.getLogger(__name__)

#: The English Wikipedia's MediaWiki Action API endpoint.
WIKIPEDIA_API_URL = "https://en.wikipedia.org/w/api.php"

#: The licence of Wikipedia's text.
WIKIPEDIA_LICENSE = "CC BY-SA 4.0"

#: A section heading in an ``explaintext`` extract: ``== History ==``.
_HEADING = re.compile(r"^(={2,6})\s*(.*?)\s*\1\s*$", re.MULTILINE)


def canonical_title(title: str) -> str:
    """Return the one spelling of an article title that a cache key is built from.

    MediaWiki treats a title's spaces and underscores alike, collapses runs of
    them, decodes percent-encoding and upper-cases the first letter, so
    ``saanen goat`` and ``Saanen%20goat`` are both the article ``Saanen_goat``.
    This spells every one of them as the article's URL does. A ``#Section``
    anchor is dropped: the citation is to the article.

    Args:
        title: An article title as cited.

    Returns:
        The title as it appears in the article's URL.

    Examples:
        >>> canonical_title("saanen goat")
        'Saanen_goat'
        >>> canonical_title("Saanen%20goat")
        'Saanen_goat'
        >>> canonical_title("Star Trek: Voyager")
        'Star_Trek:_Voyager'
        >>> canonical_title("Café")
        'Café'
        >>> canonical_title("Saanen_goat#History")
        'Saanen_goat'
    """
    # A URL's #Section anchor names part of the article; "#" is never in a title.
    words = unquote(title).partition("#")[0].replace("_", " ").split()
    joined = "_".join(words)
    first = joined[:1].upper()
    # A letter whose upper case is two letters (such as "ß") is left as written.
    return (first if len(first) == 1 else joined[:1]) + joined[1:]


def plain_headings(text: str) -> str:
    """Turn ``== Heading ==`` lines in a plain-text extract into bare heading lines.

    Args:
        text: An extract from the MediaWiki API with ``explaintext`` set.

    Returns:
        The text with each heading's ``=`` markers removed.

    Examples:
        >>> plain_headings("Intro.\\n\\n== History ==\\nOld.\\n=== Early days ===\\nOlder.")
        'Intro.\\n\\nHistory\\nOld.\\nEarly days\\nOlder.'
        >>> plain_headings("a = b, and x == y in the text")
        'a = b, and x == y in the text'
    """
    return _HEADING.sub(r"\2", text)


def api_query_url(title: str) -> str:
    """Build the MediaWiki API URL that returns ``title`` as plain text with its revision.

    Args:
        title: The article title, with spaces or underscores.

    Returns:
        The request URL.

    Examples:
        >>> url = api_query_url("Saanen_goat")
        >>> url.startswith(WIKIPEDIA_API_URL + "?action=query&")
        True
        >>> "titles=Saanen_goat" in url and "explaintext=1" in url and "redirects=1" in url
        True
    """
    params = {
        "action": "query",
        "format": "json",
        "formatversion": "2",
        "prop": "extracts|revisions|info",
        "explaintext": "1",
        "rvprop": "ids|timestamp",
        "inprop": "url",
        "redirects": "1",
        "titles": title,
    }
    return f"{WIKIPEDIA_API_URL}?{urlencode(params)}"


@ReferenceSourceRegistry.register
class WikipediaSource(ReferenceSource):
    """Fetch an English Wikipedia article's plain text from the MediaWiki API.

    Examples:
        >>> WikipediaSource.prefix()
        'WIKIPEDIA'
        >>> WikipediaSource.can_handle("wikipedia:Saanen goat")
        True
        >>> WikipediaSource.can_handle("WIKIDATA:Q42")
        False
    """

    @classmethod
    def prefix(cls) -> str:
        """Return the prefix this source handles.

        Examples:
            >>> WikipediaSource.prefix()
            'WIKIPEDIA'
        """
        return "WIKIPEDIA"

    def fetch(
        self, identifier: str, config: ReferenceValidationConfig
    ) -> Optional[ReferenceContent]:
        """Fetch the article titled ``identifier``.

        The title may use underscores or spaces, and may be percent-encoded as
        copied from a URL. A redirect is followed. A missing or invalid page, or
        a failed request (Wikimedia throttles with HTTP 429), gives None, so the
        fetcher can fall back to a cached copy.

        Args:
            identifier: The article title (e.g. ``Saanen_goat``).
            config: Configuration, for the rate-limit delay and contact email.

        Returns:
            ReferenceContent with the article's plain text, or None.
        """
        time.sleep(config.rate_limit_delay)
        title = canonical_title(identifier)
        headers = {
            "Accept": "application/json",
            # Wikimedia's User-Agent policy asks for a way to reach the operator.
            "User-Agent": (
                "linkml-reference-validator/1.0 "
                f"(https://github.com/linkml/linkml-reference-validator; mailto:{config.email})"
            ),
        }
        data = get_json(api_query_url(title), f"{self.prefix()}:{title}", headers)
        if not isinstance(data, dict):
            return None
        return self._parse_response(title, data)

    def _parse_response(self, identifier: str, data: dict[str, Any]) -> Optional[ReferenceContent]:
        """Turn a ``formatversion=2`` query response into ReferenceContent.

        Args:
            identifier: The canonical article title, used in the reference ID.
            data: The decoded API response.

        Returns:
            ReferenceContent, or None when the page is missing or invalid.

        Examples:
            >>> page = {"title": "Goat", "extract": "Goats.\\n\\n== Uses ==\\nMilk.",
            ...         "revisions": [{"revid": 9, "timestamp": "2026-01-01T00:00:00Z"}],
            ...         "canonicalurl": "https://en.wikipedia.org/wiki/Goat"}
            >>> ref = WikipediaSource()._parse_response("Goat", {"query": {"pages": [page]}})
            >>> ref.reference_id, ref.title, ref.content_type, ref.content
            ('WIKIPEDIA:Goat', 'Goat', 'full_text', 'Goats.\\n\\nUses\\nMilk.')
            >>> ref.source_revision, ref.source_url, ref.license
            ('9', 'https://en.wikipedia.org/wiki/Goat', 'CC BY-SA 4.0')
            >>> missing = {"query": {"pages": [{"title": "Nope", "missing": True}]}}
            >>> WikipediaSource()._parse_response("Nope", missing) is None
            True
        """
        query = data.get("query") or {}
        pages = query.get("pages") or []
        if not pages:
            logger.warning(f"Wikipedia returned no page for {identifier}")
            return None
        page = pages[0]
        if page.get("missing") or page.get("invalid"):
            reason = page.get("invalidreason") or "no such article"
            logger.warning(f"Wikipedia has no article {identifier!r}: {reason}")
            return None

        extract = page.get("extract")
        content = plain_headings(extract).strip() if extract else None

        # A page with no revisions listed still has its text; record no revision.
        revisions = page.get("revisions") or [{}]
        revision_id = revisions[0].get("revid")

        return ReferenceContent(
            reference_id=f"{self.prefix()}:{identifier}",
            title=page.get("title"),
            content=content,
            content_type="full_text" if content else "unavailable",
            license=WIKIPEDIA_LICENSE,
            source_url=page.get("canonicalurl") or page.get("fullurl"),
            source_revision=str(revision_id) if revision_id is not None else None,
            source_revision_timestamp=revisions[0].get("timestamp"),
        )
