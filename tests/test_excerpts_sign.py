"""``excerpts sign``: emit snippet-only bundles verified against local full text (#174)."""

import hashlib

import pytest
from ruamel.yaml import YAML
from typer.testing import CliRunner

from linkml_reference_validator import __version__
from linkml_reference_validator.cli import app
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.excerpt_signing import sign_excerpts
from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)

DOI = "DOI:10.1016/j.ajodo.2025.11.017"
STEM = "DOI_10.1016_j.ajodo.2025.11.017"
TITLE = "A removable activator for Class II correction"
QUOTE = "The T-appliance is a removable activator supported by both the maxilla and the mandible."
QUOTE2 = "It was worn full time ... for nine months"
BAD = "The appliance was fixed to the teeth with cement."
BODY = f"# {TITLE}\n\nIntroduction.\n\n{QUOTE} It was worn full time by all patients for nine months.\n"
TODAY = "2026-11-17"


def evidence_yaml(*snippets: str, reference: str = DOI) -> str:
    """A data file with one evidence item per snippet."""
    items = "".join(
        f"  - reference: {reference}\n    supporting_text: \"{s}\"\n" for s in snippets
    )
    return f"id: X:1\nevidence:\n{items}"


@pytest.fixture
def config(tmp_path):
    """A config with a metadata-only cached DOI mapped to a local full text."""
    base = tmp_path / "repo"
    (base / "papers").mkdir(parents=True)
    (base / "papers" / "ajodo.md").write_text(BODY, encoding="utf-8")
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        private_cache_dir=tmp_path / "private",
        reference_base_dir=base,
        signed_excerpts_dir=base / "signed_excerpts",
        fetch_full_text=False,
        local_full_text={DOI: "papers/ajodo.md"},
    )
    ReferenceFetcher(config)._save_to_disk(
        ReferenceContent(
            reference_id=DOI,
            title=TITLE,
            content=None,
            content_type="unavailable",
            full_text_attempted=True,
        )
    )
    return config


@pytest.fixture
def data_file(config):
    """A data file quoting the DOI twice."""
    path = config.reference_base_dir / "kb.yaml"
    path.write_text(evidence_yaml(QUOTE, QUOTE2), encoding="utf-8")
    return path


def load_bundle(config):
    """The bundle written for ``DOI``."""
    return YAML(typ="safe").load(config.signed_excerpts_dir / f"{STEM}.yaml")


def test_sign_writes_only_the_snippets(config, data_file):
    report = sign_excerpts([data_file], config, today=TODAY)
    assert report.written == [f"{STEM}.yaml"]
    assert not report.failures
    bundle = load_bundle(config)
    assert bundle["reference_id"] == DOI
    assert bundle["title"] == TITLE
    assert [e["text"] for e in bundle["excerpts"]] == sorted([QUOTE, QUOTE2])
    raw = (config.signed_excerpts_dir / f"{STEM}.yaml").read_text(encoding="utf-8")
    assert "Introduction" not in raw
    assert "by all patients" not in raw
    assert str(config.reference_base_dir) not in raw


def test_sign_records_verification(config, data_file):
    sign_excerpts([data_file], config, today=TODAY)
    bundle = load_bundle(config)
    sha = hashlib.sha256(BODY.encode("utf-8")).hexdigest()
    for excerpt in bundle["excerpts"]:
        assert excerpt["verification"] == {
            "method": "local_full_text",
            "source_sha256": sha,
            "validator_version": __version__,
            "verified_at": TODAY,
        }
    assert bundle["source_char_count"] == len("".join(BODY.split()))


def test_signed_bundle_validates_without_the_file(config, data_file):
    sign_excerpts([data_file], config, today=TODAY)
    ci = config.model_copy(update={"local_full_text": {}})
    validator = SupportingTextValidator(ci)
    for quote in (QUOTE, QUOTE2):
        result = validator.validate(quote, DOI)
        assert result.is_valid, result.message
        assert result.match_result.match_location == "signed_excerpts"


