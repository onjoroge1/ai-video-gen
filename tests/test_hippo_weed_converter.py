"""The operator's hippo Markdown, converted into a renderable directed contract.

The document is the first artifact in this project that solves the cadence problem by itself: its
tables specify ~79 visual states across 208 seconds. Every generated pilot managed 7.79s per shot
against references measured at 2.36s and 3.38s. These tests exist to make sure the conversion
carries that resolution through rather than collapsing rows back into one image each.
"""
import importlib.util
from pathlib import Path

import pytest

import directed_longform as dl

ROOT = Path(__file__).resolve().parent.parent
BUILDER = ROOT / "scripts" / "build_hippo_weed_directed.py"


def _module():
    spec = importlib.util.spec_from_file_location("build_hippo_weed_directed", BUILDER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def built():
    module = _module()
    if not module.SOURCE.exists():
        pytest.skip("operator source document is not present")
    return module.build()


def test_the_contract_validates(built):
    report = dl.validate_directed_spec(built)
    assert report["valid"] is True, report.get("issues")


def test_every_visual_state_becomes_its_own_shot(built):
    """One shot per composition is the whole point.

    Collapsing a table row into a single image is what produced the 7.79s slideshow; the document
    stages two to four compositions per beat deliberately.
    """
    assert len(built["narration"]) == 22
    assert len(built["shots"]) > 3 * len(built["narration"])


def test_the_cadence_matches_the_reference_band(built):
    """Measured: reference A 3.38s, reference B 2.36s, generated pilot 7.79s."""
    duration = built["target"]["duration_sec"]
    mean = duration / len(built["shots"])
    assert 2.0 <= mean <= 3.5, f"{mean:.2f}s per shot is outside the reference band"

    holds = [shot["end_sec"] - shot["start_sec"] for shot in built["shots"]]
    assert max(holds) <= built["acceptance"]["max_unchanged_hold_sec"] + 0.01


def test_the_timeline_is_contiguous_and_zero_based(built):
    for series in (built["narration"], built["shots"]):
        assert series[0]["start_sec"] == 0.0
        for previous, current in zip(series, series[1:]):
            assert current["start_sec"] == pytest.approx(previous["end_sec"], abs=0.02)


def test_bolt_appears_exactly_as_the_document_stages_him(built):
    """The document's prose says "twice"; its storyboard stages three.

    The contract's bolt check caught that, which is the validator doing its job on an internal
    inconsistency in the source. The labels follow the storyboard, not the prose.
    """
    labelled = [s for s in built["shots"] if "useful_bolt" in s["labels"]]
    assert len(labelled) == built["acceptance"]["planned_bolt_appearances"]
    assert all("bolt" in s["visual"].casefold() for s in labelled)


def test_the_illustrated_look_and_its_negative_prompt_are_carried(built):
    import illustrated_story
    world = built["worlds"][0]
    assert "round white heads" in world["base_prompt"]
    assert "Broussard" in world["base_prompt"]        # recurring identity, per the document
    assert built["negative_prompt"] == illustrated_story.negative_prompt()
