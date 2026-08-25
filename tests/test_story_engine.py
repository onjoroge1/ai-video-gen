"""Story-format structure gates, run against fixtures at zero spend.

The point of this module is that a wrong threshold costs nothing to find: `story_engine` imports
no pipeline code and calls no provider, so the gates can be exercised against narration fixtures
instead of against a rendered video. That matters here more than usual — a long-form run cannot
currently reach a finished video at all (the rendered gate has no calibrated threshold profile),
so a fixture is the only way to test story structure end to end.
"""
import json
from pathlib import Path

import pytest

import story_engine as se

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "story"


def test_selftest_passes_every_fixture():
    """The module's own two-sided acceptance bar: known-good passes, known-bad fails."""
    assert se.selftest(verbose=False) == 0


def test_fixtures_cover_both_directions():
    """A gate that cannot fail known-bad is not evidence; one that fails known-good is worse.

    Guard the shape of the corpus, not just that it passes — a fixture set that drifted to
    all-negative or all-positive would still satisfy selftest while proving nothing.
    """
    expectations = [json.loads(p.read_text()).get("expect", {})
                    for p in FIXTURES.glob("*.json")]
    assert any(e.get("pass") is True for e in expectations), "no known-good fixture"
    assert any(e.get("pass") is False for e in expectations), "no known-bad fixture"


def test_the_default_lane_is_not_pushed_into_a_mystery():
    """default_explainer is a deliberate passthrough and must stay ungated.

    If its cadence bands ever became live, every ordinary explainer topic would be forced toward a
    mystery structure it does not have.
    """
    fmt = se.get("default_explainer")
    assert fmt.long_band == (0.0, 1.0)
    assert fmt.short_band == (0.0, 1.0)
    assert fmt.max_short_run_fail is None


def test_mystery_requires_its_load_bearing_roles():
    fmt = se.get("evidence_led_mystery")
    for role in ("anomaly", "false_belief", "reversal", "consequence", "mechanism", "resolution"):
        assert role in fmt.required, role
    # Bands must be ordered and non-overlapping at their anchors, or "delayed causal resolution"
    # is not actually delayed.
    assert fmt.bands["anomaly"][0] == 0.0
    assert fmt.bands["mechanism"][0] >= 45.0
    assert fmt.bands["resolution"][1] == 100.0


def test_judgement_calls_are_reviews_not_silent_passes():
    """Anything needing judgement must surface as a review and never be auto-passed.

    A check that guesses launders an unverified assumption into a green tick — the invented-evidence
    failure mode this module exists to prevent.
    """
    thin = {"beat_roles": [], "narration": ["A reef died fast.", "Nobody knows why."]}
    report = se.check(thin, se.get("evidence_led_mystery"))
    joined = " ".join(str(x) for x in report["requires_review"])
    assert report["requires_review"], "silent pass on a script with no roles at all"
    assert "beat roles absent" in joined
    assert "do NOT invent" in joined, "evidence anchor review must warn against inventing a date"


@pytest.mark.parametrize("fmt_name", ["default_explainer", "evidence_led_mystery",
                                      "evidence_led_short"])
def test_every_declared_format_resolves(fmt_name):
    assert se.get(fmt_name).name == fmt_name
