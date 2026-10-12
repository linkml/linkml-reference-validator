"""Exercise normalization reuse through real matching, without timing thresholds."""

import cProfile
from pathlib import Path

from linkml_reference_validator.models import ReferenceContent, ReferenceValidationConfig
from linkml_reference_validator.validation.supporting_text_validator import SupportingTextValidator


def normalization_calls(profile: cProfile.Profile) -> int:
    """Count actual normalizer executions, independently of cache internals."""
    code = SupportingTextValidator.normalize_text.__code__
    return sum(entry.callcount for entry in profile.getstats() if entry.code is code)


def test_repeated_publication_normalized_once(tmp_path: Path) -> None:
    """Different excerpts share one normalization of their publication body."""
    validator = SupportingTextValidator(ReferenceValidationConfig(cache_dir=tmp_path))
    reference = ReferenceContent(
        reference_id="TEST:one", content="α-ﬁbrils bind receptors. Cells respond to H₂O."
    )
    with cProfile.Profile() as profile:
        for quote in ["alpha fibrils", "bind receptors", "Cells respond to H₂O"]:
            assert validator.find_text_in_reference(quote, reference).found
    # One publication plus three query parts, rather than six full normalizations.
    assert normalization_calls(profile) == 4


def test_reference_changes_cannot_reuse_stale_normalization(tmp_path: Path) -> None:
    """The cache follows text, including edits to an existing reference object."""
    validator = SupportingTextValidator(ReferenceValidationConfig(cache_dir=tmp_path))
    reference = ReferenceContent(reference_id="TEST:one", content="alpha activates beta")
    assert validator.find_text_in_reference("alpha activates beta", reference).found
    reference.content = "alpha inhibits beta"
    assert not validator.find_text_in_reference("alpha activates beta", reference).found
    assert validator.find_text_in_reference("alpha inhibits beta", reference).found
    other = ReferenceContent(reference_id="TEST:one", content="gamma binds delta")
    assert not validator.find_text_in_reference("alpha inhibits beta", other).found


def test_normalization_is_scoped_to_validator_and_evicted(tmp_path: Path) -> None:
    """Keep at most 128 recent bodies per validator; old ones are recomputed."""
    validator = SupportingTextValidator(ReferenceValidationConfig(cache_dir=tmp_path))
    first = ReferenceContent(reference_id="TEST:first", content="The first protein binds ATP.")
    assert validator.find_text_in_reference("first protein", first).found
    for i in range(128):
        reference = ReferenceContent(reference_id=f"TEST:{i}", content=f"Protein number {i} binds ATP.")
        assert validator.find_text_in_reference("binds ATP", reference).found
    with cProfile.Profile() as evicted:
        assert validator.find_text_in_reference("first protein", first).found
    assert normalization_calls(evicted) == 2  # Both content and query must be recomputed.
    with cProfile.Profile() as reused:
        assert validator.find_text_in_reference("first protein", first).found
    assert normalization_calls(reused) == 1  # Only the query, without keeping every query.
    fresh = SupportingTextValidator(ReferenceValidationConfig(cache_dir=tmp_path))
    with cProfile.Profile() as isolated:
        assert fresh.find_text_in_reference("first protein", first).found
    assert normalization_calls(isolated) == 2


def test_warm_cache_preserves_svg_label_boundaries_and_unicode(tmp_path: Path) -> None:
    """Cached normalizations do not join labels or erase scientific distinctions."""
    validator = SupportingTextValidator(ReferenceValidationConfig(cache_dir=tmp_path))
    reference = ReferenceContent(
        reference_id="file:figure.svg", content="α-ﬁbrils\n\nH₂O concentration", content_type="local_svg"
    )
    for _ in range(2):
        assert validator.find_text_in_reference("alpha fibrils ... H₂O concentration", reference).found
        assert not validator.find_text_in_reference("alpha fibrils H₂O concentration", reference).found
        assert not validator.find_text_in_reference("H2O concentration", reference).found
