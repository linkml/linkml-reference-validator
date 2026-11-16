"""Sync signed excerpt bundles from a private full-text store into a public repo.

A private store such as claimstore keeps full texts and verifies short fair-use
excerpts against them. Each verified bundle (``<REF_ID>.yaml`` with a
``reference_id`` and a list of ``excerpts``) is copied verbatim into a public
repo's ``signed_excerpts_dir``, where validation accepts an exact match against
it. This module selects which bundles a public repo needs and copies them.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

from ruamel.yaml import YAML  # type: ignore

BUNDLE_SUFFIXES = (".yaml", ".yml")


@dataclass
class SyncReport:
    """Bundle filenames grouped by what a sync did (or would do) to each.

    Examples:
        >>> SyncReport().changed
        False
        >>> SyncReport(added=["PMID_1.yaml"]).changed
        True
    """

    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        """True if the destination differs (or differed) from the selection."""
        return bool(self.added or self.updated or self.removed)


def is_tagged_for(bundle: dict[str, Any], target_repo: str) -> bool:
    """Return True if any excerpt in ``bundle`` lists ``target_repo`` in its target_repo.

    Examples:
        >>> b = {"excerpts": [{"text": "x", "target_repo": ["dismech:kb/disorders/A.yaml"]}]}
        >>> is_tagged_for(b, "dismech")
        True
        >>> is_tagged_for(b, "dis")
        False
        >>> is_tagged_for({"excerpts": [{"text": "x", "target_repo": "dismech"}]}, "dismech")
        True
        >>> is_tagged_for({"excerpts": ["plain string excerpt"]}, "dismech")
        False
    """
    for excerpt in bundle.get("excerpts") or []:
        if not isinstance(excerpt, dict):
            continue
        targets = excerpt.get("target_repo") or []
        if isinstance(targets, str):
            targets = [targets]
        for target in targets:
            if target == target_repo or str(target).startswith(f"{target_repo}:"):
                return True
    return False


def find_cited_reference_ids(
    reference_ids: Iterable[str], paths: Iterable[Path]
) -> set[str]:
    """Return the subset of ``reference_ids`` that appear in any file in ``paths``.

    Matching ignores case (DOIs are case-insensitive) and respects identifier
    boundaries, so ``PMID:1`` is not found inside ``PMID:12``.

    Examples:
        >>> import tempfile
        >>> d = Path(tempfile.mkdtemp())
        >>> _ = (d / "a.yaml").write_text("reference: PMID:12\\nsee doi:10.1/X.")
        >>> sorted(find_cited_reference_ids(["PMID:1", "PMID:12", "DOI:10.1/x"], [d / "a.yaml"]))
        ['DOI:10.1/x', 'PMID:12']
    """
    # A plain substring test is much faster than a regex over large corpora,
    # so it screens each file and the boundary regex only confirms the hits.
    remaining = {i.lower(): i for i in reference_ids}
    found: set[str] = set()
    for path in paths:
        if not remaining:
            break
        text = path.read_text(encoding="utf-8").lower()
        for key in [k for k in remaining if k in text]:
            if re.search(r"(?<![\w./-])" + re.escape(key) + r"(?![\w/-])", text):
                found.add(remaining.pop(key))
    return found


def _expand_globs(patterns: Iterable[str], base_dir: Path) -> list[Path]:
    """Expand glob patterns relative to ``base_dir`` into existing files."""
    paths: list[Path] = []
    for pattern in patterns:
        paths.extend(p for p in sorted(base_dir.glob(pattern)) if p.is_file())
    return paths


def _bundle_files(directory: Path) -> list[Path]:
    """List bundle files (YAML) directly inside ``directory``."""
    return sorted(
        p for p in directory.iterdir() if p.is_file() and p.suffix in BUNDLE_SUFFIXES
    )


def select_bundles(
    source_dir: Path,
    target_repo: Optional[str] = None,
    referenced_in: Iterable[str] = (),
    base_dir: Path = Path("."),
) -> list[Path]:
    """Select the bundle files in ``source_dir`` that a downstream repo needs.

    With neither ``target_repo`` nor ``referenced_in`` every bundle is selected.
    Otherwise a bundle is selected if it is tagged for ``target_repo`` OR its
    ``reference_id`` is cited in a file matching one of the ``referenced_in``
    globs (relative to ``base_dir``).
    """
    files = _bundle_files(source_dir)
    patterns = list(referenced_in)
    if target_repo is None and not patterns:
        return files

    yaml = YAML(typ="safe")
    bundles = {f: yaml.load(f.read_text(encoding="utf-8")) or {} for f in files}
    cited = find_cited_reference_ids(
        (str(b["reference_id"]) for b in bundles.values() if b.get("reference_id")),
        _expand_globs(patterns, base_dir),
    )
    return [
        f
        for f, bundle in bundles.items()
        if (target_repo is not None and is_tagged_for(bundle, target_repo))
        or str(bundle.get("reference_id")) in cited
    ]


def sync_signed_excerpts(
    source_dir: Path,
    dest_dir: Path,
    target_repo: Optional[str] = None,
    referenced_in: Iterable[str] = (),
    prune: bool = False,
    dry_run: bool = False,
    base_dir: Path = Path("."),
) -> SyncReport:
    """Copy selected bundles verbatim from ``source_dir`` into ``dest_dir``.

    Files are copied byte-for-byte so the public copy is exactly what the
    private store verified. With ``prune`` bundles in ``dest_dir`` that are no
    longer selected are deleted; other files (e.g. a README) are left alone.
    With ``dry_run`` nothing is written and the report describes what would
    change.

    Raises:
        FileNotFoundError: if ``source_dir`` is not a directory (for example
            the private store has not been cloned).
    """
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Signed excerpts source not found: {source_dir}")

    report = SyncReport()
    selected = select_bundles(source_dir, target_repo, referenced_in, base_dir)
    if not dry_run:
        dest_dir.mkdir(parents=True, exist_ok=True)

    for src in selected:
        dest = dest_dir / src.name
        content = src.read_bytes()
        if not dest.exists():
            report.added.append(src.name)
        elif dest.read_bytes() != content:
            report.updated.append(src.name)
        else:
            report.unchanged.append(src.name)
            continue
        if not dry_run:
            dest.write_bytes(content)

    if prune and dest_dir.is_dir():
        selected_names = {src.name for src in selected}
        for stale in _bundle_files(dest_dir):
            if stale.name not in selected_names:
                report.removed.append(stale.name)
                if not dry_run:
                    stale.unlink()

    return report
