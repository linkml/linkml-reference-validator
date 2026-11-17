"""Sign excerpts: verify quotes against local full text and write snippet-only bundles.

A curator who holds a closed paper's full text maps it with ``local_full_text``
or ``local_full_text_dir`` and validates locally. :func:`sign_excerpts` then
writes, for each such reference, a bundle in ``signed_excerpts_dir`` holding
only the quotes that matched, so CI can validate the same ``DOI:`` citations
through the signed-excerpt fallback without the file (#174). No other text from
the paper is written.

Each signed excerpt carries a ``verification`` record: the SHA-256 of the text
it was matched against, the validator version, and the date. This is an
*attestation*, not a cryptographic signature. It tells a reviewer which entries
were produced by this command rather than typed by hand, but anyone able to
edit the bundle can also edit the record. With
``signed_excerpts_require_verification`` on, validation ignores entries that
carry no record.
"""

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import date
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from ruamel.yaml import YAML  # type: ignore
from ruamel.yaml.comments import CommentedMap  # type: ignore

from linkml_reference_validator import __version__
from linkml_reference_validator.cache import (
    _same_reference_id,
    cache_filename,
    disambiguated_cache_filename,
)
from linkml_reference_validator.models import ReferenceValidationConfig
from linkml_reference_validator.signed_excerpts import BUNDLE_SUFFIXES
from linkml_reference_validator.validation.evidence_items import _extract_evidence_items
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

logger = logging.getLogger(__name__)

#: ``verification.method`` written by :func:`sign_excerpts`.
SIGN_METHOD = "local_full_text"


@dataclass
class SignFailure:
    """A quote that did not verify against the local full text, and why."""

    reference_id: str
    text: str
    message: str


@dataclass
class SignReport:
    """What a signing run did (or, with ``dry_run``, would do).

    Examples:
        >>> SignReport().changed
        False
        >>> SignReport(written=["PMID_1.yaml"]).changed
        True
    """

    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failures: list[SignFailure] = field(default_factory=list)
    no_local_text: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """True if any bundle differs (or differed) from what signing produces."""
        return bool(self.written)


def collapse_whitespace(text: str) -> str:
    """Fold whitespace runs, as signed-excerpt matching does.

    Examples:
        >>> collapse_whitespace("  a \\n b  ")
        'a b'
    """
    return re.sub(r"\s+", " ", text).strip()


def collect_quotes(data_files: Iterable[Path]) -> list[tuple[str, str]]:
    """Return (reference ID, quote) pairs found in YAML data files, in file order.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> _ = (d / "a.yaml").write_text(
        ...     "evidence:\\n- reference: PMID:1\\n  supporting_text: a quote\\n")
        >>> collect_quotes([d / "a.yaml"])
        [('PMID:1', 'a quote')]
    """
    pairs: list[tuple[str, str]] = []
    yaml = YAML(typ="safe")
    for path in data_files:
        for document in yaml.load_all(path.read_text(encoding="utf-8")):
            if isinstance(document, (dict, list)):
                for text, reference_id, _ in _extract_evidence_items(document, None):
                    pairs.append((reference_id, text))
    return pairs


def _source_text_stats(path: Path, content: str) -> tuple[str, int]:
    """The SHA-256 of the file's bytes, and the non-whitespace length of its text."""
    sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return sha, len(re.sub(r"\s", "", content))


