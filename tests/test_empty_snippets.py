"""Tests for rejection of substantively empty supporting text.

An empty (or whitespace-only) snippet used to pass the whole validation stack
vacuously: the empty string is a substring of every document, so every
"is this quote in the reference?" check succeeded without any evidence being
present. See https://github.com/monarch-initiative/dismech/issues/8550

Every layer must now treat a present-but-blank excerpt as an error:

- ``SupportingTextValidator`` rejects blank text before it ever fetches
- the LinkML plugin distinguishes an absent excerpt slot from a blank one
- the repairer flags blank text for removal instead of attempting a fix
- the repair CLI collects blank snippets instead of silently dropping them
"""

from pathlib import Path

import pytest
from linkml.validator.validation_context import ValidationContext  # type: ignore[import-untyped]
from linkml_runtime.utils.schemaview import SchemaView  # type: ignore[import-untyped]

from linkml_reference_validator.cli.repair import _extract_evidence_items
from linkml_reference_validator.models import (
    ReferenceContent,
    ReferenceValidationConfig,
    RepairActionType,
    RepairConfig,
    ValidationSeverity,
)
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)
from linkml_reference_validator.validation.repairer import SupportingTextRepairer
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
    is_blank_text,
)

MIN_LENGTH = 20

DATA_DIR = Path(__file__).parent / "data"
FIXTURES_DIR = Path(__file__).parent / "fixtures"
DEEP_SCHEMA = DATA_DIR / "test_schema_deep_nesting.yaml"

BLANK_TEXTS = ["", " ", "   ", "\t", "\n", " \t\n ", " "]


@pytest.fixture
def config(tmp_path):
    """Configuration pointing at an empty temporary cache."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
    )


@pytest.fixture
def validator(config):
    """Validator under test."""
    return SupportingTextValidator(config)


@pytest.fixture
def cached_config(tmp_path):
    """Configuration with the test reference fixtures pre-cached."""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for fixture_file in FIXTURES_DIR.glob("*.md"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    for fixture_file in FIXTURES_DIR.glob("*.txt"):
        (cache_dir / fixture_file.name).write_text(fixture_file.read_text())
    return ReferenceValidationConfig(cache_dir=cache_dir, rate_limit_delay=0.0)


@pytest.fixture
def plugin(cached_config):
    """Plugin with cached test references."""
    return ReferenceValidationPlugin(config=cached_config)


@pytest.fixture
def deep_context(plugin):
    """Validation context for the deeply nested test schema."""
    schema_view = SchemaView(str(DEEP_SCHEMA))
    context = ValidationContext(schema_view.schema, target_class="Community")
    plugin.pre_process(context)
    return context


def _community(snippet_field: dict) -> dict:
    """Build a Community instance whose single evidence item carries the given fields."""
    return {
        "name": "Test Community",
        "members": [
            {
                "taxon_name": "Species A",
                "evidence": [{"reference": "PMID:TEST001", **snippet_field}],
            }
        ],
    }


# ---------------------------------------------------------------------------
# is_blank_text
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", BLANK_TEXTS)
def test_is_blank_text_true(text):
    """Empty and whitespace-only strings are blank."""
    assert is_blank_text(text) is True


@pytest.mark.parametrize("text", ["a", " a ", "[note]", "..."])
def test_is_blank_text_false(text):
    """Any string with a non-whitespace character is not blank."""
    assert is_blank_text(text) is False


def test_is_blank_text_non_string():
    """Non-strings are not blank text (they are handled elsewhere)."""
    assert is_blank_text(None) is False
    assert is_blank_text(["a"]) is False


# ---------------------------------------------------------------------------
# SupportingTextValidator
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", BLANK_TEXTS)
def test_validate_rejects_blank_supporting_text(validator, text):
    """A blank snippet is an error, not a vacuous pass."""
    result = validator.validate(text, "PMID:TEST001")

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR
    assert "empty" in result.message.lower()


def test_validate_blank_does_not_fetch(validator, mocker):
    """A blank snippet fails without any reference lookup."""
    spy = mocker.patch.object(validator.fetcher, "fetch")

    result = validator.validate("", "PMID:TEST001")

    assert result.is_valid is False
    spy.assert_not_called()


def test_validate_blank_rejected_for_skipped_prefix(tmp_path):
    """Blank text is a data defect even when the reference prefix is skipped."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        skip_prefixes=["GO"],
    )
    validator = SupportingTextValidator(config)

    result = validator.validate("", "GO:0008150")

    assert result.is_valid is False
    assert "empty" in result.message.lower()


def test_find_text_in_reference_rejects_blank(validator):
    """Blank text is not found, even though "" is a substring of everything."""
    ref = ReferenceContent(
        reference_id="PMID:123",
        content="The protein functions in cell cycle regulation.",
    )

    match = validator.find_text_in_reference("", ref)

    assert match.found is False
    assert "empty" in match.error_message.lower()