def test_unverified_snippet_is_reported_and_not_signed(config):
    data = config.reference_base_dir / "kb.yaml"
    data.write_text(evidence_yaml(QUOTE, BAD), encoding="utf-8")
    report = sign_excerpts([data], config, today=TODAY)
    assert [(f.reference_id, f.text) for f in report.failures] == [(DOI, BAD)]
    assert [e["text"] for e in load_bundle(config)["excerpts"]] == [QUOTE]


def test_sign_excerpts_falls_back_to_private_cache_dir(tmp_path):
    """excerpts sign can verify against private_cache_dir written by cache enrich."""
    base = tmp_path / "repo"
    base.mkdir()
    cfg = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        private_cache_dir=tmp_path / "private",
        reference_base_dir=base,
        signed_excerpts_dir=base / "signed_excerpts",
        fetch_full_text=False,
    )
    fetcher = ReferenceFetcher(cfg)
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=DOI,
            title=TITLE,
            content="Only the abstract.",
            content_type="abstract_only",
            full_text_attempted=True,
        )
    )
    fetcher._save_to_disk(
        ReferenceContent(
            reference_id=DOI,
            title=TITLE,
            content=f"Only the abstract.\n\n{QUOTE}",
            content_type="full_text_pdf",
            full_text_provider="zotero",
            full_text_access_type="user_library",
            full_text_attempted=True,
        ),
        private=True,
    )
    # Normal validation before signing must NOT read private_cache_dir
    assert not SupportingTextValidator(cfg).validate(QUOTE, DOI).is_valid

    data = base / "kb.yaml"
    data.write_text(evidence_yaml(QUOTE), encoding="utf-8")
    report = sign_excerpts([data], cfg, today=TODAY)
    assert report.written == [f"{STEM}.yaml"]
    assert not report.failures

    # After signing, normal validation succeeds via signed_excerpts_dir
    res = SupportingTextValidator(cfg).validate(QUOTE, DOI)
    assert res.is_valid
    assert res.match_result.match_location == "signed_excerpts"

    # Without signed_excerpts_dir, normal validation still ignores private_cache_dir
    cfg_no_bundles = cfg.model_copy(update={"signed_excerpts_dir": None})
    assert not SupportingTextValidator(cfg_no_bundles).validate(QUOTE, DOI).is_valid

    # Even when local_full_text_dir is set to another directory, sign_excerpts
    # still falls back to private_cache_dir for references not in local_full_text_dir
    curated_dir = base / "curated"
    curated_dir.mkdir()
    cfg_both = cfg.model_copy(
        update={
            "local_full_text_dir": curated_dir,
            "signed_excerpts_dir": base / "signed_excerpts_both",
        }
    )
    report_both = sign_excerpts([data], cfg_both, today=TODAY)
    assert report_both.written == [f"{STEM}.yaml"]
    assert not report_both.failures




def test_existing_bundle_does_not_vouch_for_a_snippet(config):
    """A hand-typed bundle entry must not let signing re-sign the same text."""
    config.signed_excerpts_dir.mkdir()
    (config.signed_excerpts_dir / f"{STEM}.yaml").write_text(
        f"reference_id: {DOI}\nexcerpts:\n- text: {BAD}\n", encoding="utf-8"
    )
    data = config.reference_base_dir / "kb.yaml"
    data.write_text(evidence_yaml(BAD), encoding="utf-8")
    report = sign_excerpts([data], config, today=TODAY)
    assert [f.text for f in report.failures] == [BAD]
    assert "verification" not in load_bundle(config)["excerpts"][0]


def test_resigning_is_idempotent(config, data_file):
    sign_excerpts([data_file], config, today=TODAY)
    before = (config.signed_excerpts_dir / f"{STEM}.yaml").read_bytes()
    report = sign_excerpts([data_file], config, today="2027-01-01")
    assert report.written == []
    assert report.unchanged == [f"{STEM}.yaml"]
    assert (config.signed_excerpts_dir / f"{STEM}.yaml").read_bytes() == before


