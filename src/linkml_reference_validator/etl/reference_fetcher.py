"""Fetching and caching of references from various sources.

This module provides the main ReferenceFetcher class that coordinates
fetching from various sources (PMID, DOI, file, URL) using a plugin architecture.
"""

import json
import logging
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from ruamel.yaml import YAML  # type: ignore

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceContent,
    ReferenceValidationConfig,
    SupplementaryFile,
)
from linkml_reference_validator.etl.sources import ReferenceSourceRegistry
from linkml_reference_validator.etl.sources.clinicaltrials import NCT_ID_PATTERN
from linkml_reference_validator.etl.acquire import ContentAcquirer, resolve_format, sniff_format
from linkml_reference_validator.etl.identifiers import build_identifiers
from linkml_reference_validator.etl.fulltext.base import PUBLISHER_FREE_ACCESS
from linkml_reference_validator.etl.extract import Extractor, ExtractorRegistry  # noqa: F401  (registers extractors)
from linkml_reference_validator.etl.extract.pdf import PDFExtractor
from linkml_reference_validator.etl.extract.html import HTMLExtractor
import linkml_reference_validator.etl.fulltext  # noqa: F401  (registers providers)
from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
from linkml_reference_validator.etl.fulltext.loader import register_custom_full_text_providers

logger = logging.getLogger(__name__)


#: A refresh keeping full text but returning less than this share of the cached
#: length is reported, never refused. The distinction is the whole lesson of this
#: guard's history: refusing on size blocked four kinds of genuine improvement
#: permanently, because an entry that is never written is never stamped. A log
#: line has none of those properties -- the write proceeds, the migration
#: completes, ``cache reference`` still exits 0 -- and a wrong guess costs one
#: line rather than a cache that can never migrate.
REPORT_SHRINK_RATIO = 0.2

#: ``access_type`` values whose source URL may be recorded, as an allowlist so
#: an unrecognised value stays suppressed. A private endpoint -- one reached
#: through someone's own credentials or installation -- is excluded because its
#: address is meaningless elsewhere and may carry a local token; everything
#: unknown is excluded for the reason this module excludes an unknown
#: ``oa_status`` and an unknown licence, which is that it cannot vouch for it.
#:
#: Not the same question as whether the *text* may be redistributed:
#: ``PUBLISHER_FREE_ACCESS`` is listed here precisely because a publisher's link
#: is a stable public address even when its content is not openly licensed. See
#: the note at the ``full_text_url`` assignment.
PUBLIC_URL_ACCESS_TYPES = frozenset({None, "open", PUBLISHER_FREE_ACCESS})


NEEDS_FULL_TEXT_TYPES = {
    "abstract_only",
    "unavailable",
    "no_pmc",
    "pmc_restricted",
    "summary",
}

# Global floor for "did we actually get full text, or just a few stray characters?"
# Individual providers may set a stricter floor (e.g. PMC uses 2x this in pmc.py,
# since a PMC XML/HTML hit under ~1k chars is almost always a stub, not the body).
MIN_FULL_TEXT_CHARS = 500

#: Bumped whenever an extraction change means previously cached text is wrong
#: rather than merely older. Entries stamped below this are re-fetched on the
#: next validation that needs them, one reference at a time.
#:
#: Version 1: the stub-detection and markup-welding fixes. Before them, an
#: article whose methods said "restricted" was discarded and an 8.7 KB
#: placeholder cached as its full text, and inline markup was welded to its
#: neighbours - "(GUSB, GRN, and NEU1)" stored as "(GUSB,GRN, andNEU1)".
#: Correcting the extractors does not rewrite what they already wrote, so
#: without this stamp every existing cache keeps failing correct snippets with
#: nothing in the output to explain why.
EXTRACTOR_CACHE_VERSION = 1

#: Independently version HTML full-text acceptance: prior entries may contain
#: repository metadata rather than an article. PDF/XML caches need no refresh.
#: Downloaded/raw HTML is structurally checked; pre-extracted text supplied by
#: PMC or a configured text provider is trusted under FullTextLocation's contract.
HTML_FULL_TEXT_CACHE_VERSION = 1

#: XML table extraction changes only XML caches, independent of HTML acceptance.
XML_EXTRACTION_CACHE_VERSION = 1

#: Version the claim "this reference has no content at all", scoped to
#: ``content_type: unavailable``. Such an entry records what an extractor could
#: not find, so an extractor fix can make it wrong -- and because the entry
#: carries a current ``extractor_version`` it would otherwise never be re-tested
#: and the text would stay lost. Version 1: reading ``OtherAbstract``, where
#: PubMed keeps PIP/KIE/NASA/AIDS abstracts; before it, such a record was stored
#: as having no content and a refresh deleted the abstract already cached for it
#: (issue #88). Scoped rather than bumping EXTRACTOR_CACHE_VERSION because an
#: entry that records content cannot be wrong in this way, and a blanket bump
#: would re-fetch every cached reference to find the ones that can be.
#:
#: The converse does not hold, and the stamp is deliberately general rather than
#: targeted: `unavailable` is emitted by doi, url, clinicaltrials, json_api,
#: entrez and ppr as well as pmid, and the OtherAbstract fix cannot help any of
#: those. In the dismech cache 1,499 of the 1,735 such entries are DOI, so most
#: of this refresh is cost rather than repair. That is accepted -- the stamp
#: means "this no-content claim was made by extractor version N", which a later
#: fix to any source will want, and it is still a 3% refresh against 100%.
ABSENT_CONTENT_CACHE_VERSION = 1

#: A cache file's frontmatter delimiter: a line that is exactly ``---``.
#: Splitting on the bare string instead lets any *value* containing ``---`` - a
#: URL reference_id, a title - truncate the block, which loses every field after
#: it and hides the version stamp. An entry whose stamp is hidden reads as
#: unstamped, so it is re-fetched, rewritten with the same id, and read as
#: unstamped again: a re-fetch on every run, forever.
_FRONTMATTER_DELIMITER = re.compile(r"^---[ \t]*$", re.MULTILINE)

_FORMAT_TO_CONTENT_TYPE = {
    "pdf": "full_text_pdf",
    "html": "full_text_html",
    "xml": "full_text_xml",
    "text": "full_text",
}


def _text_after_abstract(content: Optional[str]) -> str:
    """Return a record's extracted text, without the abstract prepended to it.

    ``_apply_full_text_location`` stores ``abstract + "\\n\\n" + text``, so both
    the cached record and a refreshed one carry the abstract. Comparing whole
    records credits a failed extraction with text it was always going to have:
    a ~2,000-character abstract, the median in a real cache, by itself clears a
    fifth of a 10,000-character entry.

    Split on the first blank line, which is the join that produced it *when
    there was an abstract to prepend*. ``_apply_full_text_location`` writes bare
    text when there is not -- a source that returned no abstract, or a record
    that came straight from PMC -- and the partition then lands on the first
    paragraph break in the body and drops the opening paragraph instead.

    Neither mistake is symmetric, and neither is serious. Under-subtracting on
    the *fresh* side leaves it larger and so less likely to report;
    under-subtracting on the *cached* side raises the bar and makes a report
    more likely. Both decide a log line, never a refusal.
    """
    text = content or ""
    _, separator, body = text.partition("\n\n")
    return body if separator else text


#: Casefolded cache filename -> real names, per directory. Module-level on
#: purpose: see ``ReferenceFetcher._case_index`` for why per-instance state
#: leaves two fetchers on one directory blind to each other's writes.
_CASE_INDEXES: dict[Path, dict[str, set[str]]] = {}

#: Characters ``json.dumps(ensure_ascii=False)`` leaves literal that the YAML
#: reader nonetheless rejects or the scanner treats as a line break: DEL, the
#: C1 block, and the Unicode line and paragraph separators. JSON escapes only
#: below 0x20, so these reach the file raw -- and a raw C1 byte makes the
#: reader refuse the whole entry, while a raw separator inside a quoted scalar
#: folds to a space on reload. The realistic source is mojibake: Windows-1252
#: read as Latin-1 turns smart quotes and en-dashes into ``\x91``-``\x97``, a
#: common shape for bibliographic metadata.
_YAML_UNSAFE = re.compile("[\x7f-\x9f\u2028\u2029]")


def _json_scalar(value: str) -> str:
    """Render ``value`` as a JSON string that survives a YAML round trip."""
    rendered = json.dumps(value, ensure_ascii=False)
    return _YAML_UNSAFE.sub(lambda m: f"\\u{ord(m.group(0)):04x}", rendered)