def _bundle_path(
    directory: Path,
    normalized_id: str,
    normalize: Callable[[str], str] = lambda reference_id: reference_id,
) -> Optional[Path]:
    """The bundle file for ``normalized_id`` in ``directory``.

    Tries the same names validation reads, in the same order: the usual cache
    stem, then the disambiguated one, each as ``.yaml`` or ``.yml``. A file
    that records a different ``reference_id`` belongs to the reference whose
    name it shares and is skipped, so its quotes are never merged with ours
    (#131). Stored IDs are compared after ``normalize``, as validation compares
    them. With no existing bundle, the usual name is used unless another
    reference holds it. Returns None if other references hold both names.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> _bundle_path(d, "PMID:1").name
        'PMID_1.yaml'
        >>> _ = (d / "PMID_1.yaml").write_text("reference_id: PMID:2\\n")
        >>> _bundle_path(d, "PMID:1").name.startswith("PMID_1_")
        True
    """
    stems = [
        Path(cache_filename(normalized_id)).stem,
        Path(disambiguated_cache_filename(normalized_id)).stem,
    ]
    taken = [False, False]
    for position, stem in enumerate(stems):
        for suffix in BUNDLE_SUFFIXES:
            candidate = directory / f"{stem}{suffix}"
            if not candidate.is_file():
                continue
            stored = _stored_reference_id(candidate)
            if stored is None or _same_reference_id(normalize(stored), normalized_id):
                return candidate
            taken[position] = True
    if not taken[0]:
        return directory / f"{stems[0]}.yaml"
    if not taken[1]:
        return directory / f"{stems[1]}.yaml"
    return None


def _stored_reference_id(path: Path) -> Optional[str]:
    """The ``reference_id`` a bundle file records, if any."""
    data = YAML(typ="safe").load(path.read_text(encoding="utf-8"))
    stored = data.get("reference_id") if isinstance(data, dict) else None
    return None if stored is None else str(stored)


def _round_trip_yaml() -> YAML:
    """A YAML instance that keeps an existing bundle's layout and comments."""
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=2, offset=0)
    return yaml


def _excerpt_text(item: Any) -> Optional[str]:
    """The quoted text of a bundle entry, written as a string or a mapping."""
    text = item if isinstance(item, str) else (
        item.get("text") if isinstance(item, dict) else None
    )
    return text if isinstance(text, str) else None


def _signed_here(item: Any) -> bool:
    """Whether a bundle entry was written by :func:`sign_excerpts`."""
    verification = item.get("verification") if isinstance(item, dict) else None
    return isinstance(verification, dict) and verification.get("method") == SIGN_METHOD


def _merge(
    bundle: CommentedMap,
    verified: list[str],
    verification: dict[str, str],
    title: Optional[str],
    source_char_count: Optional[int],
    prune: bool = False,
) -> bool:
    """Merge verified quotes into ``bundle``; return True if it changed.

    Existing excerpts keep their place and every field. One whose text is a
    verified quote gets a fresh ``verification`` unless it already records the
    same source hash, so re-signing unchanged text changes nothing. New quotes
    are appended in sorted order so output does not depend on file order.
    With ``prune``, entries this command signed earlier that are not among
    ``verified`` are removed; entries from anywhere else are always kept.
    """
    changed = False
    if title and bundle.get("title") != title:
        bundle["title"] = title
        changed = True
    if source_char_count is not None and bundle.get("source_char_count") != source_char_count:
        bundle["source_char_count"] = source_char_count
        changed = True

    excerpts = bundle.get("excerpts")
    if not isinstance(excerpts, list):
        excerpts = []
        bundle["excerpts"] = excerpts
        changed = True

    if prune:
        keep = {collapse_whitespace(q) for q in verified}
        stale = [
            index
            for index, item in enumerate(excerpts)
            if _signed_here(item)
            and collapse_whitespace(_excerpt_text(item) or "") not in keep
        ]
        for index in reversed(stale):
            del excerpts[index]
            changed = True

    by_text: dict[str, Any] = {}
    for index, item in enumerate(excerpts):
        text = _excerpt_text(item)
        if text is not None:
            by_text.setdefault(collapse_whitespace(text), index)

    for quote in sorted(set(verified)):
        key = collapse_whitespace(quote)
        if key in by_text:
            index = by_text[key]
            item = excerpts[index]
            if isinstance(item, str):
                item = CommentedMap(text=item)
                excerpts[index] = item
            current = item.get("verification")
            if (
                isinstance(current, dict)
                and current.get("source_sha256") == verification["source_sha256"]
            ):
                continue
            item["verification"] = dict(verification)
            changed = True
        else:
            excerpts.append(CommentedMap(text=quote, verification=dict(verification)))
            by_text[key] = len(excerpts) - 1
            changed = True
    return changed