def test_merge_keeps_existing_excerpts_and_fields(config, data_file):
    config.signed_excerpts_dir.mkdir()
    (config.signed_excerpts_dir / f"{STEM}.yaml").write_text(
        f"reference_id: {DOI}\n"
        "excerpts:\n"
        "- text: An excerpt verified elsewhere.\n"
        "  target_repo:\n"
        "  - dismech:kb/disorders/A.yaml\n",
        encoding="utf-8",
    )
    sign_excerpts([data_file], config, today=TODAY)
    excerpts = load_bundle(config)["excerpts"]
    assert excerpts[0] == {
        "text": "An excerpt verified elsewhere.",
        "target_repo": ["dismech:kb/disorders/A.yaml"],
    }
    assert [e["text"] for e in excerpts[1:]] == sorted([QUOTE, QUOTE2])


def test_changed_source_reverifies(config, data_file):
    sign_excerpts([data_file], config, today=TODAY)
    paper = config.reference_base_dir / "papers" / "ajodo.md"
    paper.write_text(BODY + "\nAppendix.\n", encoding="utf-8")
    report = sign_excerpts([data_file], config, today="2027-01-01")
    assert report.written == [f"{STEM}.yaml"]
    for excerpt in load_bundle(config)["excerpts"]:
        assert excerpt["verification"]["verified_at"] == "2027-01-01"


def test_dry_run_writes_nothing(config, data_file):
    report = sign_excerpts([data_file], config, today=TODAY, dry_run=True)
    assert report.written == [f"{STEM}.yaml"]
    assert not config.signed_excerpts_dir.exists()


def test_reference_without_local_text_is_skipped(config):
    data = config.reference_base_dir / "kb.yaml"
    data.write_text(evidence_yaml(QUOTE, reference="PMID:999"), encoding="utf-8")
    report = sign_excerpts([data], config, today=TODAY)
    assert report.written == []
    assert report.no_local_text == []


def test_requested_reference_without_local_text_is_reported(config, data_file):
    report = sign_excerpts([data_file], config, references=["PMID:999"], today=TODAY)
    assert report.no_local_text == ["PMID:999"]


def test_reference_filter(config):
    data = config.reference_base_dir / "kb.yaml"
    data.write_text(
        evidence_yaml(QUOTE) + "  - reference: PMID:999\n    supporting_text: other\n",
        encoding="utf-8",
    )
    report = sign_excerpts([data], config, references=[DOI.lower()], today=TODAY)
    assert report.written == [f"{STEM}.yaml"]


def test_sign_enforces_fair_use_caps(config, data_file):
    config.max_excerpt_length = 40
    report = sign_excerpts([data_file], config, today=TODAY)
    assert [f.text for f in report.failures] == [QUOTE]
    assert "max_excerpt_length" in report.failures[0].message
    assert [e["text"] for e in load_bundle(config)["excerpts"]] == [QUOTE2]


# ---------------------------------------------------------------------------
# Strict mode: only excerpts carrying a verification record count
# ---------------------------------------------------------------------------


def test_strict_mode_ignores_unverified_bundle_entries(config):
    config.signed_excerpts_dir.mkdir()
    (config.signed_excerpts_dir / f"{STEM}.yaml").write_text(
        f"reference_id: {DOI}\nexcerpts:\n- text: {BAD}\n", encoding="utf-8"
    )
    ci = config.model_copy(update={"local_full_text": {}})
    assert SupportingTextValidator(ci).validate(BAD, DOI).is_valid
    strict = ci.model_copy(update={"signed_excerpts_require_verification": True})
    assert not SupportingTextValidator(strict).validate(BAD, DOI).is_valid


def test_strict_mode_accepts_signed_entries(config, data_file):
    sign_excerpts([data_file], config, today=TODAY)
    strict = config.model_copy(
        update={"local_full_text": {}, "signed_excerpts_require_verification": True}
    )
    assert SupportingTextValidator(strict).validate(QUOTE, DOI).is_valid


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def write_config(config, path):
    """Write ``config``'s relevant settings as a config file."""
    path.write_text(
        "validation:\n"
        f"  cache_dir: {config.cache_dir}\n"
        f"  private_cache_dir: {config.private_cache_dir}\n"
        f"  reference_base_dir: {config.reference_base_dir}\n"
        f"  signed_excerpts_dir: {config.signed_excerpts_dir}\n"
        "  fetch_full_text: false\n"
        "  local_full_text:\n"
        f"    {DOI}: papers/ajodo.md\n",
        encoding="utf-8",
    )
    return path


