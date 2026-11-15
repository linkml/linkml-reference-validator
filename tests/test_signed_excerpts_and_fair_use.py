"""Tests for signed excerpts fallback and fair-use excerpt length constraints."""

from pathlib import Path
import pytest
from linkml_runtime.utils.schemaview import SchemaView  # type: ignore[import-untyped]
from linkml.validator.validation_context import ValidationContext  # type: ignore[import-untyped]

from linkml_reference_validator.models import (
    ReferenceValidationConfig,
)
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)


# ---------------------------------------------------------------------------
# Fair-use per-excerpt and per-part length limits
# ---------------------------------------------------------------------------


def test_max_excerpt_length_defaults_to_disabled():
    """Fair-use length caps default to 0 (disabled) so existing configs behave unchanged."""
    config = ReferenceValidationConfig()
    assert config.max_excerpt_length == 0
    assert config.max_excerpt_part_length == 0
    assert config.max_total_chars_per_reference == 0
    assert config.max_reference_fraction == 0.0
    assert config.signed_excerpts_dir is None


def test_max_excerpt_length_rejects_negative():
    """Negative length caps are rejected."""
    with pytest.raises(ValueError):
        ReferenceValidationConfig(max_excerpt_length=-1)
    with pytest.raises(ValueError):
        ReferenceValidationConfig(max_excerpt_part_length=-1)
    with pytest.raises(ValueError):
        ReferenceValidationConfig(max_total_chars_per_reference=-1)
    with pytest.raises(ValueError):
        ReferenceValidationConfig(max_reference_fraction=-0.1)
    with pytest.raises(ValueError):
        ReferenceValidationConfig(max_reference_fraction=1.5)


def test_check_excerpt_content_enforces_max_excerpt_length(tmp_path):
    """An excerpt whose total non-whitespace quoted characters exceed max_excerpt_length fails."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        max_excerpt_length=25,
    )
    validator = SupportingTextValidator(config)

    # "Protein X binds Y" -> 14 non-ws chars -> OK
    assert validator.check_excerpt_content("Protein X binds Y") is None

    # Long quote -> 38 non-ws chars -> rejected
    long_quote = "Protein X binds Y and activates downstream signaling"
    problem = validator.check_excerpt_content(long_quote)
    assert problem is not None
    assert "too long" in problem.lower()
    assert "max_excerpt_length" in problem


def test_check_excerpt_content_enforces_max_excerpt_part_length(tmp_path):
    """A contiguous part between '...' exceeding max_excerpt_part_length fails even if total is under max_excerpt_length."""
    config = ReferenceValidationConfig(
        cache_dir=tmp_path / "cache",
        max_excerpt_length=100,
        max_excerpt_part_length=20,
    )
    validator = SupportingTextValidator(config)

    # Two short parts joined by '...' -> each part <= 20 non-ws chars -> OK
    interspersed = "Protein X binds Y ... activates signaling"
    assert validator.check_excerpt_content(interspersed) is None

    # One long contiguous part -> 37 non-ws chars -> rejected
    contiguous = "Protein X binds Y and activates signaling"
    problem = validator.check_excerpt_content(contiguous)
    assert problem is not None
    assert "contiguous part" in problem.lower()
    assert "max_excerpt_part_length" in problem


# ---------------------------------------------------------------------------
# Signed excerpts fallback (exact match when not in reference cache)
# ---------------------------------------------------------------------------


def _write_cached_reference(cache_dir: Path, ref_id: str, title: str, content: str, content_type: str = "abstract_only") -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    safe_name = ref_id.replace(":", "_").replace("/", "_") + ".md"
    (cache_dir / safe_name).write_text(
        f"---\nreference_id: {ref_id}\ntitle: \"{title}\"\ncontent_type: {content_type}\n"
        f"extractor_version: 1\nabsent_content_version: 1\n---\n\n"
        f"# {title}\n\n## Content\n\n{content}\n",
        encoding="utf-8",
    )


def _write_signed_excerpts(signed_dir: Path, filename: str, yaml_text: str) -> Path:
    signed_dir.mkdir(parents=True, exist_ok=True)
    path = signed_dir / filename
    path.write_text(yaml_text, encoding="utf-8")
    return path


def test_signed_excerpt_exact_match_passes_when_abstract_lacks_quote(tmp_path):
    """An excerpt from full text passes when it exact-matches an entry in signed_excerpts_dir."""
    cache_dir = tmp_path / "references_cache"
    signed_dir = tmp_path / "signed_excerpts"

    _write_cached_reference(
        cache_dir,
        "PMID:33329548",
        "Adult-Onset Seronegative Rheumatoid Arthritis Study",
        "This abstract only mentions general background on arthritis.",
        content_type="abstract_only",
    )
    _write_signed_excerpts(
        signed_dir,
        "PMID_33329548.yaml",
        """reference_id: PMID:33329548
