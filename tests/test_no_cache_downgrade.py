"""A refresh may improve a cache entry. It may never demote one.

The extractor-version stamp introduced in #62 makes every pre-stamp entry stale,
so the next run re-fetches and rewrites it. That is the intended migration, and
it is safe only while the replacement is at least as good as what it replaces.

It often is not. Full-text retrieval fails transiently and *silently*: PMC
answers a rate-limited request with a reCAPTCHA interstitial carried on an
HTTP 200, so no status code marks it. The bot page is correctly rejected
downstream, the abstract fetch succeeds on its own, and the record is written as
``abstract_only`` — byte-identical to "this article has no full text". Measured
against one real reference, the same fetch returned full text on 2 of 5
consecutive attempts.

``_stale_fallback`` does not cover this. It fires only when the source yields
*nothing*; here the abstract is something, so the fresh record is saved over a
cached one holding thousands of characters of article text, and every excerpt
quoted from that text stops validating.

The guard is deliberately narrow, and narrower than it first was. It refuses one
thing: a refresh that comes back with *no* full text where the cache has some.
It does not compare sizes. An earlier version also refused a refresh whose text
was a fraction of the cached length; that caught one real case -- a cover-page
PDF extraction -- and mis-handled four others, because a shorter extraction is
usually a better one. Those four are pinned below as cases that must migrate.

The preserved entry is not re-saved, so it stays stale and the next run tries
again. A refresh that finds full text still rewrites the entry, which is the
whole point of the migration.

Keeping an entry and serving it are separate decisions. ``_load_from_disk``
refuses to serve stale ``full_text_html`` because it may be a repository landing
page; that refusal still holds, so such an entry is kept on disk *and* withheld
from validation, which falls back to the freshly fetched abstract.
"""

import logging
from unittest.mock import patch

import pytest

from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig

FULL_TEXT_BODY = "Severe cleft palate was found in all homozygous mutants. " * 40
#: ~2,000 characters, the median of the abstract-only entries in a real cache.
REAL_ABSTRACT = "A representative abstract sentence. " * 56
ABSTRACT_BODY = "A short abstract."


