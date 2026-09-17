"""Base class and registry for full-text providers.

A provider, given cross-walked identifiers, returns a FullTextLocation that points
to (or directly contains) the full text of a reference. Providers are tried in a
configured order until one yields usable text.
"""

import logging
from abc import ABC, abstractmethod
from typing import Optional

from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)

logger = logging.getLogger(__name__)

#: ``oa_status`` values that are openly licensed on their own.
#:
#: ``bronze`` is deliberately absent. It means the publisher has made the article
#: free to read on its own site under no open licence: readable, not
#: redistributable. Treating "I may read this" as "this project may republish
#: this" is the distinction PR #61 drew for Zotero private libraries, and it
#: applies identically to a bronze PDF.
#:
#: ``green`` is absent too, and for a subtler reason: it describes *where* a copy
#: lives -- a repository -- not the terms it lives there under. A green PMC
#: author manuscript is free to read under a funder policy whose redistribution
#: terms vary by publisher, which is the same shape of claim as bronze with a
#: different host. It is admitted by :func:`access_type_for_oa_status` only when
#: the location states a licence.
#:
#: **Scope.** This governs a file found by asking an OA *index* -- OpenAlex or
#: Unpaywall -- where the index's own status is all that is known about the
#: terms. It deliberately does not govern ``pmc`` or ``epmc_preprint``, which
#: return ``oa_status="green"`` with no ``access_type`` and so continue to write
#: to the public cache. Those providers ask the archive's own API for a document
#: it serves for machine retrieval, which is a stronger warrant than an index's
#: summary of a third-party host, and routing them through this rule would
#: decline most PMID full text for want of a licence field their API does not
#: return. The asymmetry is deliberate: the same green deposit can be declined
#: from OpenAlex and admitted from PMC.
SELF_EVIDENTLY_OPEN_OA_STATUSES = frozenset({"gold", "diamond", "hybrid"})

#: ``oa_status`` values that are open *if* the location states a licence. See
#: the note on ``green`` above.
LICENCE_DEPENDENT_OA_STATUSES = frozenset({"green"})

#: Licence values outside the ``cc-`` family that grant redistribution.
OPEN_LICENCES = frozenset({"cc0", "public-domain", "mit"})


def states_a_licence(licence: Optional[str]) -> bool:
    """Report whether a location's ``license`` field grants redistribution.

    An **allowlist**, matching how this module treats ``oa_status``: a value it
    has not heard of is an unknown licence, and an unknown licence is not a
    grant. A truthiness test would not do, because neither API uses ``None`` as
    its only way of saying "no licence statement". OpenAlex's vocabulary
    includes ``other-oa`` (5.9M works) and ``publisher-specific-oa``, and
    Unpaywall documents ``implied-oa`` for a copy it believes free with no
    licence statement found. All three are truthy strings naming the *absence*
    of a licence -- and a bare funder-policy repository deposit, which is the
    case the ``green`` rule was written about, is exactly where they appear.

    Every Creative Commons variant qualifies. ``nc`` restricts commercial use
    and ``nd`` restricts derivatives; neither restricts holding a verbatim copy,
    which is all a cache does.

    Examples:
        >>> states_a_licence("cc-by")
        True
        >>> states_a_licence("cc-by-nc-nd")
        True
        >>> states_a_licence("public-domain")
        True

        The sentinels that mean "no licence statement" do not:

        >>> states_a_licence("other-oa")
        False
        >>> states_a_licence("implied-oa")
        False
        >>> states_a_licence(None)
        False
    """
    value = (licence or "").strip().lower()
    return value.startswith("cc-") or value in OPEN_LICENCES


#: ``access_type`` for a location that is free to read but not openly licensed.
#: Any non-``open`` value is skipped by ``_enrich_with_full_text``; naming it
#: distinctly keeps the reason legible in a log line.
PUBLISHER_FREE_ACCESS = "publisher_free"


def access_type_for_oa_status(
    oa_status: Optional[str], licence: Optional[str] = None
) -> str:
    """Map an ``oa_status`` (and licence, where it decides) to an ``access_type``.

    Unrecognised and missing statuses are **not** treated as open. A status this
    version has not heard of is an unknown licence, and the safe reading of an
    unknown licence is that it does not grant redistribution.

    ``green`` is decided by the licence rather than the status, because the
    status names a repository rather than a permission: a deposit that states
    its licence is open, a bare one is not. "States its licence" means
    :func:`states_a_licence`, not merely a non-empty field -- see there for why
    the difference matters.

    Known miss: a work's ``oa_status`` is its *best* status across locations, so
    a work marked ``bronze`` may still carry an openly-licensed repository copy
    in a location this code never inspects. Conservative rather than wrong --
    some redistributable full text is skipped -- and widening it means walking
    every location instead of the best one.

    Examples:
        >>> access_type_for_oa_status("gold")
        'open'
        >>> access_type_for_oa_status("bronze")
        'publisher_free'
        >>> access_type_for_oa_status(None)
        'publisher_free'
        >>> access_type_for_oa_status("something-new")
        'publisher_free'

        A repository deposit is open when it states its terms, and not when it
        merely states its address:

        >>> access_type_for_oa_status("green", licence="cc-by")
        'open'
        >>> access_type_for_oa_status("green")
        'publisher_free'

        A licence does not rescue a status that is not licence-dependent:

        >>> access_type_for_oa_status("bronze", licence="cc-by")
        'publisher_free'
    """
    status = (oa_status or "").strip().lower()
    if status in SELF_EVIDENTLY_OPEN_OA_STATUSES:
        return "open"
    if status in LICENCE_DEPENDENT_OA_STATUSES and states_a_licence(licence):
        return "open"
    return PUBLISHER_FREE_ACCESS


class FullTextProvider(ABC):
    """Abstract base class for full-text providers."""

    @classmethod
    @abstractmethod
    def name(cls) -> str:
        """Return the provider name used in the configured chain (e.g. 'unpaywall')."""
        ...

    @abstractmethod
    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        """Return a FullTextLocation, or None if this provider cannot supply one."""
        ...


class FullTextProviderRegistry:
    """Registry mapping provider names to provider instances.

    Examples:
        >>> from linkml_reference_validator.etl.fulltext.base import FullTextProviderRegistry
        >>> FullTextProviderRegistry.get("nope") is None
        True
    """

    _by_name: dict[str, FullTextProvider] = {}

    @classmethod
    def register(cls, provider_class: type[FullTextProvider]) -> type[FullTextProvider]:
        """Register a provider class (usable as a decorator)."""
        cls._by_name[provider_class.name()] = provider_class()
        logger.debug(f"Registered full-text provider: {provider_class.name()}")
        return provider_class

    @classmethod
    def register_instance(cls, name: str, provider: FullTextProvider) -> None:
        """Register a pre-built provider instance under ``name`` (for custom providers)."""
        cls._by_name[name] = provider
        logger.debug(f"Registered full-text provider instance: {name}")

    @classmethod
    def get(cls, name: str) -> Optional[FullTextProvider]:
        """Return the provider registered under ``name``, or None."""
        return cls._by_name.get(name)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered providers (for testing)."""
        cls._by_name = {}