title: "Adult-Onset Seronegative Rheumatoid Arthritis Study"
excerpts:
  - text: "Traditionally, RA is divided into seropositive (SP) ... with joint involvement."
    claim_text: "RA has seropositive and seronegative forms"
    section: "Introduction"
    entities:
      - id: MONDO:0008383
        label: rheumatoid arthritis
""",
    )

    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        signed_excerpts_dir=signed_dir,
        fetch_full_text=False,
        rate_limit_delay=0.0,
    )
    validator = SupportingTextValidator(config)

    # Exact match with signed excerpt -> valid!
    result = validator.validate(
        "Traditionally, RA is divided into seropositive (SP) ... with joint involvement.",
        "PMID:33329548",
        expected_title="Adult-Onset Seronegative Rheumatoid Arthritis Study",
    )
    assert result.is_valid is True
    assert result.title_checked is True
    assert result.match_result is not None
    assert result.match_result.match_location == "signed_excerpts"
    assert "signed excerpt" in (result.message or "").lower()


def test_signed_excerpt_rejects_any_deviation_from_signed_text(tmp_path):
    """Any deviation from the signed excerpt (even a substring or single word change) is flagged."""
    cache_dir = tmp_path / "references_cache"
    signed_dir = tmp_path / "signed_excerpts"

    _write_cached_reference(
        cache_dir,
        "PMID:33329548",
        "Adult-Onset Seronegative Rheumatoid Arthritis Study",
        "This abstract only mentions general background on arthritis.",
        content_type="abstract_only",
    )
    _write_signed_excerpts(
        signed_dir,
        "PMID_33329548.yaml",
        """reference_id: PMID:33329548
excerpts:
  - text: "Traditionally, RA is divided into seropositive (SP) ... with joint involvement."
""",
    )

    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        signed_excerpts_dir=signed_dir,
        fetch_full_text=False,
        rate_limit_delay=0.0,
    )
    validator = SupportingTextValidator(config)

    # A substring of the signed excerpt is NOT an exact match and must fail
    sub_result = validator.validate(
        "Traditionally, RA is divided into seropositive (SP)",
        "PMID:33329548",
    )
    assert sub_result.is_valid is False

    # A modified word in the signed excerpt must fail
    modified_result = validator.validate(
        "Traditionally, RA is divided into seropositive (SP) ... with severe joint involvement.",
        "PMID:33329548",
    )
    assert modified_result.is_valid is False


def test_signed_excerpt_still_enforces_title_validation(tmp_path):
    """Even when an excerpt matches signed_excerpts, a wrong expected_title still fails."""
    cache_dir = tmp_path / "references_cache"
    signed_dir = tmp_path / "signed_excerpts"

    _write_cached_reference(
        cache_dir,
        "PMID:33329548",
        "Adult-Onset Seronegative Rheumatoid Arthritis Study",
        "This abstract only mentions general background on arthritis.",
        content_type="abstract_only",
    )
    _write_signed_excerpts(
        signed_dir,
        "PMID_33329548.yaml",
        """reference_id: PMID:33329548
excerpts:
  - text: "Traditionally, RA is divided into seropositive (SP) ... with joint involvement."
""",
    )

    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        signed_excerpts_dir=signed_dir,
        fetch_full_text=False,
        rate_limit_delay=0.0,
    )
    validator = SupportingTextValidator(config)

    result = validator.validate(
        "Traditionally, RA is divided into seropositive (SP) ... with joint involvement.",
        "PMID:33329548",
        expected_title="Completely Wrong Paper Title",
    )
    assert result.is_valid is False
    assert "title mismatch" in (result.message or "").lower()


def test_signed_excerpt_works_when_reference_is_unavailable_in_public_cache(tmp_path):
    """If a closed reference has content_type: unavailable (no abstract), signed_excerpts still validates it."""
    cache_dir = tmp_path / "references_cache"
    signed_dir = tmp_path / "signed_excerpts"

    _write_cached_reference(
        cache_dir,
        "DOI:10.1016/j.cell.2021.01.001",
        "P5CS Filaments in Mitochondrial Stress",
        "",
        content_type="unavailable",
    )
    _write_signed_excerpts(
        signed_dir,
        "DOI_10.1016_j.cell.2021.01.001.yaml",
        """reference_id: DOI:10.1016/j.cell.2021.01.001
title: "P5CS Filaments in Mitochondrial Stress"
excerpts:
  - snippet: "P5CS filaments assemble in response to ... mitochondrial stress"