def _write_cache(cache_dir, reference_id, content_type, body, stamped=False):
    """Write a cache entry, pre-stamp (stale) by default.

    ``stamped=True`` writes the format-specific stamp as well as
    ``extractor_version``: ``_is_stale_cache_entry`` requires
    ``xml_extraction_version`` on a ``full_text_xml`` entry and
    ``html_full_text_version`` on a ``full_text_html`` one, so the extractor
    stamp alone still reads as stale for those two types.
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    stamp = ""
    if stamped:
        stamp = "extractor_version: 1\n"
        if content_type == "full_text_xml":
            stamp += "xml_extraction_version: 1\n"
        elif content_type == "full_text_html":
            stamp += "html_full_text_version: 1\n"
    path = cache_dir / f"{reference_id.replace(':', '_')}.md"
    path.write_text(
        f"---\nreference_id: {reference_id}\n{stamp}"
        f"title: A paper\ncontent_type: {content_type}\n---\n\n## Content\n\n{body}\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def fetcher(tmp_path):
    return ReferenceFetcher(ReferenceValidationConfig(cache_dir=tmp_path, email="me@example.org"))


def _fetch_returning(fetcher, content_type, body):
    """Run ``fetch`` with the source stubbed to return the given content."""
    fresh = ReferenceContent(
        reference_id="PMID:9177246",
        content=body,
        content_type=content_type,
        title="A paper",
    )

    class _Source:
        def fetch(self, identifier, config):
            return fresh

    with patch(
        "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        return fetcher.fetch("PMID:9177246")


@pytest.mark.parametrize(
    "cached_type", ["full_text_html", "full_text_xml", "full_text_pdf"]
)
def test_a_failed_full_text_refresh_keeps_the_cached_file(fetcher, tmp_path, cached_type):
    """The case that loses committed evidence.

    This is the *deletion* claim, and it holds for every full-text type. What
    may then be **served** differs by type and is covered separately below:
    stale HTML is kept but withheld, since it may be a landing page.
    """
    path = _write_cache(tmp_path, "PMID:9177246", cached_type, FULL_TEXT_BODY)

    _fetch_returning(fetcher, "abstract_only", ABSTRACT_BODY)

    assert "Severe cleft palate" in path.read_text(encoding="utf-8"), (
        "a transient full-text failure must not replace cached article text"
    )


def test_the_preserved_entry_stays_stale_so_the_next_run_retries(fetcher, tmp_path):
    """Preserving is not migrating: leave it un-stamped."""
    path = _write_cache(tmp_path, "PMID:9177246", "full_text_html", FULL_TEXT_BODY)

    _fetch_returning(fetcher, "abstract_only", ABSTRACT_BODY)

    assert "extractor_version" not in path.read_text(encoding="utf-8"), (
        "stamping it would end the migration on the worse content"
    )


def test_a_successful_refresh_still_rewrites_the_entry(fetcher, tmp_path):
    """The migration must still work when the replacement is good."""
    _write_cache(tmp_path, "PMID:9177246", "full_text_html", "old text " * 50)

    result = _fetch_returning(fetcher, "full_text_xml", "NEW BODY " * 50)

    assert "NEW BODY" in (result.content or "")
    assert result.content_type == "full_text_xml"


def test_an_upgrade_from_abstract_to_full_text_is_allowed(fetcher, tmp_path):
    _write_cache(tmp_path, "PMID:9177246", "abstract_only", ABSTRACT_BODY)

    result = _fetch_returning(fetcher, "full_text_xml", FULL_TEXT_BODY)

    assert result.content_type == "full_text_xml"


def test_an_abstract_refresh_over_an_abstract_entry_is_not_a_downgrade(fetcher, tmp_path):
    """No full text is lost, so nothing is preserved and the entry migrates."""
    _write_cache(tmp_path, "PMID:9177246", "abstract_only", "stale abstract")

    result = _fetch_returning(fetcher, "abstract_only", "fresher abstract")

    assert "fresher abstract" in (result.content or "")


def test_no_cached_entry_means_nothing_to_preserve(fetcher):
    result = _fetch_returning(fetcher, "abstract_only", ABSTRACT_BODY)

    assert result.content_type == "abstract_only"


# --------------------------------------------------------------------------
# Keeping an entry is not the same as serving it
# --------------------------------------------------------------------------


def test_stale_html_is_kept_on_disk_but_not_served_as_evidence(fetcher, tmp_path):
    """The case the guard must not get wrong.

    A pre-fix ``full_text_html`` entry is disproportionately likely to *be* a
    scraped landing page -- that is what this release stops fetching. Keeping
    the curator's file is right; quoting its text back as though it came from
    the article is not. ``_load_from_disk`` already refuses to serve stale HTML,
    and that refusal survives the guard.
    """
    path = _write_cache(tmp_path, "PMID:9177246", "full_text_html", FULL_TEXT_BODY)

    result = _fetch_returning(fetcher, "abstract_only", ABSTRACT_BODY)

    assert "Severe cleft palate" in path.read_text(encoding="utf-8"), (
        "the file must be kept"
    )
    assert "Severe cleft palate" not in (result.content or ""), (
        "possible landing-page text must not be served to validation"
    )
    assert result.content == ABSTRACT_BODY


def test_stale_non_html_full_text_is_both_kept_and_served(fetcher, tmp_path):
    """XML and PDF carry no landing-page risk, so the old text is still usable."""
    path = _write_cache(tmp_path, "PMID:9177246", "full_text_xml", FULL_TEXT_BODY)

    result = _fetch_returning(fetcher, "abstract_only", ABSTRACT_BODY)

    assert "Severe cleft palate" in path.read_text(encoding="utf-8")
    assert "Severe cleft palate" in (result.content or "")


@pytest.mark.parametrize(
    "cached_type", ["full_text_html", "full_text_pdf", "full_text_xml"]
)
def test_a_preserved_entry_reports_served_stale(fetcher, tmp_path, cached_type):
    """``cache reference`` must not claim success when it wrote nothing.

    Its message is "the cache still holds no current entry for it", which is
    true in both branches: the write was skipped either way.
    """
    _write_cache(tmp_path, "PMID:9177246", cached_type, FULL_TEXT_BODY)

    fresh = ReferenceContent(
        reference_id="PMID:9177246", content=ABSTRACT_BODY, content_type="abstract_only"
    )

    class _Source:
        def fetch(self, identifier, config):
            return fresh

    with patch(
        "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        outcome = fetcher.fetch_with_provenance("PMID:9177246")

    assert outcome.served_stale is True


def test_force_refresh_warns_before_discarding_cached_full_text(fetcher, tmp_path, caplog):
    """The opt-out is right; doing it silently is not.

    ``--force`` is what both the ``cache reference`` failure message and the
    troubleshooting docs tell a user to run, and a preserved entry fails every
    run, so the pressure to reach for it is continuous and it will usually be
    run across a batch. Following that advice on the motivating entry replaces
    18,464 characters with a 1,199-character abstract; the caller asked for the
    refresh, so it proceeds, but they should be told what it cost.
    """
    _write_cache(tmp_path, "PMID:9177246", "full_text_html", FULL_TEXT_BODY)

    fresh = ReferenceContent(
        reference_id="PMID:9177246", content=ABSTRACT_BODY, content_type="abstract_only"
    )

    class _Source:
        def fetch(self, identifier, config):
            return fresh

    with caplog.at_level(logging.WARNING):
        with patch(
            "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
            return_value=_Source,
        ):
            fetcher.fetch("PMID:9177246", force_refresh=True)

    assert any(
        "--force is replacing the cached" in record.getMessage()
        for record in caplog.records
    ), "the discard must not be silent"


def test_force_refresh_overrides_the_guard(fetcher, tmp_path):
    """An explicit refresh that finds less is a result the caller asked for."""
    path = _write_cache(tmp_path, "PMID:9177246", "full_text_xml", FULL_TEXT_BODY)

    fresh = ReferenceContent(
        reference_id="PMID:9177246", content=ABSTRACT_BODY, content_type="abstract_only"
    )

    class _Source:
        def fetch(self, identifier, config):
            return fresh

    with patch(
        "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        fetcher.fetch("PMID:9177246", force_refresh=True)

    assert "Severe cleft palate" not in path.read_text(encoding="utf-8")








# --------------------------------------------------------------------------
# A change of type is not a shrink
# --------------------------------------------------------------------------


def test_a_page_scrape_upgrading_to_a_clean_extraction_still_migrates(fetcher, tmp_path):
    """The exact population this release acts on.

    A pre-fix ``full_text_html`` entry holds a whole scraped page -- body,
    reference list, related-article furniture. The refresh goes to PMC XML and
    extracts the article body alone, which is legitimately a fraction of that.
    Refusing it would block the migration permanently: never written, so never
    stamped, so re-fetched and re-refused on every subsequent run, with
    ``cache reference`` exiting 1 each time and no exit but ``--force``.

    That is the bug this guard exists to prevent, with the sign flipped.
    """
    path = _write_cache(
        tmp_path, "PMID:9177246", "full_text_html", "page text with furniture " * 800
    )

    result = _fetch_returning(fetcher, "full_text_xml", "clean article body " * 330)

    assert "clean article body" in (result.content or "")
    assert "clean article body" in path.read_text(encoding="utf-8"), (
        "the better extraction must be written, not refused"
    )










def test_a_plain_text_body_upgrading_to_xml_still_migrates(fetcher, tmp_path):
    """``full_text`` is one of this project's own four content types.

    ``_FORMAT_TO_CONTENT_TYPE`` maps ``format_hint="text"`` to it, and
    ``_materialize`` defaults to that hint, so a configured ``json_api`` text
    provider writes it to the *public* cache. An earlier revision ranked content
    types to decide how strict a size comparison should be, and leaving this one
    out of the ranking gave it the strict bar and so the permanent-block loop:
    not written, not stamped, re-refused every run. The ranking went with the
    comparison; this pins the outcome that mattered, which is that a plain-text
    body still migrates to XML.
    """
    path = _write_cache(
        tmp_path, "PMID:9177246", "full_text", "plain text api body " * 1000
    )

    result = _fetch_returning(fetcher, "full_text_xml", "clean xml body text " * 320)

    assert "clean xml body text" in (result.content or "")
    assert "clean xml body text" in path.read_text(encoding="utf-8")


def test_a_stamped_entry_is_served_from_cache_without_re_fetching(fetcher, tmp_path):
    """The other side of the migration, and the reason ``stamped`` exists.

    Every other test here writes a pre-stamp entry, because the guard only runs
    on a refresh and only a stale entry is refreshed. This pins the complement:
    once an entry carries the current stamp it is served from disk and the
    source is never consulted, so the preserve path cannot fire on it and the
    fetch storm the stale entries cause does not apply to a migrated cache.
    """
    _write_cache(
        tmp_path, "PMID:9177246", "full_text_xml", FULL_TEXT_BODY, stamped=True
    )

    class _Source:
        def fetch(self, identifier, config):  # pragma: no cover - must not run
            raise AssertionError("a stamped entry must not be re-fetched")

    with patch(
        "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
        return_value=_Source,
    ):
        result = fetcher.fetch("PMID:9177246")

    assert "Severe cleft palate" in (result.content or "")













# --------------------------------------------------------------------------
# The page-scrape migration within one rung
# --------------------------------------------------------------------------


def test_a_page_scrape_refreshed_to_a_clean_html_body_still_migrates(fetcher, tmp_path):
    """The same improvement as the cross-type case, and just as reachable.

    ``PMCFullTextProvider`` returns ``format_hint="html"`` whenever its XML path
    falls short, so a pre-fix landing-page scrape can legitimately be replaced by
    a ``div.article-body`` extraction at the *same* content type, and much
    shorter. An earlier revision refused exactly this, permanently, by comparing
    sizes; the guard now asks only whether full text survived at all.
    """
    path = _write_cache(
        tmp_path, "PMID:9177246", "full_text_html", "whole page with furniture " * 800
    )

    result = _fetch_returning(fetcher, "full_text_html", "clean article body " * 300)

    assert "clean article body" in (result.content or "")
    assert "clean article body" in path.read_text(encoding="utf-8")




# --------------------------------------------------------------------------
# What the rule deliberately does not catch
# --------------------------------------------------------------------------


def test_a_cover_page_pdf_is_not_refused_but_is_reported(fetcher, tmp_path, caplog):
    """A recorded gap, not an oversight.

    A PDF whose text layer is a publisher cover sheet is still typed
    ``full_text_pdf``, so this guard lets it through. Catching it needs a
    judgement about whether text *is* an article, which is the acceptance
    layer's question -- ``is_stub_notice`` already asks it for XML, and there a
    wrong answer costs one skipped fetch. Asking it here instead cost four
    rounds of wrongly-refused migrations, each permanent, because a refusal is
    never written and so never stamped.

    Pinned so the gap is visible and deliberate. If PDF stub detection lands in
    the acceptance layer, this test should start failing and be inverted.

    Not refusing is not the same as not mentioning: the write is still recorded,
    so a curator whose quoted evidence stops verifying has a thread to pull.
    """
    path = _write_cache(
        tmp_path, "PMID:9177246", "full_text_html", "clean article body " * 740
    )

    with caplog.at_level(logging.WARNING):
        _fetch_returning(fetcher, "full_text_pdf", "Purchase this article. " * 26)

    assert "clean article body" not in path.read_text(encoding="utf-8"), (
        "the write proceeds -- refusing it is what caused four rounds of "
        "permanently blocked migrations"
    )
    assert any(
        "much shorter" in record.getMessage() for record in caplog.records
    ), "but it is not silent"


def test_a_refused_refresh_does_not_also_claim_it_was_written(fetcher, tmp_path, caplog):
    """The two messages must not contradict each other.

    The shrink report describes a write. On the refused path there is no write,
    so firing it there produced two warnings back to back -- "replaced the
    cached entry ... Written as usual" immediately followed by "keeping the
    cached entry rather than overwriting it". A reader cannot tell which
    happened, which is worse than the silence the report was added to fix.
    """
    _write_cache(tmp_path, "PMID:9177246", "full_text_html", FULL_TEXT_BODY)

    with caplog.at_level(logging.WARNING):
        _fetch_returning(fetcher, "abstract_only", ABSTRACT_BODY)

    messages = [record.getMessage() for record in caplog.records]
    assert any("keeping the cached" in m for m in messages), "the refusal is reported"
    assert not any("Written as usual" in m for m in messages), (
        "and nothing claims the opposite"
    )


def test_the_report_ignores_the_abstract_both_records_carry(fetcher, tmp_path, caplog):
    """Otherwise the report misses the case it exists for, at the size that matters.

    ``_apply_full_text_location`` stores ``abstract + "\n\n" + text``, so a
    cover-page extraction arrives carrying the abstract as well. Comparing whole
    records credits it with that text: a ~2,000-character abstract alone clears a
    fifth of a 10,000-character entry, so the write goes through in silence --
    which is exactly the cover-page case, at exactly the article size where it is
    most likely.
    """
    _write_cache(tmp_path, "PMID:9177246", "full_text_html", "article body text " * 560)
    cover_page = f"{REAL_ABSTRACT}\n\n" + "Purchase this article. " * 26

    with caplog.at_level(logging.WARNING):
        _fetch_returning(fetcher, "full_text_pdf", cover_page)

    assert any(
        "much shorter" in record.getMessage() for record in caplog.records
    ), "the abstract must not pay for the floor"


def test_the_shrink_report_quotes_the_numbers_it_decided_on(fetcher, tmp_path, caplog):
    """A message whose figures do not explain its own verdict is the defect.

    The decision uses abstract-subtracted lengths; rendering whole records
    instead quoted the cached entry at two different sizes in one sentence and
    showed a fresh/cached pair that can read as half. A curator cannot
    reconstruct why "much shorter" fired, and the natural inference -- that the
    threshold is near 50% -- is wrong.
    """
    body = "article body text " * 167  # ~3,000 characters
    _write_cache(tmp_path, "PMID:9177246", "full_text_html", f"{REAL_ABSTRACT}\n\n{body}")
    cover = f"{REAL_ABSTRACT}\n\n" + "Purchase. " * 50  # ~500 characters of text

    with caplog.at_level(logging.WARNING):
        _fetch_returning(fetcher, "full_text_pdf", cover)

    report = next(m for m in (r.getMessage() for r in caplog.records) if "much shorter" in m)
    assert "3005 characters of article text" in report, f"cached body, not record: {report}"
    assert "500 characters of full_text_pdf" in report, f"fresh body, not record: {report}"
    # The whole-record figures (~5,000 and ~2,500) must not appear: quoting them
    # would show a pair that reads as half while the sentence says much shorter.
    assert "5023" not in report and "2518" not in report, report


def test_text_after_abstract_handles_a_record_with_no_abstract(fetcher):
    """``_apply_full_text_location`` writes bare text when there is no abstract.

    The partition then lands on the first paragraph break in the body and drops
    the opening paragraph. It decides a log line either way, so this pins the
    behaviour rather than asserting it is ideal.
    """
    from linkml_reference_validator.etl.reference_fetcher import _text_after_abstract

    assert _text_after_abstract("A body with no blank line") == "A body with no blank line"
    assert _text_after_abstract(None) == ""
