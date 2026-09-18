from longform_shots import shot_plan_metrics
from retention_readiness import score_retention_readiness


def _shot(duration, *, aligned=True, timing_source="measured"):
    return {
        "kind": "still", "duration": duration, "source": f"asset:{duration}",
        "transition": "hard_cut", "semantic_aligned": aligned,
        "new_information": True, "verified_visible_information": True,
        "asset_strategy": "distinct", "timing_source": timing_source,
    }


def test_shot_metrics_name_alignment_honestly_and_count_ceiling_failures():
    metrics = shot_plan_metrics([[_shot(2.5), _shot(4.2, aligned=False,
                                                       timing_source="even_fallback")]])

    assert metrics["narration_aligned_cut_ratio"] == metrics["semantic_sync_ratio"] == 0.0
    assert metrics["over_ceiling_still_count"] == 1
    assert metrics["timing_fallback_shot_count"] == 1
    assert metrics["max_still_seconds"] == 4.2


def test_readiness_cannot_reward_a_hold_its_rendered_gate_rejects():
    metrics = shot_plan_metrics([[_shot(2.5), _shot(4.2)]])
    report = score_retention_readiness(
        {"scenes": [{"story_role": "setup"}], "_story_contract": {"ok": True}},
        {"checks": {}}, metrics, [])

    assert "long_visual_hold" in report["hard_failures"]
    visual = next(item for item in report["components"]
                  if item["name"] == "Visual continuity & semantic sync")
    assert any("exceed" in note for note in visual["notes"])