def test_find_text_in_reference_blank_without_content(validator):
    """Blank text is reported as empty rather than as a missing-content problem."""
    ref = ReferenceContent(reference_id="PMID:123", content=None)

    match = validator.find_text_in_reference("   ", ref)

    assert match.found is False
    assert "empty" in match.error_message.lower()


def test_validate_still_accepts_real_text(cached_config):
    """The blank guard must not disturb ordinary validation."""
    validator = SupportingTextValidator(cached_config)

    result = validator.validate(
        "Protein X functions in cell cycle regulation", "PMID:TEST001"
    )

    assert result.is_valid is True


# ---------------------------------------------------------------------------
# ReferenceValidationPlugin
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "   ", "\n"])
def test_plugin_rejects_blank_snippet(plugin, deep_context, text):
    """A present-but-blank snippet must produce a validation error."""
    results = list(plugin.process(_community({"snippet": text}), deep_context))

    assert len(results) == 1, (
        "A blank snippet should be reported exactly once, "
        f"got {[r.message for r in results]}"
    )
    assert "empty" in results[0].message.lower()
    assert "snippet" in results[0].instantiates


def test_plugin_blank_snippet_reported_without_reference(plugin, deep_context):
    """A blank snippet is reported even when no reference is present to check it against."""
    instance = {
        "name": "Test Community",
        "members": [{"taxon_name": "Species A", "evidence": [{"snippet": ""}]}],
    }

    results = list(plugin.process(instance, deep_context))

    assert len(results) == 1
    assert "empty" in results[0].message.lower()


def test_plugin_absent_snippet_is_not_an_error(plugin, deep_context):
    """An absent excerpt slot is LinkML's concern (required-ness), not ours."""
    instance = _community({})

    results = list(plugin.process(instance, deep_context))

    assert results == []


def test_plugin_null_snippet_is_not_an_error(plugin, deep_context):
    """An explicitly null excerpt is absent, not blank."""
    instance = _community({"snippet": None})

    results = list(plugin.process(instance, deep_context))

    assert results == []


def test_plugin_valid_snippet_still_passes(plugin, deep_context):
    """The blank guard must not flag genuine snippets."""
    instance = _community(
        {"snippet": "Protein X functions in cell cycle regulation"}
    )

    results = list(plugin.process(instance, deep_context))

    assert results == []


# ---------------------------------------------------------------------------
# SupportingTextRepairer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("text", ["", "  "])
def test_repair_single_flags_blank_for_removal(cached_config, text):
    """A blank snippet cannot be repaired; it is flagged for human review."""
    repairer = SupportingTextRepairer(cached_config, RepairConfig())

    result = repairer.repair_single(text, "PMID:TEST001", path="evidence[0].snippet")

    assert result.was_valid is False
    assert result.is_repaired is False
    assert result.repaired_text is None
    assert [a.action_type for a in result.actions] == [RepairActionType.REMOVAL]
    assert result.actions[0].can_auto_fix is False
    assert "empty" in result.message.lower()
    assert result.path == "evidence[0].snippet"


def test_repair_single_blank_does_not_fetch(cached_config, mocker):
    """Repairing a blank snippet needs no reference lookup."""
    repairer = SupportingTextRepairer(cached_config, RepairConfig())
    spy = mocker.patch.object(repairer.fetcher, "fetch")

    repairer.repair_single("", "PMID:TEST001")

    spy.assert_not_called()


# ---------------------------------------------------------------------------
# Repair CLI extraction
# ---------------------------------------------------------------------------


def test_extract_evidence_items_keeps_blank_snippet():
    """Blank snippets must reach the repairer instead of being dropped."""
    data = {
        "evidence": [
            {"reference": "PMID:TEST001", "snippet": ""},
            {"reference": "PMID:TEST002", "snippet": "real text"},
        ]
    }

    items = _extract_evidence_items(data, None, Path("unused.yaml"))

    assert ("", "PMID:TEST001", "evidence[0]") in items
    assert ("real text", "PMID:TEST002", "evidence[1]") in items


def test_extract_evidence_items_prefers_non_blank_key():
    """When both keys are present, a non-blank value still wins."""
    data = {
        "evidence": [
            {
                "reference": "PMID:TEST001",
                "supporting_text": "",
                "snippet": "real text",
            }
        ]
    }

    items = _extract_evidence_items(data, None, Path("unused.yaml"))

    assert items == [("real text", "PMID:TEST001", "evidence[0]")]


def test_extract_evidence_items_requires_reference():
    """A blank snippet with no reference has nothing to repair against."""
    data = {"evidence": [{"snippet": ""}]}

    items = _extract_evidence_items(data, None, Path("unused.yaml"))

    assert items == []


