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
