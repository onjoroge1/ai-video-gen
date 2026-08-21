"""Semantic shot planning for long-form explainers.

Narrative scenes are not editing cuts. This module maps exact narration
phrases to visual changes, guarantees a useful minimum shot length, and avoids
manufacturing jump cuts from repeated crops of one image.
"""

from __future__ import annotations

import re


RETENTION_ROLES = {
    "cold_consequence", "payoff", "prediction_gate", "rehook", "reversal",
    "false_relief", "final_escalation", "final_payoff", "resonant_end",
}
MIN_SHOT_SECONDS = 1.5
PURPOSES = ("setup", "action", "evidence", "consequence")


def select_alternate_image_indices(scenes: list[dict], max_images: int = 18) -> frozenset[int]:
    """Choose a bounded set of beats that have a real clause-specific B-roll need."""
    if max_images <= 0:
        return frozenset()
    ranked = []
    for i, scene in enumerate(scenes):
        role = str(scene.get("story_role") or "").lower()
        beats = _visual_beats(scene)
        explicit_broll = any(
            str(beat.get("source") or "").lower() in {"broll", "alternate"}
            and bool(beat.get("new_information", True))
            for beat in beats
        )
        if explicit_broll:
            priority = 0 if role in RETENTION_ROLES else 1
            ranked.append((priority, i))
    target = min(max_images, max(1, round(len(scenes) * 0.18)), len(ranked))
    return frozenset(i for _, i in sorted(ranked)[:target])