# ---------------------------------------------------------------------------
# Configurable minimum excerpt length
#
# A blank excerpt is the extreme case; a two-character one is barely better,
# since a short string matches almost any paper by chance. Length is measured
# in non-whitespace characters of quoted text, which keeps the count stable
# across PDF-to-text whitespace damage and never splits chemical names.
# ---------------------------------------------------------------------------


@pytest.fixture
def strict_config(tmp_path):
    """Configuration enforcing a minimum excerpt length."""
    return ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        rate_limit_delay=0.0,
        min_excerpt_length=MIN_LENGTH,
    )


def test_min_excerpt_length_defaults_to_disabled():
    """The check is opt-in so existing data keeps validating as before."""
    assert ReferenceValidationConfig().min_excerpt_length == 0


def test_min_excerpt_length_rejects_negative():
    """A negative minimum is meaningless."""
    with pytest.raises(ValueError):
        ReferenceValidationConfig(min_excerpt_length=-1)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("the protein", 10),
        # PDF-to-text whitespace damage must not change the count.
        ("t he pro tein", 10),
        ("the\n\nprotein", 10),
        # Editorial brackets are not quoted text.
        ("protein [important] functions", len("proteinfunctions")),
        # Ellipsis separators are not quoted text.
        ("abc ... def", 6),
        ("[editorial note only]", 0),
        ("", 0),
        # Chemical nomenclature counts in full - no tokenizing, no splitting.
        ("2,3-dihydroxybenzoate", 21),
        ("N-(4-hydroxyphenyl)acetamide", 28),
    ],
)
def test_count_quoted_characters(validator, text, expected):
    """Length counts non-whitespace characters of actually-quoted text."""
    assert validator.count_quoted_characters(text) == expected


def test_count_quoted_characters_survives_whitespace_damage(validator):
    """Mangled and clean renderings of the same quote measure identically."""
    clean = "the protein functions in cell cycle"
    mangled = "the  pro tein  func tions\tin cell   cycle"

    assert validator.count_quoted_characters(clean) == validator.count_quoted_characters(
        mangled
    )


def test_validate_rejects_too_short_excerpt(strict_config):
    """An excerpt below the configured minimum is an error."""
    validator = SupportingTextValidator(strict_config)

    result = validator.validate("the gene", "PMID:TEST001")

    assert result.is_valid is False
    assert result.severity == ValidationSeverity.ERROR
    assert "too short" in result.message.lower()
    assert str(MIN_LENGTH) in result.message


def test_validate_too_short_does_not_fetch(strict_config, mocker):
    """A too-short excerpt fails without any reference lookup."""
    validator = SupportingTextValidator(strict_config)
    spy = mocker.patch.object(validator.fetcher, "fetch")

    validator.validate("the gene", "PMID:TEST001")

    spy.assert_not_called()


def test_validate_accepts_excerpt_at_minimum(cached_config):
    """An excerpt meeting the minimum validates normally."""
    text = "Protein X functions in cell cycle regulation"
    cached_config.min_excerpt_length = len(text.replace(" ", ""))
    validator = SupportingTextValidator(cached_config)

    result = validator.validate(text, "PMID:TEST001")

    assert result.is_valid is True


def test_short_excerpt_allowed_when_check_disabled(cached_config):
    """With the default config, a short but real quote still passes."""
    validator = SupportingTextValidator(cached_config)

    result = validator.validate("Protein X", "PMID:TEST001")

    assert result.is_valid is True


def test_find_text_in_reference_rejects_too_short(strict_config):
    """The matching entry point enforces the minimum too."""
    validator = SupportingTextValidator(strict_config)
    ref = ReferenceContent(
        reference_id="PMID:123",
        content="The protein functions in cell cycle regulation.",
    )

    match = validator.find_text_in_reference("protein", ref)

    assert match.found is False
    assert "too short" in match.error_message.lower()


def test_plugin_rejects_too_short_snippet(cached_config):
    """The plugin reports a too-short snippet like any other empty evidence."""
    cached_config.min_excerpt_length = MIN_LENGTH
    plugin = ReferenceValidationPlugin(config=cached_config)
    schema_view = SchemaView(str(DEEP_SCHEMA))
    context = ValidationContext(schema_view.schema, target_class="Community")
    plugin.pre_process(context)

    results = list(plugin.process(_community({"snippet": "the gene"}), context))

    assert len(results) == 1
    assert "too short" in results[0].message.lower()


def test_repair_single_flags_too_short_for_removal(cached_config):
    """A too-short excerpt cannot be repaired - there is nothing to expand from."""
    cached_config.min_excerpt_length = MIN_LENGTH
    repairer = SupportingTextRepairer(cached_config, RepairConfig())

    result = repairer.repair_single("the gene", "PMID:TEST001")

    assert result.is_repaired is False
    assert [a.action_type for a in result.actions] == [RepairActionType.REMOVAL]
    assert "too short" in result.message.lower()
