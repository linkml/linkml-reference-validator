"""NCBI Bookshelf full-text provider (GeneReviews and other books, #41).

A PMID for a Bookshelf chapter has no PMC copy, so the PMC provider finds
nothing and the reference would keep only its PubMed summary. The chapter pages
themselves are no way in: ``books/NBK.../?report=printable`` answers a script
with a reCAPTCHA interstitial on an HTTP 200, the same trap PMC sets.

NCBI's machine-retrieval route is the litarch archive
(https://ftp.ncbi.nlm.nih.gov/pub/litarch/), one tarball per book holding a
BITS XML file per chapter. :func:`download_book` unpacks a book's chapters into
``bookshelf_archive_dir`` once; the provider then reads the chapter the PubMed
record names, offline. The archive is the litarch open-access subset, and a
chapter is used only when its own ``<license>`` says ``open-access``.
"""

import csv
import io
import logging
import re
import shutil
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Optional

import requests  # type: ignore

from linkml_reference_validator.etl.extract import MIN_FULLTEXT_CHARS
from linkml_reference_validator.etl.extract.xml import XMLExtractor
from linkml_reference_validator.etl.fulltext.base import (
    FullTextProvider,
    FullTextProviderRegistry,
)
from linkml_reference_validator.models import (
    FullTextLocation,
    ReferenceIdentifiers,
    ReferenceValidationConfig,
)

logger = logging.getLogger(__name__)

LITARCH_URL = "https://ftp.ncbi.nlm.nih.gov/pub/litarch"

# Book and part names as litarch spells them ("gene", "men1", "glutaric-a1").
# Anything else is refused before it becomes part of a path.
_SLUG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_LICENCE_TYPE = re.compile(r"<license\b[^>]*\blicense-type=\"([^\"]*)\"")
_ACCESSION = re.compile(r"^NBK\d+$")


def split_part(part: Optional[str]) -> Optional[tuple[str, str]]:
    """Split ``"<book>/<part>"`` into its two names, or None if malformed.

    Examples:
        >>> split_part("gene/men1")
        ('gene', 'men1')
        >>> split_part("gene/../etc") is None
        True
        >>> split_part("gene") is None
        True
    """
    pieces = (part or "").split("/")
    if len(pieces) != 2 or not all(_SLUG.match(p) for p in pieces):
        return None
    if any(p in (".", "..") for p in pieces):
        return None
    return pieces[0], pieces[1]


@FullTextProviderRegistry.register
class BookshelfFullTextProvider(FullTextProvider):
    """Read a Bookshelf chapter's full text from the local litarch archive.

    Examples:
        >>> BookshelfFullTextProvider.name()
        'bookshelf'
    """

    @classmethod
    def name(cls) -> str:
        return "bookshelf"

    def locate(
        self, ids: ReferenceIdentifiers, config: ReferenceValidationConfig
    ) -> Optional[FullTextLocation]:
        names = split_part(ids.bookshelf_part)
        if names is None:
            return None
        book, part = names

        # Each miss below is a decline, not an absence: the chapter exists and
        # is open, this machine just cannot read it yet. Recording absence would
        # stop the chain from ever looking again once the archive is in place.
        archive = config.bookshelf_archive_dir
        if archive is None:
            logger.info(
                "%s is a Bookshelf chapter (%s); set bookshelf_archive_dir and run "
                "'linkml-reference-validator cache bookshelf-download' for its full text",
                ids.pmid, ids.bookshelf_accession,
            )
            return FullTextLocation(
                provider="bookshelf", declined="bookshelf_archive_not_configured"
            )

        book_dirs = sorted(Path(archive).expanduser().glob(f"{book}_NBK*"))
        if not book_dirs:
            return FullTextLocation(
                provider="bookshelf", declined=f"bookshelf_book_not_in_archive:{book}"
            )
        # One folder per book; sorted only so the answer never depends on
        # directory order should a stray second copy exist.
        chapter = book_dirs[0] / f"{part}.nxml"
        if not chapter.is_file():
            return FullTextLocation(
                provider="bookshelf",
                declined=f"bookshelf_chapter_not_in_archive:{book}/{part}",
            )

        data = chapter.read_bytes()
        licence = _LICENCE_TYPE.search(data.decode("utf-8", errors="replace"))
        licence_type = licence.group(1) if licence else "none"
        if licence_type != "open-access":
            return FullTextLocation(
                provider="bookshelf", declined=f"bookshelf_licence:{licence_type}"
            )

        text = XMLExtractor().extract(data, content_type="application/xml")
        if not text or len(text) <= MIN_FULLTEXT_CHARS:
            return None
        return FullTextLocation(
            text=text,
            format_hint="xml",
            provider="bookshelf",
            # The citable public page, kept as provenance; text comes from disk.
            url=(
                f"https://www.ncbi.nlm.nih.gov/books/{ids.bookshelf_accession}/"
                if ids.bookshelf_accession
                else None
            ),
            license=licence_type,
        )


