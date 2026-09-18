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


def _timed_words(narration: str, word_times: list | None, duration: float, *,
                 require_measured: bool = False) -> list[tuple[str, float, float]]:
    """Use measured speech timing; legacy callers may explicitly retain the even fallback."""
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
    if require_measured:
        raise ValueError("Measured word timings are required for long-form evidence shots.")
    step = duration / len(words)
    return [(word, i * step, (i + 1) * step) for i, word in enumerate(words)]


def _abort_on_unalignable() -> bool:
    """SHOT_TIMING_HARD=1 restores aborting when measured anchors cannot be spaced.

    Off by default: the fallback produces a watchable video with evenly spaced visuals, and the
    abort produced no video at all after the narration was paid for.
    """
    import os
    return (os.environ.get("SHOT_TIMING_HARD", "0") or "0").strip().lower() in (
        "1", "true", "yes", "on")


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
    # Was a flat clauses[:4] for any scene length -- the fallback copy of the defect the state
    # rule just lost. A scene long enough to need twenty states got four here too, and because
    # this path runs when the model returned no usable visual_beats, it is exactly the scene
    # least likely to have been planned densely in the first place. Take as many clauses as the
    # hold ceiling requires; the slice caps itself at however many the narration actually has.
    from longform_evidence import states_required_for_words
    wanted = max(4, states_required_for_words(len(narration.split())))
    for i, clause in enumerate(clauses[:wanted]):
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
    evidence_states: list[dict] | None = None,
    motion_state_ids: set[str] | frozenset[str] = frozenset(),
    require_measured_timing: bool | None = None,
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
    strict_timing = bool(evidence_states) if require_measured_timing is None \
        else bool(require_measured_timing)
    timed = _timed_words(
        str(scene.get("narration") or ""), word_times, duration,
        require_measured=strict_timing)

    accepted_states = [
        state for state in (evidence_states or [])
        if state.get("asset_status") in {"accepted", "reused_exact"}
    ]
    timing_degraded = False
    if accepted_states:
        count = len(accepted_states)
        if duration / count < MIN_SHOT_SECONDS:
            raise ValueError(
                f"{count} evidence states cannot fit {duration:.2f}s without sub-minimum cuts")
        spans = [_find_phrase_span(timed, str(state.get("anchor_phrase") or ""))
                 for state in accepted_states]
        starts = [0.0] + [span[0] if span else -1.0 for span in spans[1:]]
        valid = all(
            starts[index] >= starts[index - 1] + MIN_SHOT_SECONDS
            for index in range(1, len(starts))
        ) and duration - starts[-1] >= MIN_SHOT_SECONDS
        # REPAIR THE ONES THAT DO NOT FIT, KEEP THE ONES THAT DO.
        #
        # `valid` is a whole-scene verdict, and failing it threw away every measured start in the
        # scene. Measured on a real render: one scene missed by 0.01s -- its tail was 1.49s against
        # a 1.5s minimum -- and four cuts that had resolved exactly were re-spaced evenly and
        # reported unaligned. Another lost five to a single unresolvable anchor. Two scenes, nine
        # cuts, and the semantic-sync ratio read 27% for a cut whose timings were almost all right.
        #
        # A forward pass pushes each start to at least MIN after its predecessor; a backward pass
        # caps it so the remaining states still fit. Feasibility is already guaranteed by the
        # precheck above (duration / count >= MIN_SHOT_SECONDS), so no new constant appears here.
        #
        # This cannot launder the metric. A state that had to be MOVED no longer sits within 0.05s
        # of its phrase, so the per-shot check below reports it unaligned -- which is true, its
        # picture no longer lands on its words. Only states the repair did not touch keep their
        # credit, and they earned it. What changes is that one bad anchor stops costing its
        # neighbours their alignment.
        repaired_indexes = set()
        if not valid:
            for index in range(1, count):
                floor = starts[index - 1] + MIN_SHOT_SECONDS
                if not spans[index] or starts[index] < floor:
                    starts[index] = floor
                    repaired_indexes.add(index)
            for index in range(count - 1, 0, -1):
                ceiling = duration - (count - index) * MIN_SHOT_SECONDS
                if starts[index] > ceiling:
                    starts[index] = ceiling
                    repaired_indexes.add(index)
        monotone = all(
            starts[index] >= starts[index - 1] + MIN_SHOT_SECONDS - 1e-9
            for index in range(1, count)
        ) and duration - starts[-1] >= MIN_SHOT_SECONDS - 1e-9
        # A monotone repair can still be editorially catastrophic. If the last resolvable anchor
        # lands near the start, the old code considered [0, 1.5, 3.0] valid and assigned the whole
        # remaining scene to state three. The delivered failure was exactly [1.5, 1.5, 43.08].
        # Redistribute in that case: semantic placement is degraded honestly, but no surviving
        # neighbour inherits every rejected state's time.
        if monotone:
            from longform_evidence import MAX_VISUAL_STATE_SECONDS
            ends = starts[1:] + [duration]
            holds = [end - start for start, end in zip(starts, ends)]
            # Do not erase valid semantic timing merely because the PLAN was sparse; the rendered
            # gate must report that separate defect. This fallback is only for the collapse shape:
            # one neighbour inherits more than twice the scene's even share. That can happen after
            # states are dropped even when every surviving anchor is individually valid.
            has_long_tail = bool(holds) and max(holds) > max(
                MAX_VISUAL_STATE_SECONDS, 2.0 * duration / count) + 1e-9
            if has_long_tail:
                timing_degraded = True
                repaired_indexes = set(range(count))
                step = duration / count
                starts = [index * step for index in range(count)]
        if not valid and not monotone:
            # DEGRADE, do not abort. The even-spacing fallback below already existed and was
            # gated behind strict_timing, so a scene whose anchors landed slightly too close
            # destroyed a run that had already bought every second of its narration.
            #
            # Measured anchoring is better than even spacing -- a visual lands on the words that
            # describe it -- but it is a QUALITY difference, not a correctness one. Evenly spaced
            # visuals over correct narration is a watchable video; no video is not. The scene is
            # marked so the degradation is auditable rather than silent, and the old behaviour
            # remains available for a caller that needs measured anchoring or nothing.
            if strict_timing and _abort_on_unalignable():
                raise ValueError(
                    "Measured word timings cannot align every evidence state without invalid cuts.")
            timing_degraded = True
            repaired_indexes = set(range(1, count))
            step = duration / count
            starts = [index * step for index in range(count)]
        shots = []
        legacy_motion_index = next(
            (j for j, item in enumerate(accepted_states)
             if str(item.get("purpose") or "") in {"action", "consequence"}), 0)
        for index, state in enumerate(accepted_states):
            start = starts[index]
            end = starts[index + 1] if index + 1 < count else duration
            strategy = str(state.get("asset_strategy") or "master")
            kind = "still"
            state_id = str(state.get("state_id") or "")
            if state_id in motion_state_ids or (has_i2v and not motion_state_ids
                                                and index == legacy_motion_index):
                kind = "i2v"
            # Per shot, not per scene. The 0.05s test is the honest gate: a shot counts as
            # aligned when it actually begins where its phrase begins, whatever happened to its
            # neighbours. Dropping the old `and valid` conjunct is what lets a repaired scene keep
            # the cuts that were always right.
            phrase_aligned = bool(
                spans[index]
                and index not in repaired_indexes
                and ((index == 0 and float(spans[index][0]) <= 1.0)
                     or (index > 0 and abs(float(spans[index][0]) - start) <= 0.05))
            )
            # A detail reframe crops the shot immediately before it, so cutting to it shows the
            # same picture suddenly larger -- a jump cut. Measured on a real render, two of these
            # produced near-identical frames either side of the cut (mean pixel difference 16/255,
            # against 24-67 for genuine cuts). Marked here and honoured in
            # explainer_pipeline._make_multishot_background, which renders the move instead: the
            # camera starts on the master's full frame and pushes in until the frame IS the crop.
            #
            # Only when it crops its immediate predecessor. A reframe of some earlier asset is a
            # real change of picture and stays a cut; pushing from the wrong master would invent
            # a move the story did not ask for.
            follows_its_master = bool(
                index > 0
                and strategy == "detail_reframe"
                and str(state.get("source_asset_id") or "").strip()
                and str(state.get("source_asset_id") or "").strip()
                == str(accepted_states[index - 1].get("asset_id") or "").strip()
            )
            shot = _shot(
                kind, str(state.get("asset_id") or ""), end - start, role,
                start=start, purpose=str(state.get("purpose") or "evidence"),
                anchor_phrase=str(state.get("anchor_phrase") or ""),
                transition=("continuous" if index == 0 else
                            "push_to_detail" if follows_its_master else "hard_cut"),
                semantic_aligned=phrase_aligned,
                new_information=bool(state.get("verified_visible_information")),
                motion="generated_motion" if kind == "i2v" else "locked",
            )
            shot.update({
                "state_id": state.get("state_id"),
                "asset_strategy": strategy,
                "source_asset_id": state.get("source_asset_id") or "",
                "verified_visible_information": bool(state.get("verified_visible_information")),
            })
            # Auditable per shot, so a low ratio can be attributed rather than guessed at:
            # "even_fallback" means the repair could not fit and the whole scene was re-spaced,
            # "repaired" means this one start was moved to keep the scene monotone, and
            # "measured" means it sits on its own phrase.
            shot["timing_source"] = ("even_fallback" if timing_degraded
                                     else "repaired" if index in repaired_indexes
                                     else "measured")
            shots.append(shot)
        return shots

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
        transition="continuous", semantic_aligned=True, new_information=False,
    )]


