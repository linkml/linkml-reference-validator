"""The repair thresholds decide what is auto-fixed and what is suggested (#127).

``RepairConfig.auto_fix_threshold`` (``--auto-fix-threshold``) and
``suggest_threshold`` were accepted and printed but never read: a fuzzy match
was graded by cutoffs hard-coded at 0.95 and 0.80. Raising the threshold to be
more careful changed nothing, and neither did lowering it. The CLI also always
overwrote a threshold set in the config file with its own default.
"""

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from linkml_reference_validator.cli import app
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
    RepairConfidence,
    RepairConfig,
)
from linkml_reference_validator.validation.repairer import SupportingTextRepairer

runner = CliRunner()

REFERENCE = ReferenceContent(
    reference_id="PMID:1", content="The immune response was strong in all treated mice."
)
#: A one-letter typo: similarity 0.9655, so HIGH under the default 0.95.
CLOSE = "The immune respnse was strong"
#: Two typos: similarity 0.70, so LOW under the default 0.80 suggest threshold.
LOOSER = "Teh immune respnse was strong"


def _repair(quote: str, **thresholds):
    repairer = SupportingTextRepairer(ReferenceValidationConfig(), RepairConfig(**thresholds))
    return repairer.attempt_repair(quote, "PMID:1", REFERENCE)


def test_the_defaults_are_unchanged():
    result = _repair(CLOSE)
    assert result.is_repaired
    assert result.actions[-1].confidence == RepairConfidence.HIGH
    assert result.actions[-1].can_auto_fix


def test_a_higher_auto_fix_threshold_blocks_the_fix_but_still_suggests_it():
    """The issue's reproduction: at 1.0, a 0.966 match is only a suggestion."""
    result = _repair(CLOSE, auto_fix_threshold=1.0)
    action = result.actions[-1]
    assert action.similarity_score == pytest.approx(0.9655, abs=1e-3)
    assert action.confidence == RepairConfidence.MEDIUM
    assert not action.can_auto_fix
    assert not result.is_repaired
    assert result.repaired_text is not None  # still offered as a suggestion


def test_a_lower_auto_fix_threshold_allows_the_fix():
    result = _repair(LOOSER, auto_fix_threshold=0.65, suggest_threshold=0.6)
    assert result.actions[-1].similarity_score == pytest.approx(0.70, abs=1e-3)
    assert result.actions[-1].confidence == RepairConfidence.HIGH
    assert result.is_repaired


def test_a_lower_suggest_threshold_turns_a_low_match_into_a_suggestion():
    assert _repair(LOOSER).actions[-1].confidence == RepairConfidence.LOW
    result = _repair(LOOSER, suggest_threshold=0.69)
    assert result.actions[-1].confidence == RepairConfidence.MEDIUM
    assert not result.is_repaired
    assert result.repaired_text is not None


def test_a_higher_suggest_threshold_stops_a_suggestion():
    result = _repair(CLOSE, auto_fix_threshold=0.99, suggest_threshold=0.97)
    assert result.actions[-1].confidence == RepairConfidence.LOW
    assert not result.is_repaired
    assert result.repaired_text is None


@pytest.mark.parametrize(
    "thresholds",
    [
        {"auto_fix_threshold": 0.8, "suggest_threshold": 0.9},
        {"suggest_threshold": 0.4, "removal_threshold": 0.5},
    ],
    ids=["suggest_above_auto_fix", "removal_above_suggest"],
)
def test_inverted_thresholds_are_rejected(thresholds):
    with pytest.raises(ValidationError, match="threshold"):
        RepairConfig(**thresholds)


# --- the CLI -----------------------------------------------------------------


@pytest.fixture
def cache_dir(tmp_path, fixtures_dir):
    cache = tmp_path / "cache"
    cache.mkdir()
    for fixture in fixtures_dir.glob("*"):
        if fixture.is_file():
            (cache / fixture.name).write_text(fixture.read_text())
    return cache


#: A one-letter typo of a sentence in PMID:TEST001 (similarity about 0.98).
TYPO = "Protein X functions in cell cycle regulaton"


def _repair_text(cache_dir, *extra):
    return runner.invoke(
        app, ["repair", "text", TYPO, "PMID:TEST001", "--cache-dir", str(cache_dir), *extra]
    )


def test_repair_text_auto_fixes_by_default(cache_dir):
    result = _repair_text(cache_dir)
    assert result.exit_code == 0, result.output
    assert "Repaired successfully" in result.output


def test_repair_text_respects_a_higher_auto_fix_threshold(cache_dir):
    result = _repair_text(cache_dir, "--auto-fix-threshold", "0.995")
    assert "Could not repair" in result.output
    assert "Confidence: MEDIUM" in result.output


def test_repair_text_reads_the_threshold_from_the_config_file(tmp_path, cache_dir):
    """With no flag, the config file's threshold is used, not the flag's default."""
    config = tmp_path / "config.yaml"
    config.write_text("repair:\n  auto_fix_threshold: 0.995\n")
    result = _repair_text(cache_dir, "--config", str(config))
    assert "Could not repair" in result.output


def test_the_flag_overrides_the_config_file(tmp_path, cache_dir):
    config = tmp_path / "config.yaml"
    config.write_text("repair:\n  auto_fix_threshold: 0.995\n")
    result = _repair_text(cache_dir, "--config", str(config), "--auto-fix-threshold", "0.95")
    assert "Repaired successfully" in result.output


SCHEMA = """
id: https://example.org/test
name: test
default_prefix: test
classes:
  Statement:
    tree_root: true
    attributes:
      evidence:
        multivalued: true
        range: Evidence
  Evidence:
    attributes:
      reference:
        range: string
      supporting_text:
        range: string
"""


def test_repair_data_reads_the_threshold_from_the_config_file(tmp_path, cache_dir):
    """`repair data` used to overwrite the file's threshold with the flag's default."""
    schema = tmp_path / "schema.yaml"
    schema.write_text(SCHEMA)
    data = tmp_path / "data.yaml"
    original = f'evidence:\n  - reference: "PMID:TEST001"\n    supporting_text: "{TYPO}"\n'
    data.write_text(original)
    config = tmp_path / "config.yaml"
    config.write_text("repair:\n  auto_fix_threshold: 0.995\n")

    result = runner.invoke(
        app,
        ["repair", "data", str(data), "--schema", str(schema), "--cache-dir", str(cache_dir),
         "--config", str(config), "--no-dry-run"],
    )

    assert "Auto-fix threshold: 0.995" in result.output
    assert data.read_text() == original


def test_a_flag_below_the_suggest_threshold_lowers_it_rather_than_failing(cache_dir):
    """There is no --suggest-threshold, so -a 0.5 must still work."""
    result = _repair_text(cache_dir, "--auto-fix-threshold", "0.5")
    assert result.exit_code == 0, result.output
    assert "Repaired successfully" in result.output


def test_an_out_of_range_flag_is_an_error_not_a_traceback(cache_dir):
    result = _repair_text(cache_dir, "--auto-fix-threshold", "1.5")
    assert result.exit_code == 1
    assert "invalid --auto-fix-threshold" in result.output