def test_cli_sign_and_check(config, data_file, tmp_path):
    cfg = write_config(config, tmp_path / "lrv.yaml")
    runner = CliRunner()
    check = runner.invoke(app, ["excerpts", "sign", str(data_file), "--config", str(cfg), "--check"])
    assert check.exit_code == 1, check.output
    assert not config.signed_excerpts_dir.exists()

    result = runner.invoke(app, ["excerpts", "sign", str(data_file), "--config", str(cfg)])
    assert result.exit_code == 0, result.output
    assert f"{STEM}.yaml" in result.output
    assert (config.signed_excerpts_dir / f"{STEM}.yaml").is_file()

    check = runner.invoke(app, ["excerpts", "sign", str(data_file), "--config", str(cfg), "--check"])
    assert check.exit_code == 0, check.output


def test_cli_sign_fails_on_unverified_snippet(config, tmp_path):
    cfg = write_config(config, tmp_path / "lrv.yaml")
    data = config.reference_base_dir / "kb.yaml"
    data.write_text(evidence_yaml(QUOTE, BAD), encoding="utf-8")
    result = CliRunner().invoke(app, ["excerpts", "sign", str(data), "--config", str(cfg)])
    assert result.exit_code == 1
    assert BAD in result.output
    assert (config.signed_excerpts_dir / f"{STEM}.yaml").is_file()