def compile_shot_plan(
    scenes: list[dict],
    durations: list[float],
    *,
    i2v_indices: set[int] | frozenset[int] = frozenset(),
    alternate_indices: set[int] | frozenset[int] = frozenset(),
    i2v_seconds: float = 5.0,
    word_times: list[list] | None = None,
    evidence_states: list[list[dict]] | None = None,
    motion_state_ids: set[str] | frozenset[str] = frozenset(),
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
            evidence_states=(evidence_states[i] if evidence_states and i < len(evidence_states)
                             else None),
            motion_state_ids=motion_state_ids,
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
    # Clause B-roll on the evidence lane, which emits no shot whose literal source is "alternate".
    #
    # `alternates` counts a string set only by the two pre-evidence paths further down, so on any
    # lane that supplies evidence_states this metric was structurally zero -- not "this cut has no
    # B-roll", but "this metric cannot see this lane". Measured: a real illustrated render scored
    # broll_clause_count 0 with 17 planned states, 12 of them distinct generated assets.
    #
    # What actually counts here is a cut that carries NEW picture on the clause it belongs to, so
    # all three conjuncts are load-bearing and none is decorative:
    #   asset_strategy "distinct"          a separately generated asset, not a crop of its master
    #   verified_visible_information       the vision check confirmed it shows what it claims
    #   semantic_aligned                   it lands ON its narration clause, not on an even split
    # Dropping the third would count an evenly-spaced placement as clause B-roll, which is the
    # opposite of what the name means; it scored 6 instead of 2 on the audited run, crediting four
    # cuts that missed their clause. This version degrades honestly -- a future cut where every
    # B-roll shot is even-spaced scores zero, and that is the correct reading.
    evidence_broll = sum(
        1
        for scene in plan
        for s in scene[1:]
        if s.get("asset_strategy") == "distinct"
        and s.get("verified_visible_information")
        and s.get("semantic_aligned")
    )
    distinct_sources = {
        s.get("source") for s in shots
        if s.get("source") and s.get("asset_strategy") in {"master", "distinct"}
    }
    reframes = [s for s in shots if s.get("asset_strategy") == "detail_reframe"]
    return {
        "shot_count": len(shots),
        "cut_count": len(cuts),
        "hard_cut_count": len(hard_cuts),
        "still_shot_count": len(stills),
        "i2v_shot_count": len(motion),
        "alternate_shot_count": alternates,
        "distinct_source_count": len(distinct_sources),
        "reframe_shot_count": len(reframes),
        "verified_information_shot_count": sum(
            1 for shot in shots if shot.get("verified_visible_information")),
        "broll_clause_count": alternates + evidence_broll,
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
                and (
                    current.get("source") == previous.get("source")
                    or current.get("source_asset_id") == previous.get("source")
                )
            )
        ),
        "continuous_camera_paths": sum(
            1
            for scene in plan
            if len(scene) == 1 and scene[0].get("kind") == "still"
        ),
        "i2v_seconds": round(sum(motion), 2),
    }