def _clean_token(value: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", value.lower())


def _script_words(narration: str) -> list[str]:
    return [word for word in str(narration or "").split() if word]


def _timed_words(narration: str, word_times: list | None, duration: float) -> list[tuple[str, float, float]]:
    """Prefer Whisper's spoken-word clock; fall back to an even script map."""
    words = _script_words(narration)
    if not words:
        return []
    if word_times:
        spoken = []
        try:
            for item in word_times:
                word, start, end = item[0], float(item[1]), float(item[2])
                if _clean_token(str(word)) and end > start:
                    spoken.append((str(word), max(0.0, start), min(duration, end)))
        except (IndexError, TypeError, ValueError):
            spoken = []
        if spoken:
            return spoken
    step = duration / len(words)
    return [(word, i * step, (i + 1) * step) for i, word in enumerate(words)]


def _find_phrase_span(timed: list[tuple[str, float, float]], phrase: str) -> tuple[float, float] | None:
    needle = [_clean_token(word) for word in str(phrase or "").split()]
    needle = [word for word in needle if word]
    haystack = [_clean_token(word) for word, _, _ in timed]
    if not needle:
        return None
    for start in range(0, len(haystack) - len(needle) + 1):
        if haystack[start:start + len(needle)] == needle:
            return timed[start][1], timed[start + len(needle) - 1][2]
    return None


def _derived_visual_beats(scene: dict) -> list[dict]:
    """Provider-free fallback: identify clause starts without inventing extra images."""
    narration = str(scene.get("narration") or "").strip()
    if not narration:
        return []
    clauses = [
        part.strip()
        for part in re.split(r"(?<=[.!?;:])\s+|\s+[—–]\s+", narration)
        if part.strip()
    ]
    if len(clauses) == 1:
        clauses = [
            part.strip()
            for part in re.split(
                r",\s+(?=(?:but|so|because|which|while|then)\b)",
                narration,
                flags=re.I,
            )
            if part.strip()
        ]
    beats = []
    for i, clause in enumerate(clauses[:4]):
        purpose = PURPOSES[min(i, len(PURPOSES) - 1)]
        beats.append({
            "anchor_phrase": " ".join(clause.split()[: min(7, len(clause.split()))]),
            "purpose": purpose,
            "visual": str(scene.get("visible_consequence") or scene.get("image_prompt") or ""),
            "source": "master",
            "new_information": i == 0,
        })
    return beats


def _visual_beats(scene: dict) -> list[dict]:
    beats = scene.get("visual_beats")
    if isinstance(beats, list):
        clean = [
            dict(beat)
            for beat in beats
            if isinstance(beat, dict) and beat.get("anchor_phrase")
        ]
        if clean:
            return clean
    return _derived_visual_beats(scene)


def semantic_broll_beat(scene: dict) -> dict:
    """Return the exact clause that should receive a genuinely different view."""
    for purpose in ("evidence", "consequence", "action"):
        for beat in _visual_beats(scene):
            if (
                str(beat.get("purpose") or "").lower() == purpose
                and bool(beat.get("new_information", True))
            ):
                return beat
    return {}


def _semantic_anchor(
    scene: dict,
    timed: list[tuple[str, float, float]],
    purposes: set[str],
) -> tuple[float, dict] | None:
    explicit = str(scene.get("motion_anchor_phrase") or "").strip()
    candidates = ([{"anchor_phrase": explicit, "purpose": "action"}] if explicit else []) + _visual_beats(scene)
    for beat in candidates:
        if str(beat.get("purpose") or "").lower() not in purposes:
            continue
        span = _find_phrase_span(timed, str(beat.get("anchor_phrase") or ""))
        if span:
            return span[0], beat
    return None


def _shot(
    kind: str,
    source: str,
    duration: float,
    role: str,
    *,
    start: float,
    purpose: str,
    anchor_phrase: str = "",
    transition: str = "continuous",
    semantic_aligned: bool = True,
    new_information: bool = False,
    motion: str | None = None,
) -> dict:
    return {
        "kind": kind,
        "source": source,
        "duration": round(duration, 3),
        "start_sec": round(start, 3),
        "end_sec": round(start + duration, 3),
        "motion": motion or ("generated_motion" if kind == "i2v" else "continuous_reframe"),
        "story_role": role,
        "purpose": purpose,
        "anchor_phrase": anchor_phrase,
        "transition": transition,
        "semantic_aligned": bool(semantic_aligned),
        "new_information": bool(new_information),
    }


def compile_scene_shots(
    scene: dict,
    duration: float,
    scene_index: int,
    *,
    has_i2v: bool = False,
    has_alternate: bool = False,
    i2v_seconds: float = 5.0,
    word_times: list | None = None,
) -> list[dict]:
    """Compile phrase-aligned shots for one narrated scene.

    A single source remains one continuous camera path. A hard cut is emitted
    only for clause-specific B-roll; generated motion uses a match-motion edit.
    Small remainders are absorbed into the generated clip instead of becoming
    flash frames.
    """
    del scene_index  # retained for API compatibility
    duration = max(0.05, float(duration))
    role = str(scene.get("story_role") or "").lower()
    timed = _timed_words(str(scene.get("narration") or ""), word_times, duration)

    if has_i2v:
        anchor = _semantic_anchor(scene, timed, {"action", "consequence"})
        anchor_time = anchor[0] if anchor else 0.0
        anchor_beat = anchor[1] if anchor else {}
        motion_len = min(float(i2v_seconds), duration)
        start = min(max(0.0, anchor_time), max(0.0, duration - motion_len))
        end = start + motion_len
        if 0 < start < MIN_SHOT_SECONDS:
            start = 0.0
        if 0 < duration - end < MIN_SHOT_SECONDS:
            end = duration
        if end - start < MIN_SHOT_SECONDS:
            start, end = 0.0, duration

        shots = []
        if start >= MIN_SHOT_SECONDS:
            shots.append(_shot(
                "still", "master", start, role, start=0.0, purpose="setup",
                transition="continuous", semantic_aligned=True, new_information=True,
                motion="locked",
            ))
        motion_start = shots[-1]["end_sec"] if shots else 0.0
        motion_end = min(duration, end + max(0.0, motion_start - start))
        shots.append(_shot(
            "i2v", "master", motion_end - motion_start, role, start=motion_start,
            purpose=str(anchor_beat.get("purpose") or "action"),
            anchor_phrase=str(
                anchor_beat.get("anchor_phrase")
                or scene.get("motion_anchor_phrase")
                or ""
            ),
            transition="match_motion" if shots else "continuous",
            semantic_aligned=bool(anchor) or not timed,
            new_information=True,
        ))
        tail = duration - motion_end
        broll_anchor = (
            _semantic_anchor(scene, timed, {"evidence", "consequence"})
            if has_alternate else None
        )
        broll_start = broll_anchor[0] if broll_anchor else None
        can_cut_to_broll = bool(
            broll_anchor
            and broll_start is not None
            and broll_start >= motion_start + MIN_SHOT_SECONDS
            and duration - broll_start >= MIN_SHOT_SECONDS
        )
        if can_cut_to_broll:
            motion_end = float(broll_start)
            shots[-1]["duration"] = round(motion_end - motion_start, 3)
            shots[-1]["end_sec"] = round(motion_end, 3)
            tail = duration - motion_end
        if tail > 0 and not can_cut_to_broll:
            shots[-1]["duration"] = round(float(shots[-1]["duration"]) + tail, 3)
            shots[-1]["end_sec"] = round(duration, 3)
            tail = 0.0
        if tail >= MIN_SHOT_SECONDS:
            beat = broll_anchor[1] if broll_anchor else {}
            shots.append(_shot(
                "still", "alternate", tail, role, start=motion_end,
                purpose=str(beat.get("purpose") or "evidence"),
                anchor_phrase=str(beat.get("anchor_phrase") or ""),
                transition="hard_cut", semantic_aligned=True,
                new_information=True,
            ))
        elif tail > 0:
            shots[-1]["duration"] = round(float(shots[-1]["duration"]) + tail, 3)
            shots[-1]["end_sec"] = round(duration, 3)
        return shots

    if has_alternate:
        anchor = _semantic_anchor(scene, timed, {"evidence", "consequence"})
        cut_at = anchor[0] if anchor else None
        if (
            cut_at is not None
            and cut_at >= MIN_SHOT_SECONDS
            and duration - cut_at >= MIN_SHOT_SECONDS
        ):
            beat = anchor[1] if anchor else {}
            return [
                _shot(
                    "still", "master", cut_at, role, start=0.0, purpose="setup",
                    transition="continuous", semantic_aligned=True, new_information=True,
                ),
                _shot(
                    "still", "alternate", duration - cut_at, role, start=cut_at,
                    purpose=str(beat.get("purpose") or "evidence"),
                    anchor_phrase=str(beat.get("anchor_phrase") or ""),
                    transition="hard_cut", semantic_aligned=bool(anchor),
                    new_information=True,
                ),
            ]

    return [_shot(
        "still", "master", duration, role, start=0.0, purpose="setup",
        transition="continuous", semantic_aligned=True, new_information=True,
    )]


def compile_shot_plan(
    scenes: list[dict],
    durations: list[float],
    *,
    i2v_indices: set[int] | frozenset[int] = frozenset(),
    alternate_indices: set[int] | frozenset[int] = frozenset(),
    i2v_seconds: float = 5.0,
    word_times: list[list] | None = None,
) -> list[list[dict]]:
    if len(scenes) != len(durations):
        raise ValueError("scenes and durations must have the same length")
    timings = word_times or [[] for _ in scenes]
    return [
        compile_scene_shots(
            scene,
            durations[i],
            i,
            has_i2v=i in i2v_indices,
            has_alternate=i in alternate_indices,
            i2v_seconds=i2v_seconds,
            word_times=timings[i] if i < len(timings) else None,
        )
        for i, scene in enumerate(scenes)
    ]


def shot_plan_metrics(plan: list[list[dict]]) -> dict:
    shots = [shot for scene in plan for shot in scene]
    stills = [float(s["duration"]) for s in shots if s["kind"] == "still"]
    motion = [float(s["duration"]) for s in shots if s["kind"] == "i2v"]
    cuts = [shot for scene in plan for shot in scene[1:]]
    hard_cuts = [shot for shot in cuts if shot.get("transition") == "hard_cut"]
    meaningful = [shot for shot in cuts if shot.get("new_information")]
    aligned = [shot for shot in cuts if shot.get("semantic_aligned")]
    anchored_motion = [shot for shot in shots if shot.get("kind") == "i2v"]
    aligned_motion = [shot for shot in anchored_motion if shot.get("semantic_aligned")]
    sub_min = [
        float(s["duration"])
        for s in shots
        if float(s["duration"]) < MIN_SHOT_SECONDS
    ]
    alternates = sum(1 for s in shots if s.get("source") == "alternate")
    return {
        "shot_count": len(shots),
        "cut_count": len(cuts),
        "hard_cut_count": len(hard_cuts),
        "still_shot_count": len(stills),
        "i2v_shot_count": len(motion),
        "alternate_shot_count": alternates,
        "broll_clause_count": alternates,
        "avg_still_seconds": round(sum(stills) / len(stills), 2) if stills else 0.0,
        "min_shot_seconds": round(
            min((float(s["duration"]) for s in shots), default=0.0),
            2,
        ),
        "max_still_seconds": round(max(stills), 2) if stills else 0.0,
        "sub_min_shot_count": len(sub_min),
        "semantic_sync_ratio": round(len(aligned) / len(cuts), 3) if cuts else 1.0,
        "meaningful_cut_ratio": round(len(meaningful) / len(cuts), 3) if cuts else 1.0,
        "motion_sync_ratio": round(
            len(aligned_motion) / len(anchored_motion),
            3,
        ) if anchored_motion else 1.0,
        "same_source_hard_cut_count": sum(
            1
            for scene in plan
            for previous, current in zip(scene, scene[1:])
            if (
                current.get("transition") == "hard_cut"
                and current.get("source") == previous.get("source")
            )
        ),
        "continuous_camera_paths": sum(
            1
            for scene in plan
            if len(scene) == 1 and scene[0].get("kind") == "still"
        ),
        "i2v_seconds": round(sum(motion), 2),
    }