def test_cli_sign_needs_a_destination(config, data_file, tmp_path):
    cfg = tmp_path / "lrv.yaml"
    cfg.write_text("validation:\n  fetch_full_text: false\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["excerpts", "sign", str(data_file), "--config", str(cfg)])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Review follow-ups (#176)
# ---------------------------------------------------------------------------


def test_bundle_for_another_reference_is_not_merged_into(config, data_file):
    """A file at the usual name that records a different reference is left alone."""
    from linkml_reference_validator.cache import disambiguated_cache_filename

    config.signed_excerpts_dir.mkdir()
    other = config.signed_excerpts_dir / f"{STEM}.yaml"
    other.write_text(
        "reference_id: DOI:10.1016/j_ajodo.2025.11.017\nexcerpts:\n- text: Other.\n",
        encoding="utf-8",
    )
    before = other.read_bytes()
    report = sign_excerpts([data_file], config, today=TODAY)
    assert other.read_bytes() == before
    name = disambiguated_cache_filename(DOI).replace(".md", ".yaml")
    assert report.written == [name]
    ci = config.model_copy(update={"local_full_text": {}})
    result = SupportingTextValidator(ci).validate(QUOTE, DOI)
    assert result.is_valid, result.message


def test_sign_refuses_a_bundle_over_the_cumulative_cap(config, data_file):
    """Quotes kept from earlier runs count toward the cap CI will apply."""
    config.signed_excerpts_dir.mkdir()
    (config.signed_excerpts_dir / f"{STEM}.yaml").write_text(
        f"reference_id: {DOI}\nexcerpts:\n- text: {'x' * 60}\n", encoding="utf-8"
    )
    config.max_total_chars_per_reference = 120
    report = sign_excerpts([data_file], config, today=TODAY)
    assert report.written == []
    assert [f.reference_id for f in report.failures] == [DOI]
    assert "max_total_chars_per_reference" in report.failures[0].message


def test_sign_refuses_a_bundle_over_the_fraction_cap(config, data_file):
    config.max_reference_fraction = 0.7  # 120 of 172; this run's quotes are 105
    config.signed_excerpts_dir.mkdir()
    (config.signed_excerpts_dir / f"{STEM}.yaml").write_text(
        f"reference_id: {DOI}\nexcerpts:\n- text: {'x' * 60}\n", encoding="utf-8"
    )
    report = sign_excerpts([data_file], config, today=TODAY)
    assert report.written == []
    assert "max_reference_fraction" in report.failures[0].message


def test_prune_drops_locally_signed_excerpts_no_longer_cited(config, data_file):
    sign_excerpts([data_file], config, today=TODAY)
    bundle = config.signed_excerpts_dir / f"{STEM}.yaml"
    bundle.write_text(
        bundle.read_text(encoding="utf-8")
        + "- text: Verified elsewhere.\n  target_repo: dismech\n",
        encoding="utf-8",
    )
    data_file.write_text(evidence_yaml(QUOTE), encoding="utf-8")
    kept = sign_excerpts([data_file], config, today=TODAY)
    assert kept.unchanged == [f"{STEM}.yaml"]
    report = sign_excerpts([data_file], config, today=TODAY, prune=True)
    assert report.written == [f"{STEM}.yaml"]
    texts = [e["text"] for e in load_bundle(config)["excerpts"]]
    assert texts == [QUOTE, "Verified elsewhere."]


def test_source_edited_mid_run_is_not_signed(config, data_file, monkeypatch):
    """The recorded hash must be of the text the quotes were checked against."""
    paper = config.reference_base_dir / "papers" / "ajodo.md"
    original = SupportingTextValidator.validate

    def validate_then_edit(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        paper.write_text(BODY + "\nEdited.\n", encoding="utf-8")
        return result

    monkeypatch.setattr(SupportingTextValidator, "validate", validate_then_edit)
    report = sign_excerpts([data_file], config, today=TODAY)
    assert report.written == []
    assert "changed while" in report.failures[0].message


# ---------------------------------------------------------------------------
# Second review follow-ups (#176)
# ---------------------------------------------------------------------------


def test_prune_does_not_touch_a_reference_with_failures(config, data_file):
    """A wrong local file must not wipe excerpts signed against the right one."""
    sign_excerpts([data_file], config, today=TODAY)
    before = (config.signed_excerpts_dir / f"{STEM}.yaml").read_bytes()
    (config.reference_base_dir / "papers" / "ajodo.md").write_text(
        "# Preprint\n\nDifferent wording entirely.\n", encoding="utf-8"
    )
    report = sign_excerpts([data_file], config, today=TODAY, prune=True)
    assert len(report.failures) == 2
    assert (config.signed_excerpts_dir / f"{STEM}.yaml").read_bytes() == before


def test_prune_visits_bundles_for_references_no_longer_cited(config, data_file):
    sign_excerpts([data_file], config, today=TODAY)
    data_file.write_text(evidence_yaml("other", reference="PMID:999"), encoding="utf-8")
    report = sign_excerpts([data_file], config, today=TODAY, prune=True)
    assert report.written == [f"{STEM}.yaml"]
    assert load_bundle(config)["excerpts"] == []


def test_prune_leaves_uncited_bundles_from_elsewhere_alone(config, data_file):
    config.signed_excerpts_dir.mkdir()
    other = config.signed_excerpts_dir / "PMID_5.yaml"
    other.write_text("reference_id: PMID:5\nexcerpts:\n- text: From a store.\n", encoding="utf-8")
    before = other.read_bytes()
    sign_excerpts([data_file], config, today=TODAY, prune=True)
    assert other.read_bytes() == before


def test_check_reports_an_unchanged_bundle_over_the_cap(config, data_file):
    sign_excerpts([data_file], config, today=TODAY)
    config.max_total_chars_per_reference = 50
    report = sign_excerpts([data_file], config, today=TODAY, dry_run=True)
    assert any("max_total_chars_per_reference" in f.message for f in report.failures)
    assert any("--prune" in f.message for f in report.failures)


def test_bundle_with_a_non_normalized_reference_id_is_reused(config, data_file):
    config.signed_excerpts_dir.mkdir()
    bundle = config.signed_excerpts_dir / f"{STEM}.yaml"
    bundle.write_text(
        "reference_id: doi:10.1016/J.AJODO.2025.11.017\nexcerpts:\n- text: Kept.\n",
        encoding="utf-8",
    )
    report = sign_excerpts([data_file], config, today=TODAY)
    assert report.written == [f"{STEM}.yaml"]
    assert [p.name for p in config.signed_excerpts_dir.iterdir()] == [f"{STEM}.yaml"]
    assert load_bundle(config)["excerpts"][0]["text"] == "Kept."


def test_both_bundle_names_taken_by_other_references_is_a_failure(config, data_file):
    from linkml_reference_validator.cache import disambiguated_cache_filename

    config.signed_excerpts_dir.mkdir()
    for name, ref in [
        (f"{STEM}.yaml", "DOI:10.1016/j_ajodo.2025.11.017"),
        (disambiguated_cache_filename(DOI).replace(".md", ".yaml"), "DOI:10.9/other"),
    ]:
        (config.signed_excerpts_dir / name).write_text(
            f"reference_id: {ref}\nexcerpts:\n- text: x\n", encoding="utf-8"
        )
    report = sign_excerpts([data_file], config, today=TODAY)
    assert report.written == []
    assert any("another reference" in f.message for f in report.failures)


def test_prune_skips_bundles_validation_would_not_read(config, data_file):
    """A hand-named bundle, or the .yml twin of a .yaml, is not rewritten elsewhere."""
    config.signed_excerpts_dir.mkdir()
    odd = config.signed_excerpts_dir / "smith2020.yaml"
    odd.write_text(
        "reference_id: PMID:5\nexcerpts:\n- text: x\n  verification:\n"
        "    method: local_full_text\n    source_sha256: ab\n",
        encoding="utf-8",
    )
    twin = config.signed_excerpts_dir / "PMID_6.yml"
    twin.write_text("reference_id: PMID:6\nexcerpts: []\n", encoding="utf-8")
    (config.signed_excerpts_dir / "PMID_6.yaml").write_text(
        "reference_id: PMID:6\nexcerpts: []\n", encoding="utf-8"
    )
    report = sign_excerpts([data_file], config, today=TODAY, prune=True)
    names = sorted(p.name for p in config.signed_excerpts_dir.iterdir())
    assert names == sorted([f"{STEM}.yaml", "PMID_6.yaml", "PMID_6.yml", "smith2020.yaml"])
    assert "PMID_5.yaml" not in report.written
    assert report.unchanged.count("PMID_6.yaml") == 1


def test_prune_of_a_mixed_uncited_bundle_keeps_entries_from_elsewhere(config, data_file):
    config.signed_excerpts_dir.mkdir()
    mixed = config.signed_excerpts_dir / "PMID_7.yaml"
    mixed.write_text(
        "reference_id: PMID:7\nexcerpts:\n- text: From a store.\n- text: Signed here.\n"
        "  verification:\n    method: local_full_text\n    source_sha256: ab\n",
        encoding="utf-8",
    )
    report = sign_excerpts([data_file], config, today=TODAY, prune=True)
    assert "PMID_7.yaml" in report.written
    assert YAML(typ="safe").load(mixed)["excerpts"] == [{"text": "From a store."}]


def test_prune_reports_a_malformed_bundle_instead_of_crashing(config, data_file):
    config.signed_excerpts_dir.mkdir()
    (config.signed_excerpts_dir / "broken.yaml").write_text("a: [unclosed\n", encoding="utf-8")
    report = sign_excerpts([data_file], config, today=TODAY, prune=True)
    assert f"{STEM}.yaml" in report.written
    assert any("broken.yaml" in f.message for f in report.failures)


def test_prune_does_not_add_an_empty_excerpt_list(config, data_file):
    config.signed_excerpts_dir.mkdir()
    bare = config.signed_excerpts_dir / "PMID_8.yaml"
    bare.write_text("reference_id: PMID:8\ntitle: No excerpts yet\n", encoding="utf-8")
    before = bare.read_bytes()
    report = sign_excerpts([data_file], config, today=TODAY, prune=True)
    assert "PMID_8.yaml" not in report.written
    assert bare.read_bytes() == before


@pytest.mark.parametrize(
    "name,content",
    [
        (f"{STEM}.yaml", b"- text: a list, not a mapping\n"),
        ("PMID_9.yaml", b"reference_id: PMID:9\ntitle: caf\xe9\n"),
        ("PMID_9.yml", b"a: [unclosed\n"),
    ],
)
def test_unreadable_bundles_are_reported_not_raised(config, data_file, name, content):
    config.signed_excerpts_dir.mkdir()
    if name == "PMID_9.yml":
        (config.signed_excerpts_dir / "PMID_9.yaml").write_text(
            "reference_id: PMID:9\nexcerpts: []\n", encoding="utf-8"
        )
    (config.signed_excerpts_dir / name).write_bytes(content)
    report = sign_excerpts([data_file], config, today=TODAY, prune=True)
    assert any(name in f.message for f in report.failures), report.failures