class _RefreshLoss:
    """Describe what a refused refresh returned, formatted only if logged.

    ``logger.warning`` decides whether a record is emitted before rendering its
    arguments, so an f-string built at the call site is computed whichever way
    that goes. The rest of this module passes lazy ``%s`` arguments; this keeps
    the branch on ``content_type`` without breaking that.
    """

    __slots__ = ("_fresh",)

    def __init__(self, fresh: ReferenceContent) -> None:
        self._fresh = fresh

    def __str__(self) -> str:
        if self._fresh.content_type in NEEDS_FULL_TEXT_TYPES:
            return f"no full text ({self._fresh.content_type})"
        # The extracted text, not the whole record. Both records carry the same
        # abstract, so including it quotes the cached entry at one size here and
        # another in the caller's own ``%d``, and shows a pair that can read as
        # half while the sentence says "much shorter". The subtracted lengths
        # are the ones every caller decides on.
        return (
            f"{len(_text_after_abstract(self._fresh.content))} characters of "
            f"{self._fresh.content_type}"
        )


@dataclass(frozen=True)
class FetchOutcome:
    """A fetch result together with how it was obtained.

    ``content`` alone cannot distinguish text that came from the source from
    text served out of an out-of-date cache entry because the reference could
    not be re-fetched - the source may be unreachable, or no source may handle
    the identifier at all. Callers that only need the text use
    :meth:`ReferenceFetcher.fetch`; callers acting on whether only an
    out-of-date entry could be served - ``cache reference``, whose whole job is
    to populate the cache - need ``served_stale`` too.

    Examples:
        >>> FetchOutcome(content=None).served_stale
        False
        >>> outcome = FetchOutcome(
        ...     content=ReferenceContent(reference_id="PMID:1"), served_stale=True
        ... )
        >>> outcome.content.reference_id
        'PMID:1'
    """

    content: Optional[ReferenceContent]
    served_stale: bool = False