def _bundle_cap_problem(
    bundle: CommentedMap,
    validator: SupportingTextValidator,
    source_char_count: Optional[int],
) -> Optional[str]:
    """Why the merged bundle as a whole exceeds a fair-use cap, if it does.

    Validation only counts the quotes cited in one run, but the committed
    bundle keeps every quote ever signed into it. Checking the whole bundle
    stops it from collecting more of a paper than either cap allows.
    """
    config = validator.config
    total = sum(
        validator.count_quoted_characters(text)
        for text in (_excerpt_text(item) for item in bundle.get("excerpts") or [])
        if text is not None
    )
    advice = "not written (--prune drops signed excerpts no longer cited)"
    limit = config.max_total_chars_per_reference
    if limit > 0 and total > limit:
        return (
            f"Bundle holds {total} non-whitespace characters of quoted text, "
            f"maximum is {limit} (max_total_chars_per_reference); {advice}"
        )
    fraction = config.max_reference_fraction
    if fraction > 0.0 and source_char_count:
        allowed = int(source_char_count * fraction)
        if total > allowed:
            return (
                f"Bundle holds {total} of {source_char_count} non-whitespace "
                f"characters ({total / source_char_count:.1%}), maximum is "
                f"{fraction:.1%} (max_reference_fraction); {advice}"
            )
    return None


def sign_excerpts(
    data_files: Iterable[Path],
    config: ReferenceValidationConfig,
    references: Optional[Iterable[str]] = None,
    dest_dir: Optional[Path] = None,
    dry_run: bool = False,
    today: Optional[str] = None,
    prune: bool = False,
) -> SignReport:
    """Verify quotes in ``data_files`` against local full text and write bundles.

    Every quote citing a reference that ``local_full_text`` or
    ``local_full_text_dir`` maps to an existing file is validated against that
    file with the usual matcher and fair-use caps. Quotes that pass are merged
    into ``<dest_dir>/<cache stem>.yaml``; quotes that fail are reported and
    left out. Existing bundles are never consulted as evidence, so a hand-typed
    entry cannot be re-signed.

    Args:
        data_files: YAML data files to scan for quotes
        config: Validation config; supplies the mappings and the caps
        references: Only sign these references. Each must have local text, or
            it is listed in ``no_local_text``. Default: every cited reference
            that has local text.
        dest_dir: Bundle directory; default ``config.signed_excerpts_dir``
        dry_run: Write nothing; report what would change
        today: ``verified_at`` date (ISO); default today
        prune: Remove excerpts this command signed earlier that are no longer
            cited (or no longer verify); excerpts from elsewhere are kept

    A bundle is not written if, after merging, its quotes as a whole exceed
    ``max_total_chars_per_reference`` or ``max_reference_fraction``, nor if
    the source file changed while its quotes were being checked.

    Raises:
        ValueError: if neither ``dest_dir`` nor ``signed_excerpts_dir`` is set.
    """
    directory = dest_dir or config.signed_excerpts_dir
    if directory is None:
        raise ValueError("No destination: set signed_excerpts_dir or pass dest_dir")
    directory = Path(directory)

    # Verify against the local text only: an existing bundle must not vouch
    # for the quotes it is about to be extended with.
    checking = config.model_copy(update={"signed_excerpts_dir": None})
    validator = SupportingTextValidator(checking)
    fetcher = validator.fetcher
    report = SignReport()

    wanted = [fetcher.normalize_reference_id(r) for r in references or []]
    quotes: dict[str, list[str]] = {}
    for reference_id, text in collect_quotes(data_files):
        normalized = fetcher.normalize_reference_id(reference_id)
        if wanted and not any(_same_reference_id(w, normalized) for w in wanted):
            continue
        quotes.setdefault(normalized, []).append(text)
    for reference_id in wanted:
        if fetcher.local_full_text_path(reference_id) is None:
            report.no_local_text.append(reference_id)

    yaml = _round_trip_yaml()
    stamp = today or date.today().isoformat()
    for reference_id, texts in quotes.items():
        source = fetcher.local_full_text_path(reference_id)
        if source is None:
            continue
        reference = fetcher.fetch(reference_id)
        if reference is None or not reference.content:
            continue
        sha, char_count = _source_text_stats(source, reference.content)

        verified: list[str] = []
        failed = False
        for text in texts:
            result = validator.validate(text, reference_id)
            if result.is_valid:
                verified.append(text)
            else:
                failed = True
                report.failures.append(SignFailure(reference_id, text, result.message or ""))
        if _source_text_stats(source, reference.content)[0] != sha:
            report.failures.append(
                SignFailure(
                    reference_id,
                    "",
                    f"{source.name} changed while its quotes were being checked; "
                    "nothing signed for this reference, run again",
                )
            )
            continue
        # A failure may mean the wrong file is mapped (a preprint, say), so
        # pruning against this run could delete excerpts that were right.
        prune_here = prune and not failed
        if not verified and not prune_here:
            continue
        verification = {
            "method": SIGN_METHOD,
            "source_sha256": sha,
            "validator_version": __version__,
            "verified_at": stamp,
        }
        _update_bundle(
            report, yaml, directory, reference_id, fetcher.normalize_reference_id,
            validator, verified, verification, reference.title, char_count,
            prune_here, dry_run,
        )

    if prune and not wanted:
        # References the data no longer cites at all: drop what this command
        # signed for them. Needs no local text, since nothing is verified.
        cited = set(quotes)
        for path in sorted(p for p in directory.glob("*") if p.suffix in BUNDLE_SUFFIXES):
            stored = _stored_reference_id(path)
            if stored is None:
                continue
            normalized = fetcher.normalize_reference_id(stored)
            if any(_same_reference_id(normalized, c) for c in cited):
                continue
            _update_bundle(
                report, yaml, directory, normalized, fetcher.normalize_reference_id,
                validator, [], None, None, None, True, dry_run,
            )

    return report


