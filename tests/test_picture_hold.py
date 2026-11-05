"""One picture held under several camera moves is one hold (operator, 2026-11-05)."""
from longform_shots import shot_plan_metrics, split_long_holds


def _still(source, duration, start, strategy="distinct", source_asset_id=""):
    return {"kind": "still", "source": source, "duration": duration, "start_sec": start,
            "end_sec": start + duration, "asset_strategy": strategy,
            "source_asset_id": source_asset_id, "transition": "hard_cut",
            "semantic_aligned": True, "new_information": True}


def test_hold_split_parts_count_as_one_picture():
    # A 10 s master split into camera-move parts: every shot is under 3.5 s, the picture is not.
    parts = split_long_holds([_still("asset:s001:e01", 10.0, 0.0, "master")])
    assert len(parts) > 1 and max(p["duration"] for p in parts) <= 3.5
    plan = [parts + [_still("asset:s001:e02", 3.0, 10.0)]]
    metrics = shot_plan_metrics(plan)
    assert metrics["max_still_seconds"] <= 3.5
    assert metrics["max_picture_seconds"] == 10.0
    assert metrics["max_opening_picture_seconds"] == 10.0


def test_detail_reframe_continues_its_source_picture():
    plan = [[_still("asset:s001:e01", 3.0, 0.0, "master"),
             _still("asset:s001:e02", 3.0, 3.0, "detail_reframe", "asset:s001:e01"),
             _still("asset:s001:e03", 3.0, 6.0)]]
    assert shot_plan_metrics(plan)["max_picture_seconds"] == 6.0


def test_new_picture_every_few_seconds_passes():
    plan = [[_still(f"asset:s001:e{i:02d}", 3.0, 3.0 * i) for i in range(1, 20)]]
    metrics = shot_plan_metrics(plan)
    assert metrics["max_picture_seconds"] == 3.0
    assert metrics["max_picture_seconds"] <= metrics["picture_hold_ceiling_seconds"]
    assert metrics["max_opening_picture_seconds"] <= metrics["opening_picture_hold_ceiling_seconds"]