""",
    )

    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        signed_excerpts_dir=signed_dir,
        fetch_full_text=False,
        rate_limit_delay=0.0,
    )
    validator = SupportingTextValidator(config)

    result = validator.validate(
        "P5CS filaments assemble in response to ... mitochondrial stress",
        "DOI:10.1016/j.cell.2021.01.001",
        expected_title="P5CS Filaments in Mitochondrial Stress",
    )
    assert result.is_valid is True
    assert result.match_result is not None
    assert result.match_result.match_location == "signed_excerpts"


# ---------------------------------------------------------------------------
# Cumulative per-reference and fraction-of-reference fair-use limits
# ---------------------------------------------------------------------------


def test_per_reference_cumulative_and_fraction_limits(tmp_path):
    """Cumulative characters quoted from a single reference cannot exceed max_total_chars_per_reference or max_reference_fraction."""
    cache_dir = tmp_path / "references_cache"
    # Reference body has 200 non-whitespace characters:
    body = (
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa. "
        "Lambda mu nu xi omicron pi rho sigma tau upsilon. "
        "Phi chi psi omega primera segunda tercera cuarta quinta. "
        "Sexta septima octava novena decima undeca duodeca."
    )
    _write_cached_reference(
        cache_dir,
        "PMID:999999",
        "Greek Letters Paper",
        body,
        content_type="full_text_pdf",
    )

    schema_yaml = tmp_path / "schema.yaml"
    schema_yaml.write_text(
        """id: https://example.org/claimstore
name: claimstore
prefixes:
  linkml: https://w3id.org/linkml/
  dcterms: http://purl.org/dc/terms/
  oa: http://www.w3.org/ns/oa#
default_range: string
classes:
  ReferenceExcerpts:
    tree_root: true
    attributes:
      reference_id:
        slot_uri: dcterms:references
      title:
        slot_uri: dcterms:title
      excerpts:
        range: ExcerptItem
        multivalued: true
        inlined_as_list: true
  ExcerptItem:
    attributes:
      text:
        slot_uri: oa:exact
      claim_text:
        range: string
""",
        encoding="utf-8",
    )

    # Set max_total_chars_per_reference=60
    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        fetch_full_text=False,
        max_total_chars_per_reference=60,
    )
    plugin = ReferenceValidationPlugin(config=config)
    sv = SchemaView(str(schema_yaml))
    ctx = ValidationContext(sv.schema, target_class="ReferenceExcerpts")
    plugin.pre_process(ctx)

    instance = {
        "reference_id": "PMID:999999",
        "title": "Greek Letters Paper",
        "excerpts": [
            {"text": "Alpha beta gamma delta epsilon zeta"},  # 30 non-ws chars -> cumulative 30 <= 60 (OK)
            {"text": "Lambda mu nu xi omicron pi rho sigma"},  # 29 non-ws chars -> cumulative 59 <= 60 (OK)
            {"text": "Phi chi psi omega primera segunda"},     # 28 non-ws chars -> cumulative 87 > 60 (FAIL!)
        ],
    }

    results = list(plugin.process(instance, ctx))
    assert len(results) == 1
    assert "max_total_chars_per_reference" in results[0].message
    assert "excerpts[2]" in (results[0].instantiates or "")


def test_per_reference_fraction_limit(tmp_path):
    """Cumulative characters quoted from a reference cannot exceed max_reference_fraction of the reference length."""
    cache_dir = tmp_path / "references_cache"
    # Reference body with ~180 non-whitespace chars
    body = (
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa. "
        "Lambda mu nu xi omicron pi rho sigma tau upsilon. "
        "Phi chi psi omega primera segunda tercera cuarta quinta. "
        "Sexta septima octava novena decima undeca duodeca."
    )
    _write_cached_reference(
        cache_dir,
        "PMID:888888",
        "Short Paper",
        body,
        content_type="full_text_pdf",
    )

    config = ReferenceValidationConfig(
        cache_dir=cache_dir,
        fetch_full_text=False,
        max_reference_fraction=0.20,  # 20% of ~180 chars is ~36 chars
    )
    validator = SupportingTextValidator(config)

    # First quote: 30 non-ws chars (<= 36) -> passes
    r1 = validator.validate("Alpha beta gamma delta epsilon zeta", "PMID:888888")
    assert r1.is_valid is True

    # Second distinct quote: 29 non-ws chars -> cumulative 59 (> 36) -> fails on fraction!
    r2 = validator.validate("Lambda mu nu xi omicron pi rho sigma", "PMID:888888")
    assert r2.is_valid is False
    assert "max_reference_fraction" in (r2.message or "")
