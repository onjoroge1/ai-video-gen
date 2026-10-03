"""Two scenes that say the same sentence are a defect (killer bees, 2026-10-02)."""
import json
import explainer_pipeline as ep


def _scene(beat, text, continues="", role="escalation", part=1, count=1):
    return {"beat_id": beat, "narration": text, "continues": continues, "causal_role": role,
            "beat_part": part, "beat_part_count": count, "_parent_beat_id": beat.rstrip("b")}


def test_detects_verbatim_and_near_duplicates_only():
    scenes = [
        _scene("event_05", "In October 1957, a local beekeeper noticed the queen excluders and removed them from the hives."),
        _scene("event_05b", "In October 1957, a local beekeeper noticed the queen excluders and removed them from the hives.",
               continues="event_05", part=2, count=2),
        _scene("event_06", "Twenty-six African queens and their swarms escaped the apiary south of Sao Paulo."),
        _scene("event_07", "The hybrids moved north two hundred miles a year and reached Texas in 1990."),
    ]
    dupes = ep.duplicate_narration(scenes)
    assert [(d["scene"], d["duplicate_of"], d["continuation"]) for d in dupes] == [(2, 1, True)]


def test_collapse_drops_the_repeating_continuation_and_reknits_parts():
    script = {"scenes": [
        _scene("event_05", "In October 1957, a beekeeper removed the queen excluders from the hives.", part=1, count=2),
        _scene("event_05b", "In October 1957, a beekeeper removed the queen excluders from the hives.",
               continues="event_05", part=2, count=2),
        _scene("event_06", "Twenty-six queens and their swarms poured out across the grove."),
    ]}
    dropped = ep.collapse_duplicate_narration(script)
    assert dropped == 1
    ids = [s["beat_id"] for s in script["scenes"]]
    assert ids == ["event_05", "event_06"]
    assert script["scenes"][0]["beat_part_count"] == 1 and script["scenes"][0]["continues"] == ""
    assert [s["n"] for s in script["scenes"]] == [1, 2]
    assert ep.duplicate_narration(script["scenes"]) == []


def test_non_continuation_duplicate_is_reported_not_dropped():
    script = {"scenes": [
        _scene("event_04", "The escaped bees formed hybrid populations with European honey bees.", role="mechanism"),
        _scene("event_16", "The escaped bees formed hybrid populations with European honey bees.", role="reversal"),
    ]}
    assert ep.collapse_duplicate_narration(script) == 0
    assert ep.duplicate_narration(script["scenes"])