class ReferenceFetcher:
    """Fetch and cache references from various sources.

    Uses a plugin architecture to support multiple reference types:
    - PMID (PubMed IDs)
    - DOI (Digital Object Identifiers via Crossref API)
    - file (local files)
    - url (web URLs)

    Examples:
        >>> config = ReferenceValidationConfig()
        >>> fetcher = ReferenceFetcher(config)
        >>> # This would fetch from NCBI in real usage
        >>> # ref = fetcher.fetch("PMID:12345678")

        >>> # Local file support
        >>> # ref = fetcher.fetch("file:./research/notes.md")

        >>> # URL support
        >>> # ref = fetcher.fetch("url:https://example.com/paper.html")
    """

    def __init__(self, config: ReferenceValidationConfig):
        """Initialize the reference fetcher.

        Args:
            config: Configuration for fetching and caching

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher.config.email
            'linkml-reference-validator@example.com'
        """
        self.config = config
        # Keyed by normalized reference ID. The value is the whole outcome, not
        # just the content, so an entry cannot be separated from how it was
        # obtained: a stale fallback stays flagged on every later read in this
        # process instead of being laundered into a fresh-looking hit.
        self._cache: dict[str, FetchOutcome] = {}
        self._acquirer = ContentAcquirer()
        # Build the PDF extractor once: this validates config.pdf_backend up front
        # (an unknown backend raises here, at init, rather than mid-fetch) and avoids
        # re-instantiating the backend on every download.
        self._pdf_extractor = PDFExtractor(backend=config.pdf_backend)
        register_custom_full_text_providers(config.full_text_providers_file)

    def fetch(
        self, reference_id: str, force_refresh: bool = False
    ) -> Optional[ReferenceContent]:
        """Fetch a reference by ID.

        Supports various ID formats:
        - PMID:12345678
        - DOI:10.xxxx/yyyy
        - file:./path/to/file.md
        - url:https://example.com

        The content may have been served from an out-of-date cache entry because
        the reference could not be re-fetched; callers that must tell those apart
        use :meth:`fetch_with_provenance` instead.

        Args:
            reference_id: The reference identifier
            force_refresh: If True, bypass cache and fetch fresh

        Returns:
            ReferenceContent if found, None otherwise

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> # Would fetch in real usage:
            >>> # ref = fetcher.fetch("PMID:12345678")
            >>> # ref = fetcher.fetch("file:./notes.md")
        """
        return self.fetch_with_provenance(reference_id, force_refresh).content

    def fetch_with_provenance(
        self, reference_id: str, force_refresh: bool = False
    ) -> FetchOutcome:
        """Fetch a reference, reporting whether only an out-of-date entry was served.

        Identical to :meth:`fetch` except for the return type: the outcome's
        ``served_stale`` is True when the reference could not be re-fetched and
        an out-of-date cache entry was served in its place. That leaves the cache
        without a current entry, so a caller whose job is to populate it should
        treat it as a failure - not because nothing was downloaded, which is
        equally true of a cache hit that needed no download, but because the
        entry that is there is the one this version was meant to replace.

        Args:
            reference_id: The reference identifier
            force_refresh: If True, bypass cache and fetch fresh

        Returns:
            A :class:`FetchOutcome` wrapping the content, if any

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> # Would fetch in real usage:
            >>> # outcome = fetcher.fetch_with_provenance("PMID:12345678")
            >>> # outcome.served_stale
        """
        normalized_reference_id = self.normalize_reference_id(reference_id)

        # Check memory cache
        if not force_refresh and normalized_reference_id in self._cache:
            return self._cache[normalized_reference_id]

        # Check disk cache
        if not force_refresh:
            cached = self._load_from_disk(normalized_reference_id)
            if cached:
                # A record cached as abstract_only may predate full-text support, or
                # reflect a prior transient failure. Give the chain one more chance
                # per process if it was never cleanly attempted.
                cached = self._maybe_retry_full_text(cached)
                return self._remember(
                    normalized_reference_id, FetchOutcome(content=cached)
                )

        # Find appropriate source using registry
        source_class = ReferenceSourceRegistry.get_source(normalized_reference_id)
        if not source_class:
            logger.warning(f"No source found for reference type: {normalized_reference_id}")
            return self._stale_fallback(normalized_reference_id, force_refresh)

        # Parse identifier and fetch
        _, identifier = self._parse_reference_id(normalized_reference_id)
        source = source_class()
        content = source.fetch(identifier, self.config)

        # Source-produced full HTML (currently PMC's body-selecting path) is
        # already extracted by that source. Certify only this fresh fetch, never
        # an arbitrary inventory/load/save round trip of pre-fix cached text.
        if content and content.content_type == "full_text_html":
            content.metadata = dict(
                content.metadata or {}, html_full_text_version=HTML_FULL_TEXT_CACHE_VERSION
            )

        if content and content.content_type == "full_text_xml":
            content.metadata = dict(
                content.metadata or {}, xml_extraction_version=XML_EXTRACTION_CACHE_VERSION
            )

        if content and self.config.fetch_full_text and self.needs_full_text(content):
            content = self._enrich_with_full_text(content)

        if not content:
            return self._stale_fallback(normalized_reference_id, force_refresh)

        preserved = self._preserve_cached_full_text(
            normalized_reference_id, content, force_refresh
        )
        if preserved is not None:
            return self._remember(normalized_reference_id, preserved)

        self._save_by_access(content)

        return self._remember(normalized_reference_id, FetchOutcome(content=content))

    def _remember(
        self, normalized_reference_id: str, outcome: FetchOutcome
    ) -> FetchOutcome:
        """Record an outcome in the memory cache and return it for the caller."""
        self._cache[normalized_reference_id] = outcome
        return outcome

    def _stale_fallback(
        self, normalized_reference_id: str, force_refresh: bool
    ) -> FetchOutcome:
        """Serve an out-of-date cache entry when the source yielded nothing.

        A stale entry is treated as absent on the happy path so the current
        extractors rewrite it. That is only safe while a replacement can actually
        be fetched: offline, during a provider outage, or for a record since
        withdrawn, "this text is out of date" must not become "this reference does
        not exist". The older copy is worse than a fresh fetch and much better than
        reporting every cached reference as not found.

        The entry is deliberately not re-saved, so it stays stale and the next run
        that can reach the source still refreshes it. ``force_refresh`` opts out
        entirely: an explicit refresh that failed should report failure.
        Unverified HTML full-text entries are excluded: their text may be only
        landing-page metadata, which cannot safely serve as article evidence.

        The outcome is flagged ``served_stale`` so callers that need the cache to
        hold a current entry afterwards can report failure rather than success.
        """
        if force_refresh:
            return FetchOutcome(content=None)

        stale = self._load_from_disk(normalized_reference_id, allow_stale=True)
        if stale is None:
            return FetchOutcome(content=None)

        logger.warning(
            "Could not re-fetch %s; using the cache entry written by an older "
            "extractor. Its text may still contain the errors this version fixes.",
            normalized_reference_id,
        )
        return self._remember(
            normalized_reference_id, FetchOutcome(content=stale, served_stale=True)
        )

    def _preserve_cached_full_text(
        self,
        normalized_reference_id: str,
        fresh: ReferenceContent,
        force_refresh: bool,
    ) -> Optional[FetchOutcome]:
        """Refuse a refresh that would replace cached full text with none.

        A refresh may improve an entry; it may never demote one. That invariant
        is about the **public** validation cache, which is the only one
        :meth:`_load_from_disk` reads; a private research-cache entry has no
        equivalent protection, and none is attempted here. Full-text
        retrieval fails transiently and silently -- a rate-limited PMC request
        answers with a reCAPTCHA interstitial carried on an HTTP 200, so nothing
        downstream can distinguish it from article text. The bot page is
        rejected, the abstract fetch succeeds on its own, and the record would
        be written as ``abstract_only``: indistinguishable from "this article
        has no full text", and destroying whatever the entry held.

        :meth:`_stale_fallback` does not cover this. It fires only when the
        source yields *nothing*, and here the abstract is something.

        **Deleting and serving are separate decisions, and this method makes
        both.** Whether an entry may be *overwritten* is asked with
        ``allow_stale_html=True``, because a stale ``full_text_html`` entry is
        still somebody's data and destroying it is not this method's business.
        Whether its text may be *served as evidence* is asked without that
        bypass, so :meth:`_load_from_disk`'s refusal of stale HTML -- "it may be
        a repository landing page" -- still holds. An entry can therefore be
        kept on disk and withheld from validation at the same time, which is the
        right answer for a pre-fix entry scraped from a landing page: the
        curator's file is not deleted, and its suspect text is not quoted back
        as though it came from the article.

        Narrow on purpose:

        * only a **loss** of full text is refused -- the refresh coming back
          with none at all (see :meth:`_refresh_loses_full_text`, which is a rule
          about kind and does not compare sizes) -- so an entry that gains full
          text, keeps it, or had none to begin with, migrates normally. A
          refresh that keeps full text but returns far less of it is reported by
          :meth:`_report_shrinking_refresh` and written;
        * the preserved entry is **not re-saved**, so it stays stale and the
          next run that can reach the source still refreshes it -- the same
          contract :meth:`_stale_fallback` documents;
        * ``force_refresh`` opts out of the *refusal*, because an explicit
          refresh that found less is a result the caller asked for -- but not of
          the notice: :meth:`_warn_forced_discard` still says what it replaced.

        Both outcomes set ``served_stale``. The flag's consumer is ``cache
        reference``, which reports "the cache still holds no current entry for
        it", and that is exactly true here in both branches: the write was
        skipped, so the entry on disk is the out-of-date one either way.

        Returns ``None`` when the refresh may proceed normally.
        """
        if force_refresh:
            self._warn_forced_discard(normalized_reference_id, fresh)
            return None

        # May it be overwritten? Stale HTML is readable for this question only.
        cached = self._load_from_disk(
            normalized_reference_id, allow_stale=True, allow_stale_html=True
        )
        if cached is None or self.needs_full_text(cached):
            return None
        if not self._refresh_loses_full_text(cached, fresh):
            # The write proceeds. Say so if it replaced much more than it brought,
            # which is the only place that report can be true.
            self._report_shrinking_refresh(normalized_reference_id, cached, fresh)
            return None

        logger.warning(
            "Refresh of %s returned %s; keeping the cached %s entry rather than "
            "overwriting it. It stays stale, so a later run will try again.",
            normalized_reference_id,
            _RefreshLoss(fresh),
            cached.content_type,
        )

        # May its text be served? Asked without the bypass, so stale HTML is
        # withheld here exactly as _stale_fallback withholds it, and validation
        # falls back to the freshly fetched abstract.
        servable = self._load_from_disk(normalized_reference_id, allow_stale=True)
        return FetchOutcome(content=servable or fresh, served_stale=True)

    def _report_shrinking_refresh(
        self,
        normalized_reference_id: str,
        cached: ReferenceContent,
        fresh: ReferenceContent,
    ) -> None:
        """Note a refresh that keeps full text but returns far less of it.

        Reported rather than refused. A PDF whose text layer is a publisher
        cover sheet is still typed ``full_text_pdf``, so the kind rule lets it
        through and the article body is overwritten -- and until this existed
        that happened with no output at all, leaving a curator whose quoted
        evidence stopped verifying with nothing to pull on.

        Refusing it is what this guard used to do, and what cost four rounds of
        permanently blocked migrations. A warning shares none of that: the write
        proceeds, the entry is stamped, the migration completes, and a wrong
        guess costs one log line.
        """
        cached_length = len(_text_after_abstract(cached.content))
        if not cached_length:
            return
        if len(_text_after_abstract(fresh.content)) >= cached_length * REPORT_SHRINK_RATIO:
            return
        logger.warning(
            "Refresh of %s replaced the cached %s entry (%d characters of "
            "article text) with a much shorter one: %s. Written as usual, since "
            "a shorter extraction is often a cleaner one -- but check it if "
            "quoted excerpts stop verifying.",
            normalized_reference_id,
            cached.content_type,
            cached_length,
            _RefreshLoss(fresh),
        )

    def _warn_forced_discard(
        self, normalized_reference_id: str, fresh: ReferenceContent
    ) -> None:
        """Say what ``force_refresh`` is about to destroy, before it does.

        The opt-out itself is right: an explicit refresh that finds less is a
        result the caller asked for. Doing it silently is not. ``--force`` is
        what both the ``cache reference`` failure message and the troubleshooting
        docs name as the remedy, and a preserved entry fails on every run, so the
        pressure to reach for it is continuous and it is typically run across a
        batch rather than one reference at a time. Following that advice should
        not quietly perform the loss this guard exists to prevent.
        """
        cached = self._load_from_disk(
            normalized_reference_id, allow_stale=True, allow_stale_html=True
        )
        if cached is None or self.needs_full_text(cached):
            return
        if not self._refresh_loses_full_text(cached, fresh):
            return
        logger.warning(
            "--force is replacing the cached %s entry for %s (%d characters of "
            "article text) with %s. The cached text is not recoverable from here.",
            cached.content_type,
            normalized_reference_id,
            len(_text_after_abstract(cached.content)),
            _RefreshLoss(fresh),
        )

    @staticmethod
    def _refresh_loses_full_text(
        cached: ReferenceContent, fresh: ReferenceContent
    ) -> bool:
        """Report whether a refresh replaces full text with no full text.

        Deliberately a rule about *kind*, not a comparison of size. An earlier
        version also refused a refresh whose text was a fraction of the cached
        length, to catch a cover-page PDF extraction that clears the acceptance
        floor. That guarded one real case and mis-handled four others -- a page
        scrape replaced by a clean XML body, by a clean HTML body, a plain-text
        API body replaced by XML, and any re-extraction that merely trimmed a
        trailing section -- because a shorter extraction is usually a *better*
        one, and the shrink cannot tell the two apart.

        Each of those mis-handled cases fails in the worse direction. A refusal
        is not a one-off: the entry is never written, so it is never stamped, so
        every later run re-fetches and re-refuses it while ``cache reference``
        exits 1. A guard meant to protect the cache instead pinned it
        permanently at its pre-migration content.

        The size question belongs in the acceptance layer, where
        :func:`linkml_reference_validator.etl.extract.xml.is_stub_notice`
        already rejects an XML placeholder before it is ever cached, and where a
        wrong answer costs one skipped fetch rather than a cache that can never
        migrate. Extending it to PDF text layers -- a cover sheet reads much like
        the placeholder it already catches -- would close the one case this rule
        knowingly lets through; ``test_a_cover_page_pdf_is_not_refused_but_is_reported``
        pins that gap and says to invert it when that lands.

        Examples:
            >>> from linkml_reference_validator.models import ReferenceContent
            >>> def ref(content_type):
            ...     return ReferenceContent(
            ...         reference_id="PMID:1", content="text", content_type=content_type
            ...     )
            >>> ReferenceFetcher._refresh_loses_full_text(
            ...     ref("full_text_html"), ref("abstract_only"))
            True

            A shorter or differently-shaped full text is still full text:

            >>> ReferenceFetcher._refresh_loses_full_text(
            ...     ref("full_text_html"), ref("full_text_xml"))
            False
            >>> ReferenceFetcher._refresh_loses_full_text(
            ...     ref("full_text_xml"), ref("full_text"))
            False
        """
        return fresh.content_type in NEEDS_FULL_TEXT_TYPES

    def needs_full_text(self, content: ReferenceContent) -> bool:
        """Return True if the content lacks full text and the chain should run.

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> from linkml_reference_validator.models import ReferenceContent
            >>> fetcher.needs_full_text(
            ...     ReferenceContent(reference_id="DOI:1", content_type="abstract_only")
            ... )
            True
            >>> fetcher.needs_full_text(
            ...     ReferenceContent(reference_id="DOI:1", content_type="full_text_xml")
            ... )
            False
        """
        return content.content_type in NEEDS_FULL_TEXT_TYPES

    def _maybe_retry_full_text(self, content: ReferenceContent) -> ReferenceContent:
        """Re-run the full-text chain for a cached record that never cleanly tried.

        Leaves a record alone once it already has full text, when full-text fetching
        is disabled, or when a prior clean run already concluded none is available
        (``full_text_attempted``). When a retry changes the record it is re-saved so
        the result persists. This is what lets a one-off provider outage recover on a
        later run instead of being cached as permanent absence (PR #48 review #1).
        """
        if (
            not self.config.fetch_full_text
            or content.full_text_declined
            or not self.needs_full_text(content)
            or content.full_text_attempted
        ):
            return content

        before = (content.content, content.content_type, content.full_text_attempted)
        content = self._enrich_with_full_text(content)
        after = (content.content, content.content_type, content.full_text_attempted)
        if after != before:
            self._save_by_access(content)
        return content

    def _save_by_access(self, content: ReferenceContent) -> None:
        """Persist content according to its access provenance.

        Ordinary enrichment rejects private locations before this point. The
        private branch remains a defensive safeguard for callers handling an
        explicitly private ``ReferenceContent`` outside validation.
        """
        self._save_to_disk(
            content,
            private=content.full_text_access_type not in (None, "open"),
        )

    def _enrich_with_full_text(self, content: ReferenceContent) -> ReferenceContent:
        """Merge the first usable public full text from the provider chain.

        If no provider yields usable full text but the chain was consulted without
        a transient error *and without declining anything*, mark
        ``full_text_attempted`` so the record is not re-queried on every later
        run. A provider/download error leaves the flag unset so a subsequent run
        retries (PR #48 review #1), and so does a policy decline -- see the note
        at the assignment for why those are the same kind of thing. Locations
        with an explicit non-open access type are ignored: private-library
        material is available to the separate cache-enrichment workflow, never to
        ordinary validation.
        """
        ids = build_identifiers(content)
        abstract = content.content
        had_error = False
        declined_on_policy: Optional[str] = None

        for provider_name in self.config.full_text_providers:
            provider = FullTextProviderRegistry.get(provider_name)
            if provider is None:
                logger.debug(f"Full-text provider not registered: {provider_name}")
                continue

            try:  # external system boundary: a provider failure must not abort the chain
                location = provider.locate(ids, self.config)
            except Exception as exc:
                logger.warning(f"Provider '{provider_name}' failed for {content.reference_id}: {exc}")
                had_error = True
                continue

            if location is None:
                continue

            if location.declined:
                logger.debug(
                    "Provider '%s' declined a candidate for %s (%s)",
                    provider_name,
                    content.reference_id,
                    location.declined,
                )
                declined_on_policy = location.declined
                continue

            if location.access_type not in (None, "open"):
                logger.info(
                    "Ignoring non-public full text from provider '%s' for %s",
                    provider_name,
                    content.reference_id,
                )
                declined_on_policy = f"access_type:{location.access_type}"
                continue

            applied, error = self._apply_full_text_location(
                content, abstract, location, provider_name
            )
            if error:
                had_error = True
            if applied:
                return content

        # No usable full text. ``full_text_attempted`` means "a clean run
        # concluded none is available", and ``_maybe_retry_full_text`` never runs
        # the chain again once it is set, so only a genuine absence may set it.
        #
        # Two outcomes are not absences. A transient failure is not one, which
        # ``had_error`` has always covered. Neither is a location we *found* and
        # declined -- a bronze PDF refused on licence, or a landing page refused
        # because fetching it would be scraping. Those are decisions about
        # material that exists, and recording a decision as a fact about the
        # article is the defect this whole change is about, one layer up: a
        # bronze record that later converts to gold, or a page-only DOI that
        # later gains a repository PDF, would never be looked at again.
        #
        # The cost of leaving the flag unset is one chain re-run per process for
        # those references, which is the trade ``had_error`` already makes.
        if declined_on_policy:
            # Remembered, not asserted. Leaving nothing at all would be correct
            # and ruinous: a decline never clears the way a transient error
            # does, so every run would re-walk the whole chain for every bronze
            # or page-only reference -- four providers, each opening with a
            # rate-limit sleep, against the hosts whose rate limiting produces
            # the interstitial this guard exists for. On one real corpus that is
            # 23,465 eligible entries and about thirteen hours of sleep per run.
            # The entry is re-fetched when the extractor version moves, which is
            # when a re-walk is actually worth paying for.
            content.full_text_declined = declined_on_policy
        elif not had_error:
            content.full_text_attempted = True
        return content

    def locate_full_text(
        self, content: ReferenceContent, provider_name: str
    ) -> Optional[FullTextLocation]:
        """Locate full text for cached content using exactly one provider.

        This is the inventory primitive used by ``cache enrich --dry-run``. It
        deliberately ignores ``full_text_attempted`` because a newly configured
        private library may contain a manuscript that public providers missed.

        Raises:
            ValueError: If ``provider_name`` is not registered.
        """
        provider = FullTextProviderRegistry.get(provider_name)
        if provider is None:
            raise ValueError(f"Unknown full-text provider: {provider_name}")
        return provider.locate(build_identifiers(content), self.config)

    def apply_full_text_location(
        self,
        content: ReferenceContent,
        location: FullTextLocation,
        provider_name: str,
        private: bool = False,
    ) -> bool:
        """Materialize one located resource, update content, and persist it."""
        private = private or location.access_type not in (None, "open")
        abstract = content.content
        applied, _ = self._apply_full_text_location(
            content, abstract, location, provider_name, private=private
        )
        if applied:
            if not private:
                normalized_id = self.normalize_reference_id(content.reference_id)
                # Enriched and about to be written back with the current stamp,
                # so whatever was served before, this copy is no longer stale.
                self._remember(normalized_id, FetchOutcome(content=content))
            self._save_to_disk(content, private=private)
        return applied

    def iter_cached_references(self) -> Iterator[ReferenceContent]:
        """Yield modern Markdown cache entries in deterministic path order."""
        for cache_path in sorted(self.config.get_cache_dir().glob("*.md")):
            content_text = cache_path.read_text(encoding="utf-8")
            reference = self._load_markdown_format(content_text, cache_path.stem)
            if reference is not None:
                yield reference

    def _apply_full_text_location(
        self,
        content: ReferenceContent,
        abstract: Optional[str],
        location: FullTextLocation,
        provider_name: str,
        private: bool = False,
    ) -> tuple[bool, bool]:
        """Apply one location and return ``(applied, transient_error)``."""
        text, fmt, pdf_bytes, error = self._materialize(location)
        if not text or len(text.strip()) < MIN_FULL_TEXT_CHARS:
            return False, error

        if (
            fmt == "html" and abstract
            and " ".join(text.split()) == " ".join(abstract.split())
        ):
            return False, error

        content.content = f"{abstract}\n\n{text}" if abstract else text
        content.content_type = _FORMAT_TO_CONTENT_TYPE.get(fmt or "text", "full_text")
        if fmt == "html":
            content.metadata = dict(
                content.metadata or {}, html_full_text_version=HTML_FULL_TEXT_CACHE_VERSION
            )
        if fmt == "xml":
            content.metadata = dict(
                content.metadata or {}, xml_extraction_version=XML_EXTRACTION_CACHE_VERSION
            )
        content.full_text_provider = location.provider or provider_name
        # A private-library endpoint is not durable provenance and may carry
        # session-specific access information -- a localhost Zotero attachment
        # URL means nothing to anyone else and may encode a local token. A
        # publisher's own link is neither: it is a stable public URL, and the
        # reason a PUBLISHER_FREE_ACCESS location's *text* stays out of the
        # public cache is licensing rather than secrecy, so recording where it
        # came from costs nothing and is worth keeping.
        content.full_text_url = (
            location.url
            if location.access_type in PUBLIC_URL_ACCESS_TYPES
            else None
        )
        content.oa_status = location.oa_status
        content.license = location.license
        content.full_text_access_type = location.access_type
        content.full_text_source_item_id = location.source_item_id
        content.full_text_attempted = True
        if pdf_bytes is not None and self.config.download_pdfs:
            content.local_pdf_path = self._save_pdf(
                content.reference_id, pdf_bytes, private=private
            )
        return True, error

    def _materialize(
        self, location: FullTextLocation
    ) -> tuple[Optional[str], Optional[str], Optional[bytes], bool]:
        """Turn a FullTextLocation into ``(text, format, pdf_bytes_if_any, error)``.

        ``error`` is True only when a download or extraction *raised* — a transient
        condition worth retrying — not when the resource was merely absent or unusable.
        ``location.text`` is a trusted provider's already-extracted article body
        (PMC or a configured text API). HTML markup supplied there still requires
        structural extraction; a format hint alone does not certify raw HTML.
        """
        if location.text:
            if location.format_hint == "html" and re.search(r"<[A-Za-z][^>]*>", location.text):
                return HTMLExtractor().extract_full_text(location.text), "html", None, False
            return location.text, location.format_hint or "text", None, False

        if not location.url:
            return None, None, None, False

        try:  # external system boundary
            data, content_type = self._acquirer.fetch_bytes(location.url, self.config)
        except Exception as exc:
            logger.warning(f"Download failed for {location.url}: {exc}")
            return None, None, None, True

        if data is None:
            return None, None, None, False

        # Trust the actual bytes over the server content-type / provider hint: a
        # url_for_pdf that really returns an HTML landing page must not reach pypdf.
        fmt = sniff_format(data) or resolve_format(content_type, location.url, location.format_hint)
        if fmt is None:
            return None, None, None, False

        extractor: Optional[Extractor]
        if fmt == "pdf":
            extractor = self._pdf_extractor
        else:
            extractor = ExtractorRegistry.get(fmt)
        if extractor is None:
            return None, fmt, None, False

        try:  # external system boundary: parsing arbitrary downloaded bytes
            text = (
                HTMLExtractor().extract_full_text(data)
                if fmt == "html"
                else extractor.extract(data, content_type=content_type)
            )
        except Exception as exc:
            logger.warning(f"Extraction failed for {location.url}: {exc}")
            return None, fmt, None, True

        pdf_bytes = data if fmt == "pdf" else None
        return text, fmt, pdf_bytes, False

    def _save_pdf(
        self, reference_id: str, data: bytes, private: bool = False
    ) -> str:
        """Persist a downloaded PDF and return its path relative to the cache dir."""
        safe_id = (
            reference_id.replace(":", "_").replace("/", "_").replace("?", "_").replace("=", "_")
        )
        files_dir = (
            self.config.get_private_files_cache_dir()
            if private
            else self.config.get_files_cache_dir()
        )
        pdf_path = files_dir / f"{safe_id}.pdf"
        pdf_path.write_bytes(data)
        if private:
            pdf_path.chmod(0o600)
            return str(pdf_path.relative_to(self.config.get_private_cache_dir()))
        return str(pdf_path.relative_to(self.config.cache_dir))

    def _parse_reference_id(
        self, reference_id: str, *, apply_prefix_map: bool = True
    ) -> tuple[str, str]:
        """Parse a reference ID into prefix and identifier.

        Args:
            reference_id: Reference ID like "PMID:12345678" or URL
            apply_prefix_map: Resolve configured aliases; disabled for cache paths
                because fetch has already resolved the caller's alias.

        Returns:
            Tuple of (prefix, identifier)

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._parse_reference_id("PMID:12345678")
            ('PMID', '12345678')
            >>> fetcher._parse_reference_id("PMID 12345678")
            ('PMID', '12345678')
            >>> fetcher._parse_reference_id("12345678")
            ('PMID', '12345678')
            >>> fetcher._parse_reference_id("file:./test.md")
            ('file', './test.md')
            >>> fetcher._parse_reference_id("url:https://example.com/page")
            ('url', 'https://example.com/page')
            >>> fetcher._parse_reference_id("https://example.com/page")
            ('url', 'https://example.com/page')
            >>> fetcher._parse_reference_id("http://example.com")
            ('url', 'http://example.com')
            >>> config = ReferenceValidationConfig(reference_prefix_map={"geo": "GEO"})
            >>> ReferenceFetcher(config)._parse_reference_id("geo:GSE12345")
            ('GEO', 'GSE12345')
        """
        stripped = reference_id.strip()

        # Handle bare HTTP/HTTPS URLs (before the prefix:identifier parsing)
        if stripped.lower().startswith(("http://", "https://")):
            return "url", stripped

        # Bare trial IDs use the same prefix and identifier casing as the source.
        if NCT_ID_PATTERN.fullmatch(stripped):
            stripped = f"clinicaltrials:{stripped}"

        # Standard prefix:identifier format
        match = re.match(r"^([A-Za-z_]+)[:\s]+(.+)$", stripped)
        if match:
            prefix = match.group(1)
            # Match the canonical prefix used by the source and prefix aliases.
            prefix = self._normalize_prefix(prefix)
            if apply_prefix_map:
                prefix = self._apply_prefix_map(prefix)
            identifier = match.group(2).strip()
            if prefix == "clinicaltrials" and NCT_ID_PATTERN.fullmatch(identifier):
                identifier = identifier.upper()
            return prefix, identifier
        if reference_id.strip().isdigit():
            return "PMID", reference_id.strip()
        return "UNKNOWN", reference_id

    def normalize_reference_id(self, reference_id: str) -> str:
        """Normalize reference IDs using configured prefix aliases.

        Args:
            reference_id: Raw reference ID (e.g., "pmid:12345678", "PMID 12345678")

        Returns:
            Normalized reference ID (e.g., "PMID:12345678")

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher.normalize_reference_id("pmid:12345678")
            'PMID:12345678'
            >>> fetcher.normalize_reference_id("PMID 12345678")
            'PMID:12345678'
            >>> fetcher.normalize_reference_id("NCT12345678")
            'clinicaltrials:NCT12345678'
            >>> fetcher.normalize_reference_id("CLINICALTRIALS:nct12345678")
            'clinicaltrials:NCT12345678'
        """
        prefix, identifier = self._parse_reference_id(reference_id)
        if prefix == "UNKNOWN":
            return reference_id.strip()
        return f"{prefix}:{identifier}"

    def _normalize_prefix(self, prefix: str) -> str:
        """Normalize prefix casing to match the reference sources."""
        if prefix.lower() in ("file", "url", "clinicaltrials"):
            return prefix.lower()
        return prefix.upper()

    def _apply_prefix_map(self, prefix: str) -> str:
        """Apply configured prefix aliases."""
        prefix_map = self._normalized_prefix_map()
        return prefix_map.get(prefix, prefix)

    def _normalized_prefix_map(self) -> dict[str, str]:
        """Return a case-normalized prefix map."""
        normalized: dict[str, str] = {}
        for key, value in self.config.reference_prefix_map.items():
            normalized[self._normalize_prefix(key)] = self._normalize_prefix(value)
        return normalized

    def get_cache_path(self, reference_id: str) -> Path:
        """Get the cache file path for a reference.

        Bare NCT IDs and ClinicalTrials casing are canonicalized. For configured
        prefix aliases, pass the result of :meth:`normalize_reference_id`.

        Args:
            reference_id: Reference identifier

        Returns:
            Path to cache file

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> path = fetcher.get_cache_path("PMID:12345678")
            >>> path.name
            'PMID_12345678.md'
            >>> path = fetcher.get_cache_path("url:https://example.com/book/chapter1")
            >>> path.name
            'url_https___example.com_book_chapter1.md'
        """
        return self._cache_path(reference_id, self.config.get_cache_dir())

    def _cache_path(self, reference_id: str, cache_dir: Path) -> Path:
        """Return a cache path, canonicalizing ClinicalTrials IDs in either cache."""
        prefix, identifier = self._parse_reference_id(
            reference_id, apply_prefix_map=False
        )
        if prefix == "clinicaltrials":
            reference_id = f"{prefix}:{identifier}"
        # Other IDs already arrive normalized from fetch(). Reapplying arbitrary
        # prefix maps here could follow a second alias and change the cache key.
        safe_id = (
            reference_id.replace(":", "_")
            .replace("/", "_")
            .replace("?", "_")
            .replace("=", "_")
        )
        path = cache_dir / f"{safe_id}.md"
        if prefix.upper() == "DOI":
            return self._existing_case_variant(path)
        return path

    @staticmethod
    def _stored_reference_id(cache_path: Path, reference: ReferenceContent) -> str:
        """The id already recorded in ``cache_path``, else the reference's own.

        Applied to DOI references only, since that is what the argument covers:
        a DOI in two capitalizations is one reference, so the spelling first
        written should stand. Sanitization also collapses ``:`` ``/`` ``?`` and
        ``=`` to ``_``, so two *distinct* ``url:`` references can share a
        filename; that collision predates this change and cementing the first
        writer's id there would change how it is handled, for an identifier
        type the argument does not cover.

        Read with ``errors="replace"``: an entry too mangled to decode is the one
        that most needs overwriting, and a ``UnicodeDecodeError`` here would be
        the one thing that stops it. Only the ``reference_id:`` line is read, so
        replacement characters elsewhere cost nothing.
        """
        if not reference.reference_id.upper().startswith("DOI:"):
            return reference.reference_id
        try:
            with cache_path.open(encoding="utf-8", errors="replace") as handle:
                for position, line in enumerate(handle):
                    if line.startswith("reference_id:"):
                        stored = line.split(":", 1)[1].strip()
                        return stored or reference.reference_id
                    # The opening delimiter is the first line; the closing one
                    # ends the frontmatter and with it anywhere the id can be.
                    if position and line.strip() == "---":
                        break
        except OSError:  # no existing entry, or unreadable
            pass
        return reference.reference_id

    def _existing_case_variant(self, path: Path) -> Path:
        """Return an already-cached file differing from ``path`` only in case.

        DOI names are case-insensitive by specification, so
        ``10.1016/S0002-9440(10)63332-9`` and its lowercase spelling are one
        reference. The prefix is normalized but the suffix is not, so without
        this each spelling gets its own file: a duplicate download, and two
        committed entries for one paper in a project that versions its cache.

        Resolution looks for what is already on disk rather than imposing a
        canonical spelling, so an existing cache is not renamed underneath
        anyone -- a project holding thousands of DOI entries sees no diff, and
        whichever spelling was written first keeps winning.

        Scoped to DOI on purpose. A PMID or an NCT id is not case-insensitive,
        and folding those would merge genuinely distinct references.

        The index is built from real directory entries and ``exists()`` is never
        consulted. On a case-insensitive filesystem -- macOS by default --
        ``exists()`` is true for a spelling that is *not* the one on disk, so
        trusting it would return the caller's spelling and write a second entry
        that silently collides with the first.

        Where a cache already holds *both* spellings -- what a case-sensitive
        checkout of an already-duplicated repository looks like -- the caller's
        exact spelling wins, and failing that the lexicographically first, so
        the answer does not depend on directory order.
        """
        index = self._case_index(path.parent)
        names = index.get(path.name.casefold())
        if not names:
            return path
        if path.name in names:
            return path
        return path.parent / min(names)

    @staticmethod
    def _case_index(cache_dir: Path) -> dict[str, set[str]]:
        """Casefolded name -> real names, built once per directory per process.

        ``_cache_path`` is on the read path and the write path both, so scanning
        the directory per resolution is quadratic over a cache: measured at
        6.7 ms a call against a 6,721-entry directory, or 45 seconds of pure
        path resolution for a run that touches every reference.

        The index is shared across every fetcher in the process, not held per
        instance. ``Repairer`` holds two fetchers over one directory -- its own
        and the one inside ``SupportingTextValidator`` -- and interleaves them
        across many references, so with per-instance state each one's writes
        were invisible to the other and a cross-spelling DOI could still produce
        two files. Every write funnels through :meth:`_remember_cache_file`, so
        one shared map stays accurate for the whole process.

        What it cannot see is a writer *outside this process* -- another run,
        or a subprocess this one shelled out to -- which is the window
        :meth:`forget_cache_listing` exists for.
        """
        cached = _CASE_INDEXES.get(cache_dir)
        if cached is not None:
            return cached
        index: dict[str, set[str]] = {}
        if cache_dir.is_dir():
            for entry in cache_dir.iterdir():
                index.setdefault(entry.name.casefold(), set()).add(entry.name)
        _CASE_INDEXES[cache_dir] = index
        return index

    @staticmethod
    def forget_cache_listing() -> None:
        """Drop the cached directory listings used to resolve DOI capitalization.

        Call this after something *outside this process* has written to a cache
        directory -- another run, or a subprocess -- so the next DOI lookup sees
        the new files. Writes from any fetcher in this process are already
        tracked. Cheap: a listing is rebuilt on the next resolution that needs
        it.
        """
        _CASE_INDEXES.clear()

    @staticmethod
    def _remember_cache_file(path: Path) -> None:
        """Record a newly written file so a later lookup in another case finds it."""
        index = _CASE_INDEXES.get(path.parent)
        if index is not None:
            index.setdefault(path.name.casefold(), set()).add(path.name)

    def _quote_yaml_value(self, value: str) -> str:
        """Quote a YAML value if it contains special characters.

        YAML has many special characters that need quoting, including:
        - [ ] { } : , # & * ? | - < > = ! % @ `
        - Leading/trailing spaces
        - Values that look like booleans, nulls, or numbers

        Args:
            value: The string value to potentially quote

        Returns:
            The value, quoted if necessary

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._quote_yaml_value("[Cholera].")
            '"[Cholera]."'
            >>> fetcher._quote_yaml_value("Normal title")
            'Normal title'
            >>> fetcher._quote_yaml_value("Title: with colon")
            '"Title: with colon"'

            A line break cannot be carried by a plain or a double-quoted YAML
            scalar written on one line, so such a value is emitted JSON-style,
            which is valid YAML and reloads with the break intact:

            >>> fetcher._quote_yaml_value("Two\\nlines")
            '"Two\\\\nlines"'
        """
        # A literal line break ends the scalar, so interpolating one produces
        # frontmatter that does not parse -- and re-fetching rewrites the same
        # broken file, so nothing recovers it. Crossref titles do contain them.
        # JSON escaping is valid YAML and preserves the break on reload, where
        # folding it to a space would silently edit metadata that is compared
        # against the fetched record elsewhere.
        # ``splitlines`` splits on every break the YAML scanner recognises --
        # U+0085, U+2028 and U+2029 as well as \n and \r -- and on the vertical
        # tab and form feed, which the reader rejects outright as non-printable.
        # Each produces the same unrecoverable file, just with a rarer
        # character. ``!= [value]`` rather than ``len(...) > 1`` because a
        # trailing break splits to a single element.
        if value.splitlines() != [value] or _YAML_UNSAFE.search(value):
            return _json_scalar(value)

        # Characters that require quoting in YAML values
        special_chars = '[]{}:,#&*?|<>=!%@`"\'\\'
        needs_quote = False

        # Check for special characters
        for char in special_chars:
            if char in value:
                needs_quote = True
                break

        # Check for leading/trailing whitespace
        if value != value.strip():
            needs_quote = True

        # Check for values that YAML might misinterpret
        lower_value = value.lower()
        if lower_value in ("true", "false", "yes", "no", "on", "off", "null", "~"):
            needs_quote = True

        if needs_quote:
            # Escape any existing double quotes and wrap in double quotes
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'

        return value

    def _save_to_disk(
        self, reference: ReferenceContent, private: bool = False
    ) -> None:
        """Save reference content to disk cache as markdown with YAML frontmatter.

        Args:
            reference: Reference content to save
        """
        cache_path = self._cache_path(
            reference.reference_id,
            self.config.get_private_cache_dir()
            if private
            else self.config.get_cache_dir(),
        )

        lines = []
        lines.append("---")
        # An entry that already exists keeps the spelling it was written with.
        # The path resolves to that file either way, so rewriting this line
        # under the caller's capitalization would leave a one-line diff in a
        # committed cache on every cross-spelling re-fetch -- the churn this
        # resolution exists to remove, one layer in.
        lines.append(f"reference_id: {self._stored_reference_id(cache_path, reference)}")
        lines.append(f"extractor_version: {EXTRACTOR_CACHE_VERSION}")
        html_version = (reference.metadata or {}).get("html_full_text_version")
        if reference.content_type == "full_text_html" and isinstance(html_version, int):
            lines.append(f"html_full_text_version: {html_version}")
        # YAML booleans are not extraction versions, despite bool subclassing int.
        xml_version = (reference.metadata or {}).get("xml_extraction_version")
        if reference.content_type == "full_text_xml" and type(xml_version) is int:
            lines.append(f"xml_extraction_version: {xml_version}")
        # Written from the constant, unlike the HTML and XML stamps, which come
        # from `reference.metadata` so a metadata-only rewrite preserves the
        # original. That is safe here only because every path that saves an
        # `unavailable` entry has just produced it with this extractor:
        # `apply_full_text_location` saves only when it applied something, which
        # moves content_type away from `unavailable`, and `_maybe_retry_full_text`
        # runs on the fetch path where staleness already forced a re-fetch. An
        # enrichment path that re-saved an untouched `unavailable` entry would
        # certify it as re-tested when it was not -- recreating #88 one version
        # up. Move this to metadata if such a path is ever added.
        if reference.content_type == "unavailable":
            lines.append(f"absent_content_version: {ABSENT_CONTENT_CACHE_VERSION}")
        if reference.title:
            lines.append(f"title: {self._quote_yaml_value(reference.title)}")
        if reference.authors:
            lines.append("authors:")
            for author in reference.authors:
                lines.append(f"- {self._quote_yaml_value(author)}")
        if reference.journal:
            lines.append(f"journal: {self._quote_yaml_value(reference.journal)}")
        if reference.year:
            lines.append(f"year: '{reference.year}'")
        if reference.doi:
            lines.append(f"doi: {reference.doi}")
        if reference.keywords:
            lines.append("keywords:")
            for keyword in reference.keywords:
                lines.append(f"- {self._quote_yaml_value(keyword)}")
        if reference.publication_types:
            lines.append("publication_types:")
            for publication_type in reference.publication_types:
                lines.append(f"- {self._quote_yaml_value(publication_type)}")
        lines.append(f"content_type: {reference.content_type}")
        if reference.is_preprint is not None:
            lines.append(f"is_preprint: {str(reference.is_preprint).lower()}")
        if reference.peer_review_status:
            lines.append(
                f"peer_review_status: {self._quote_yaml_value(reference.peer_review_status)}"
            )
        if reference.full_text_attempted:
            lines.append("full_text_attempted: true")
        if reference.full_text_declined:
            lines.append(
                f"full_text_declined: "
                f"{self._quote_yaml_value(reference.full_text_declined)}"
            )
        if reference.full_text_provider:
            lines.append(f"full_text_provider: {reference.full_text_provider}")
        if reference.full_text_url:
            lines.append(f"full_text_url: {self._quote_yaml_value(reference.full_text_url)}")
        if reference.oa_status:
            lines.append(f"oa_status: {reference.oa_status}")
        if reference.license:
            lines.append(f"license: {self._quote_yaml_value(reference.license)}")
        if reference.local_pdf_path:
            lines.append(f"local_pdf_path: {self._quote_yaml_value(reference.local_pdf_path)}")
        if reference.full_text_access_type:
            lines.append(
                "full_text_access_type: "
                f"{self._quote_yaml_value(reference.full_text_access_type)}"
            )
        if reference.full_text_source_item_id:
            lines.append(
                "full_text_source_item_id: "
                f"{self._quote_yaml_value(reference.full_text_source_item_id)}"
            )
        if reference.metadata and "extra_fields_captured" in reference.metadata:
            extra_fields = reference.metadata.get("extra_fields_captured")
            if isinstance(extra_fields, list):
                lines.append("extra_fields_captured:")
                for field_name in extra_fields:
                    if isinstance(field_name, str):
                        lines.append(f"- {self._quote_yaml_value(field_name)}")
                    else:
                        logger.warning(
                            "Skipping non-string item in extra_fields_captured: %r (type %s)",
                            field_name,
                            type(field_name).__name__,
                        )
        if reference.supplementary_files:
            lines.append("supplementary_files:")
            for sf in reference.supplementary_files:
                lines.append(f"  - filename: {self._quote_yaml_value(sf.filename)}")
                if sf.download_url:
                    lines.append(f"    download_url: {self._quote_yaml_value(sf.download_url)}")
                if sf.content_type:
                    lines.append(f"    content_type: {sf.content_type}")
                if sf.size_bytes is not None:
                    lines.append(f"    size_bytes: {sf.size_bytes}")
                if sf.checksum:
                    lines.append(f"    checksum: {sf.checksum}")
                if sf.description:
                    lines.append(f"    description: {self._quote_yaml_value(sf.description)}")
                if sf.local_path:
                    lines.append(f"    local_path: {self._quote_yaml_value(sf.local_path)}")
        lines.append("---")
        lines.append("")

        if reference.title:
            lines.append(f"# {reference.title}")
            if reference.authors:
                lines.append(f"**Authors:** {', '.join(reference.authors)}")
            if reference.journal:
                journal_info = reference.journal
                if reference.year:
                    journal_info += f" ({reference.year})"
                lines.append(f"**Journal:** {journal_info}")
            if reference.doi:
                lines.append(
                    f"**DOI:** [{reference.doi}](https://doi.org/{reference.doi})"
                )
            lines.append("")
            lines.append("## Content")
            lines.append("")

        if reference.content:
            lines.append(reference.content)

        cache_path.write_text("\n".join(lines), encoding="utf-8")
        self._remember_cache_file(cache_path)
        if private:
            cache_path.chmod(0o600)
        logger.info(f"Cached {reference.reference_id} to {cache_path}")

    def _load_from_disk(
        self,
        reference_id: str,
        allow_stale: bool = False,
        allow_stale_html: bool = False,
    ) -> Optional[ReferenceContent]:
        """Load reference content from the public validation cache.

        Supports both new markdown format with YAML frontmatter and legacy text format.
        Private research caches are intentionally excluded so validation results are
        reproducible across local machines and CI.

        Args:
            reference_id: Reference identifier
            allow_stale: Return entries written by an older extractor instead of
                treating them as absent. Used once a fetch has already failed to
                produce a usable replacement -- by :meth:`_stale_fallback` when
                the source yielded nothing at all, and by
                :meth:`_preserve_cached_full_text` and
                :meth:`_warn_forced_discard` when it yielded no full text.
            allow_stale_html: Also return a stale ``full_text_html`` entry, which
                ``allow_stale`` alone withholds because it may be a repository
                landing page rather than the article. Set this only to decide
                whether an entry may be *overwritten*; leave it off to decide
                whether its text may be *served* as evidence. Meaningless
                without ``allow_stale``, which rejects a stale entry of any type
                before this is consulted.

        Returns:
            ReferenceContent if cached, None otherwise
        """
        cache_path = self.get_cache_path(reference_id)
        is_legacy = False

        if not cache_path.exists():
            legacy_path = cache_path.with_suffix(".txt")
            if not legacy_path.exists():
                return None
            cache_path = legacy_path
            is_legacy = True

        content_text = cache_path.read_text(encoding="utf-8")

        # The pre-Markdown format has no frontmatter to stamp, and is deliberately
        # exempt from the staleness check rather than perpetually stale: it is a
        # read-only compatibility path that nothing has written for a long time,
        # so such entries are as likely to be hand-maintained as tool-written -
        # and they are not what the extractor bugs produced, since those wrote
        # Markdown. Re-fetching them would discard someone's data to fix a
        # problem they do not have.
        if is_legacy or not content_text.startswith("---"):
            return self._load_legacy_format(content_text, reference_id)

        if not allow_stale and self._is_stale_cache_entry(content_text):
            logger.info(
                "Ignoring cache entry for %s written by an older extractor; "
                "it will be re-fetched and rewritten",
                reference_id,
            )
            return None
        reference = self._load_markdown_format(content_text, reference_id)
        if (
            allow_stale
            and not allow_stale_html
            and reference is not None
            and reference.content_type == "full_text_html"
            and self._is_stale_cache_entry(content_text)
        ):
            logger.warning(
                "Refusing stale HTML full text for %s: it may be a repository "
                "landing page. Retry when the source serves full text again to "
                "repair it.",
                reference_id,
            )
            return None
        return reference

    @staticmethod
    def _as_optional_list(value: Any) -> Optional[list]:
        """Normalise a frontmatter value into an optional list.

        YAML may parse a single-item field as a scalar rather than a list;
        this coerces such values back to a list and maps empties to None.

        Examples:
            >>> ReferenceFetcher._as_optional_list(["a", "b"])
            ['a', 'b']
            >>> ReferenceFetcher._as_optional_list("solo")
            ['solo']
            >>> ReferenceFetcher._as_optional_list(None) is None
            True
        """
        if not value:
            return None
        return value if isinstance(value, list) else [value]

    @staticmethod
    def _parse_cached_authors(value: Any, reference_id: str) -> Optional[list[str]]:
        """Recover author strings from legacy YAML without stringifying garbage.

        Unquoted colon-bearing authors can parse as mappings. Each string key
        paired with a string, int, float, or bool becomes one readable author,
        in order; a null value restores the name with a trailing colon. Scalar
        formatting may differ from the original YAML spelling. Valid strings
        are preserved verbatim. Null list entries, non-string scalar entries,
        empty maps, and pairs with non-string keys or unsupported values are
        dropped with a warning; nested structures are never traversed. An
        absent/null field, scalar empty string, or empty list means no authors,
        as does a list with no recoverable entries.

        Examples:
            >>> ReferenceFetcher._parse_cached_authors(
            ...     ["Smith J", {"Consortium": "contact@example.org"}], "PMID:1"
            ... )
            ['Smith J', 'Consortium: contact@example.org']
            >>> ReferenceFetcher._parse_cached_authors(
            ...     [{"Consortium": None, "Room": 305}], "PMID:1"
            ... )
            ['Consortium:', 'Room: 305']
            >>> ReferenceFetcher._parse_cached_authors(None, "PMID:1") is None
            True
        """
        if value is None or (isinstance(value, str) and not value):
            return None
        entries = value if isinstance(value, list) else [value]
        authors: list[str] = []
        dropped = 0
        for entry in entries:
            if isinstance(entry, str):
                authors.append(entry)
            elif isinstance(entry, dict) and entry:
                for name, detail in entry.items():
                    if isinstance(name, str) and detail is None:
                        authors.append(f"{name}:")
                    elif isinstance(name, str) and isinstance(detail, (str, int, float, bool)):
                        authors.append(f"{name}: {detail}")
                    else:
                        dropped += 1
            else:
                dropped += 1
        if dropped:
            logger.warning(
                "Dropped %d malformed author entries or mapping pairs from cache for %s",
                dropped,
                reference_id,
            )
        return authors or None

    @staticmethod
    def _split_frontmatter(content_text: str) -> Optional[tuple[str, str]]:
        """Split cache-file text into ``(frontmatter, body)``.

        Args:
            content_text: The cache file's contents

        Returns:
            The frontmatter and body, or None if the text is not delimited

        Examples:
            >>> ReferenceFetcher._split_frontmatter("---\\nyear: '2024'\\n---\\nBody.")
            ("\\nyear: '2024'\\n", '\\nBody.')
            >>> ReferenceFetcher._split_frontmatter("Body with no frontmatter.") is None
            True
            >>> # A value containing --- is not a delimiter; only a line that is
            >>> ReferenceFetcher._split_frontmatter("---\\ntitle: a---b\\n---\\nBody.")
            ('\\ntitle: a---b\\n', '\\nBody.')
        """
        parts = _FRONTMATTER_DELIMITER.split(content_text, maxsplit=2)
        if len(parts) < 3:
            return None
        return parts[1], parts[2]

    @classmethod
    def _is_stale_cache_entry(cls, content_text: str) -> bool:
        """Report whether extraction or format-specific full-text processing needs refreshing.

        Deliberately not applied by :meth:`iter_cached_references`: export and
        enrichment walk the cache as a record of what was fetched, and dropping
        older entries there would lose them rather than refresh them. Only the
        validation read path treats a stale entry as absent, so it is re-fetched
        and rewritten.

        Args:
            content_text: The cache file's contents, including frontmatter

        Returns:
            True if either applicable version stamp is absent or below current.

        Examples:
            >>> stale = "---\\nreference_id: PMID:1\\n---\\nBody."
            >>> ReferenceFetcher._is_stale_cache_entry(stale)
            True
            >>> current = f"---\\nextractor_version: {EXTRACTOR_CACHE_VERSION}\\n---\\nBody."
            >>> ReferenceFetcher._is_stale_cache_entry(current)
            False
        """
        split = cls._split_frontmatter(content_text)
        if split is None:
            return True

        # Preserve the pre-existing missing/old-version fast path, including for
        # damaged legacy frontmatter that a successful re-fetch can replace.
        match = re.search(r"^extractor_version:\s*(\d+)\s*$", split[0], re.MULTILINE)
        if not match or int(match.group(1)) < EXTRACTOR_CACHE_VERSION:
            return True

        metadata = YAML(typ="safe").load(split[0])
        if isinstance(metadata, dict) and metadata.get("content_type") == "full_text_html":
            html_version = metadata.get("html_full_text_version")
            if (
                not isinstance(html_version, int)
                or html_version < HTML_FULL_TEXT_CACHE_VERSION
            ):
                return True

        if isinstance(metadata, dict) and metadata.get("content_type") == "full_text_xml":
            xml_version = metadata.get("xml_extraction_version")
            if type(xml_version) is not int or xml_version < XML_EXTRACTION_CACHE_VERSION:
                return True

        # Scoped to `unavailable`, which leaves one gap: with
        # `source_extra_fields["PMID"]` configured, a record with no abstract is
        # stored as `summary` carrying the extra-fields blob, so an
        # OtherAbstract-only record damaged by #88 lands outside this rule and is
        # never re-tested. Widening to `summary` is not worth it -- most summary
        # entries have nothing to do with a missing abstract, so it would cost a
        # re-fetch of all of them. A deployment using that setting should clear
        # its affected entries by hand.
        if isinstance(metadata, dict) and metadata.get("content_type") == "unavailable":
            absent_version = metadata.get("absent_content_version")
            if (
                type(absent_version) is not int
                or absent_version < ABSENT_CONTENT_CACHE_VERSION
            ):
                return True

        # A newer stamp is not stale: an older tool reading a cache written by a
        # newer one should leave it alone rather than re-fetch it on every run.
        return False

    def _load_markdown_format(
        self, content_text: str, reference_id: str
    ) -> Optional[ReferenceContent]:
        """Load reference from markdown format with YAML frontmatter.

        Args:
            content_text: File contents
            reference_id: Reference identifier

        Returns:
            ReferenceContent if successful, None otherwise
        """
        split = self._split_frontmatter(content_text)
        if split is None:
            logger.warning(f"Invalid markdown format for {reference_id}")
            return None

        yaml_parser = YAML(typ="safe")
        frontmatter = yaml_parser.load(split[0])
        body = split[1].strip()

        content = self._extract_content_from_markdown(body)

        authors = self._parse_cached_authors(frontmatter.get("authors"), reference_id)
        keywords = self._as_optional_list(frontmatter.get("keywords"))
        publication_types = self._as_optional_list(
            frontmatter.get("publication_types")
        )

        # Parse supplementary files
        supplementary_files = self._parse_supplementary_files(
            frontmatter.get("supplementary_files")
        )

        metadata: dict = {}
        if "xml_extraction_version" in frontmatter:
            metadata["xml_extraction_version"] = frontmatter["xml_extraction_version"]
        if "html_full_text_version" in frontmatter:
            metadata["html_full_text_version"] = frontmatter["html_full_text_version"]
        if "extra_fields_captured" in frontmatter:
            metadata["extra_fields_captured"] = frontmatter["extra_fields_captured"]

        return ReferenceContent(
            reference_id=frontmatter.get("reference_id", reference_id),
            title=frontmatter.get("title"),
            content=content,
            content_type=frontmatter.get("content_type", "unknown"),
            authors=authors,
            journal=frontmatter.get("journal"),
            year=str(frontmatter.get("year")) if frontmatter.get("year") else None,
            doi=frontmatter.get("doi"),
            keywords=keywords,
            publication_types=publication_types,
            supplementary_files=supplementary_files,
            metadata=metadata,
            full_text_provider=frontmatter.get("full_text_provider"),
            full_text_url=frontmatter.get("full_text_url"),
            oa_status=frontmatter.get("oa_status"),
            license=frontmatter.get("license"),
            local_pdf_path=frontmatter.get("local_pdf_path"),
            full_text_access_type=frontmatter.get("full_text_access_type"),
            full_text_source_item_id=frontmatter.get("full_text_source_item_id"),
            is_preprint=frontmatter.get("is_preprint"),
            peer_review_status=frontmatter.get("peer_review_status"),
            full_text_attempted=bool(frontmatter.get("full_text_attempted", False)),
            full_text_declined=frontmatter.get("full_text_declined"),
        )

    def _extract_content_from_markdown(self, body: str) -> str:
        """Extract the actual content from markdown body.

        Removes the title, authors, journal, and DOI headers to get just the content.

        Args:
            body: Markdown body text

        Returns:
            Extracted content
        """
        lines = body.split("\n")
        content_start = 0

        for i, line in enumerate(lines):
            if line.strip().startswith("## Content"):
                content_start = i + 1
                break

        if content_start > 0:
            content_lines = lines[content_start:]
            while content_lines and not content_lines[0].strip():
                content_lines.pop(0)
            return "\n".join(content_lines)

        return body

    def _parse_supplementary_files(
        self, files_data: Optional[list]
    ) -> Optional[list[SupplementaryFile]]:
        """Parse supplementary files from YAML frontmatter data.

        Args:
            files_data: List of file dicts from YAML frontmatter

        Returns:
            List of SupplementaryFile objects, or None if no files

        Examples:
            >>> config = ReferenceValidationConfig()
            >>> fetcher = ReferenceFetcher(config)
            >>> fetcher._parse_supplementary_files(None) is None
            True
            >>> fetcher._parse_supplementary_files([]) is None
            True
            >>> files = fetcher._parse_supplementary_files([
            ...     {"filename": "test.pdf", "size_bytes": 1000}
            ... ])
            >>> len(files)
            1
            >>> files[0].filename
            'test.pdf'
        """
        if not files_data:
            return None

        files = []
        for f in files_data:
            if not isinstance(f, dict):
                continue
            filename = f.get("filename")
            if not filename:
                continue
            files.append(
                SupplementaryFile(
                    filename=filename,
                    download_url=f.get("download_url"),
                    content_type=f.get("content_type"),
                    size_bytes=f.get("size_bytes"),
                    checksum=f.get("checksum"),
                    description=f.get("description"),
                    local_path=f.get("local_path"),
                )
            )

        return files if files else None

    def _load_legacy_format(
        self, content_text: str, reference_id: str
    ) -> Optional[ReferenceContent]:
        """Load reference from legacy text format.

        Args:
            content_text: File contents
            reference_id: Reference identifier

        Returns:
            ReferenceContent if successful, None otherwise
        """
        lines = content_text.split("\n")

        metadata = {}
        content_start = 0

        for i, line in enumerate(lines):
            if not line.strip():
                content_start = i + 1
                break
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()

        content = (
            "\n".join(lines[content_start:]).strip()
            if content_start < len(lines)
            else None
        )

        authors = (
            metadata.get("Authors", "").split(", ") if metadata.get("Authors") else None
        )

        return ReferenceContent(
            reference_id=metadata.get("ID", reference_id),
            title=metadata.get("Title"),
            content=content,
            content_type=metadata.get("ContentType", "unknown"),
            authors=authors,
            journal=metadata.get("Journal"),
            year=metadata.get("Year"),
            doi=metadata.get("DOI"),
        )