def _update_bundle(
    report: SignReport,
    yaml: YAML,
    directory: Path,
    reference_id: str,
    normalize: Callable[[str], str],
    validator: SupportingTextValidator,
    verified: list[str],
    verification: Optional[dict[str, str]],
    title: Optional[str],
    source_char_count: Optional[int],
    prune: bool,
    dry_run: bool,
) -> None:
    """Merge into, cap-check and (unless ``dry_run``) write one reference's bundle.

    The caps are checked whether or not the merge changed anything, so
    ``--check`` reports a bundle that was over them already.
    """
    path = _bundle_path(directory, reference_id, normalize)
    if path is None:
        report.failures.append(
            SignFailure(
                reference_id,
                "",
                "both bundle names for this reference hold another reference's "
                "bundle; nothing written",
            )
        )
        return
    bundle = (
        yaml.load(path.read_text(encoding="utf-8")) if path.is_file() else None
    ) or CommentedMap(reference_id=reference_id)
    changed = _merge(
        bundle, verified, verification or {"source_sha256": ""}, title,
        source_char_count, prune=prune,
    )
    known_count = bundle.get("source_char_count")
    cap_problem = _bundle_cap_problem(
        bundle, validator, known_count if isinstance(known_count, int) else None
    )
    if cap_problem:
        report.failures.append(SignFailure(reference_id, "", cap_problem))
        return
    if not changed:
        report.unchanged.append(path.name)
        return
    report.written.append(path.name)
    if dry_run:
        return
    directory.mkdir(parents=True, exist_ok=True)
    buffer = StringIO()
    yaml.dump(bundle, buffer)
    path.write_text(buffer.getvalue(), encoding="utf-8")
    logger.info("Signed %d excerpt(s) for %s in %s", len(verified), reference_id, path)