def download_book(
    accession: str,
    archive_dir: Path,
    config: ReferenceValidationConfig,
    mirror: str = LITARCH_URL,
) -> Path:
    """Download one litarch book and unpack its chapter XML into ``archive_dir``.

    Only ``*.nxml`` members are kept -- figures and PDFs are most of a tarball
    and none of the text -- and only those that stay inside the book's folder.
    The book is unpacked beside its final place and swapped in at the end, so
    an interrupted download leaves the previous copy, if any, as it was.

    Args:
        accession: The book's NBK accession, e.g. ``NBK1116`` for GeneReviews
        archive_dir: The ``bookshelf_archive_dir`` to unpack into
        config: For the contact email and rate limiting
        mirror: Base URL of litarch; the default is NCBI's

    Returns:
        The book's folder, e.g. ``archive_dir / "gene_NBK1116"``

    Raises:
        ValueError: ``accession`` is not a book in litarch's file list.
        requests.HTTPError: The mirror refused a download.
    """
    if not _ACCESSION.match(accession):
        raise ValueError(f"Not an NBK accession: {accession!r}")
    headers = {"User-Agent": f"linkml-reference-validator/1.0 (mailto:{config.email})"}

    time.sleep(config.rate_limit_delay)
    listing = requests.get(f"{mirror}/file_list.csv", headers=headers, timeout=60)
    listing.raise_for_status()
    rows = csv.DictReader(io.StringIO(listing.text))
    remote = next(
        (row["File"] for row in rows if row.get("Accession ID") == accession), None
    )
    if remote is None:
        raise ValueError(f"{accession} is not in litarch's file list")

    book_name = PurePosixPath(remote).name.removesuffix(".tar.gz")
    if not _SLUG.match(book_name):
        raise ValueError(f"Unexpected litarch file name: {remote!r}")
    archive_dir = Path(archive_dir).expanduser()
    archive_dir.mkdir(parents=True, exist_ok=True)
    final = archive_dir / book_name
    staging = archive_dir / f".{book_name}.partial"
    shutil.rmtree(staging, ignore_errors=True)

    chapters = 0
    time.sleep(config.rate_limit_delay)
    with requests.get(
        f"{mirror}/{remote}", headers=headers, timeout=60, stream=True
    ) as response:
        response.raise_for_status()
        response.raw.decode_content = True
        # "r|gz" reads the tarball as a stream: GeneReviews is 640 MB, and
        # nothing but the chapter XML is ever written to disk.
        with tarfile.open(fileobj=response.raw, mode="r|gz") as tar:
            for member in tar:
                path = PurePosixPath(member.name)
                if (
                    not member.isfile()
                    or path.suffix != ".nxml"
                    or len(path.parts) != 2
                    or path.parts[0] != book_name
                    or not _SLUG.match(path.name)
                ):
                    continue
                source = tar.extractfile(member)
                if source is None:
                    continue
                staging.mkdir(exist_ok=True)
                (staging / path.name).write_bytes(source.read())
                chapters += 1

    if not chapters:
        shutil.rmtree(staging, ignore_errors=True)
        raise ValueError(f"{remote} held no chapter XML")
    shutil.rmtree(final, ignore_errors=True)
    staging.rename(final)
    logger.info("Unpacked %s chapters of %s into %s", chapters, accession, final)
    return final
