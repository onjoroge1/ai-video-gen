"""The causal lane's wiring into the real long-form script path.

`_generate_script_chunked` serves every landscape explainer, so the causal fields have to be
strictly additive: with `causal_lane=False` the beat prompt must come out byte-identical to what
the cinematic lane has always sent. These tests capture the prompt the pipeline actually builds
rather than asserting on the source, so a stray concatenation shows up here.
"""
import json
import re
from pathlib import Path

import pytest

import causal_story as cs
import explainer_pipeline as ep


class _Abort(RuntimeError):
    """Raised after the first model call so the test never proceeds to paid expansion."""


def _capture_beat_prompt(monkeypatch, **kwargs):
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            raise _Abort

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    with pytest.raises(_Abort):
        ep._generate_script_chunked("Why did the plan fail?", 200, "engaging", "", 14, **kwargs)
    return seen["prompt"]


def test_cinematic_lane_prompt_is_unchanged_by_the_causal_wiring(monkeypatch):
    prompt = _capture_beat_prompt(monkeypatch)
    # Note: the cinematic prompt has its own "HUMAN-LED CAUSAL SPINE" block, which asks for
    # BUT/THEREFORE/SO connections in prose. The declared chain is the checkable version of the
    # same idea and carries a distinct name so the two can never be confused here.
    assert "HUMAN-LED CAUSAL SPINE" in prompt
    for token in ("causal_role", "DECLARED CAUSAL CHAIN", "caused_by", '"chapter"'):
        assert token not in prompt, f"{token!r} leaked into the cinematic lane prompt"


def test_causal_lane_prompt_asks_for_the_chain(monkeypatch):
    import event_functions as ef
    prompt = _capture_beat_prompt(monkeypatch, causal_lane=True)
    assert '"caused_by"' in prompt and '"event_function"' in prompt
    for field in ('"causal_role"', '"role"', '"mechanism_beat"'):
        assert field not in prompt
    for function in ef.map_for("backfiring_solution").required:
        assert function in prompt
    assert "rewarded_measure" in prompt and "goal_claim_refs" in prompt
    assert "stated_policy_goal" in prompt and "same facts" in prompt


def test_the_causal_prompt_drops_the_rival_mechanism_window(monkeypatch):
    """The causal prompt must not inherit a competing cinematic order or timing contract.

    FIXED ARCHITECTURE used to assign the mechanism to 40-55% while rule C, ~100 lines earlier,
    demanded it inside the engine's deadline. Both unconditional, neither referencing the other.
    Four measured runs landed the principle near 35% -- the average of the two -- and twelve
    renders died on LATE_MECHANISM before the contradiction was found. Raising rule C's deadline
    made it WORSE (43s -> 55s), which is the signature of a second instruction pulling the other
    way.
    """
    plain = _capture_beat_prompt(monkeypatch)
    causal = _capture_beat_prompt(monkeypatch, causal_lane=True)

    assert "40-55% mechanism" in plain, "the cinematic lane keeps its own tuned architecture"
    assert "40-55% mechanism" not in causal, "the rival window must not reach the causal lane"

    # The remaining cinematic reversal -> escalation architecture conflicted too.
    for conflict in ("40-55% third payoff + a reversal", "0-8% COLD CONSEQUENCE",
                     "28-40% first escalation", "STANDARD EXPLAINER. Deliver the first useful"):
        assert conflict not in causal
    assert "The compiler assigns story roles" in causal
    assert "Do not supply a hinge, mechanism, tool" in causal


def test_the_prompt_states_exactly_one_mechanism_deadline(monkeypatch):
    import story_engines as se
    import event_functions as ef
    for engine_id in se.ENGINES:
        prompt = _capture_beat_prompt(monkeypatch, causal_lane=True, pinned_engine=engine_id)
        if ef.map_for(engine_id):
            assert '"mechanism_beat"' not in prompt
            continue
        stated = set(re.findall(r"pct [Mm][Uu][Ss][Tt] be under (\d+)", prompt))
        expected = int(round(se.mechanism_deadline_pct(se.get(engine_id), cs.MECHANISM_DEADLINE_PCT) * 100))
        assert stated == {str(expected)}
        assert "40-55% mechanism" not in prompt


def _sheet(n_beats):
    """A beat sheet in the shape the planner returns, carrying a declared chain."""
    roles = ["setup", "intervention", "false_resolution", "hinge", "mechanism",
             "escalation", "escalation", "escalation", "reversal", "tool"]
    chapters = [1, 1, 1, 1, 1, 2, 2, 3, 3, 4]
    return {
        "title": "T", "hook": "One sentence that promises the turn.", "style_mode": "educational",
        "throughline": "t", "opening_object": "the workshop table",
        "final_callback_object": "the workshop table", "human_subject": "Alex",
        "stages": ["ONE", "TWO"], "peak_scene": 7, "payoffs": [3, 8],
        "beats": [{
            "n": i + 1, "pct": int(i / n_beats * 100), "beat": f"beat {i + 1}",
            "role": "escalation", "causal_role": roles[i % len(roles)],
            "caused_by": 0 if i == 0 else i, "chapter": chapters[i % len(chapters)],
            "human_present": True, "human_intention": "solve it", "human_belief": "b",
            "expected_outcome": "e", "actual_outcome": "a", "continuity_anchor": "table",
            "causal_link": "therefore", "bolt_mode": "absent", "claim_refs": [],
            "evidence_id": "", "question_opened": "", "question_answered": "",
            "new_complication": "", "visible_consequence": "v", "opens_loop": "",
            "closes_loop": "",
        } for i in range(n_beats)],
    }


def test_beat_numbers_become_scene_ids_the_storyboard_can_resolve(monkeypatch):
    """The planner reasons in beat numbers; the storyboard resolves the chain by scene id.

    The translation happens once, at the merge. If it drifts, every `caused_by` edge dangles at
    the same time and the storyboard fails with DANGLING_CAUSE on every scene.
    """
    n_beats = 10

    class _Messages:
        def create(self, **call):
            return _reply(_route(call["messages"][0]["content"], n_beats))

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    script = ep._generate_script_chunked("Why did the plan fail?", 200, "engaging", "", n_beats,
                                         causal_lane=True)

    scenes = script["scenes"]
    assert scenes[0]["scene_id"] == "scene_001"
    assert scenes[0]["caused_by"] == "", "the setup starts the chain"
    assert scenes[3]["caused_by"] == "scene_003"
    assert scenes[0]["causal_role"] == "setup"
    assert scenes[3]["chapter"] == 1 and scenes[5]["chapter"] == 2

    # Every declared parent must resolve to a scene that exists, which is what the chain check
    # in causal_story asserts and what a drifting translation would break.
    ids = {scene["scene_id"] for scene in scenes}
    assert all(scene["caused_by"] in ids for scene in scenes[1:])


def test_cinematic_scenes_carry_no_causal_fields(monkeypatch):
    """The other lane must not gain fields it never asked for."""
    n_beats = 10

    class _Messages:
        def create(self, **call):
            return _reply(_route(call["messages"][0]["content"], n_beats))

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    script = ep._generate_script_chunked("Why did the plan fail?", 200, "engaging", "", n_beats)
    assert all("causal_role" not in scene and "caused_by" not in scene
               for scene in script["scenes"])


def _reply(payload):
    usage = type("U", (), {"input_tokens": 1, "output_tokens": 1})()
    block = type("B", (), {"text": json.dumps(payload)})()
    return type("R", (), {"content": [block], "usage": usage})()


def _spine(n_beats):
    roles = ["setup", "intervention", "false_resolution", "hinge", "mechanism",
             "escalation", "escalation", "escalation", "reversal", "tool"]
    chapters = [1, 1, 1, 1, 1, 2, 2, 3, 3, 4]
    return {"spine": [{"n": i + 1, "causal_role": roles[i % len(roles)],
                       "caused_by": i, "chapter": chapters[i % len(chapters)]}
                      for i in range(n_beats)],
            "parallel_cases": []}


def _route(prompt, n_beats):
    """Dispatch on what the prompt asks for, so adding a call cannot silently break the mock."""
    if ("Design a SCENE-BY-SCENE BEAT SHEET" in prompt
                    or "Plan the sourced factual events" in prompt):
        return _sheet(n_beats)
    if "Label the CAUSAL CHAIN" in prompt:
        return _spine(n_beats)
    return {"scenes": [{"narration": f"Line {i + 1} of the story here.", "image_prompt": "p",
                        "scene_type": "real_world_example", "environment_type": "city",
                        "text_overlay": "X", "text_sub": "", "shot_type": "medium"}
                       for i in range(n_beats)]}


def _capture_expansion_prompt(monkeypatch, **kwargs):
    """Capture the call that writes narration, whichever ordinal it now is."""
    seen = {}

    class _Messages:
        def create(self, **call):
            prompt = call["messages"][0]["content"]
            if ("Design a SCENE-BY-SCENE BEAT SHEET" not in prompt
                    and "Label the CAUSAL CHAIN" not in prompt
                    and "Plan the sourced factual events" not in prompt):
                seen["prompt"] = prompt
                raise _Abort
            return _reply(_route(prompt, 10))

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    with pytest.raises(_Abort):
        ep._generate_script_chunked("Why did the plan fail?", 200, "engaging", "", 10, **kwargs)
    return seen["prompt"]


def test_the_spoken_chapter_rule_reaches_the_call_that_writes_narration(monkeypatch):
    """Found by the end-to-end run: six correct chapters in the plan, zero spoken markers.

    The beat sheet plans; the expansion writes narration. A rule about what the narrator SAYS
    placed only on the beat sheet never reaches the call that writes the words, so every chapter
    opened on prose and the transcript rubric measured 0 step markers against a band of 4-8.
    """
    expansion = _capture_expansion_prompt(monkeypatch, causal_lane=True)
    assert "OPEN EACH NEW CHAPTER OUT LOUD" in expansion
    assert '"Step one."' in expansion


def test_the_cinematic_expansion_prompt_gains_nothing(monkeypatch):
    expansion = _capture_expansion_prompt(monkeypatch)
    assert "OPEN EACH NEW CHAPTER OUT LOUD" not in expansion


def test_the_beat_sheet_offers_somewhere_to_put_parallel_cases(monkeypatch):
    """A generalization beat could not carry cases, because no field for them existed."""
    prompt = _capture_beat_prompt(monkeypatch, causal_lane=True)
    assert '"parallel_cases"' in prompt
    assert f"at least {cs.MIN_PARALLEL_CASES}" in prompt
    assert '"parallel_cases"' not in _capture_beat_prompt(monkeypatch)


def test_singleton_roles_are_stated_as_a_countable_check(monkeypatch):
    prompt = _capture_beat_prompt(monkeypatch, causal_lane=True)
    assert "each required function exactly once" in prompt
    assert "Do not pad" in prompt


def test_the_hinge_word_cap_reaches_the_call_that_writes_narration(monkeypatch):
    """Same class of bug as the spoken chapter marker, found the same way.

    The spine pass decides WHICH beat is the hinge; the expansion writes its words. Without the
    cap on the expansion prompt the hinge came back at 24 words against a 10-word contract.
    """
    expansion = _capture_expansion_prompt(monkeypatch, causal_lane=True)
    assert "THE HINGE IS ONE SHORT SENTENCE" in expansion
    assert f"AT MOST {cs.MAX_HINGE_WORDS} words" in expansion
    assert "THE HINGE IS ONE SHORT SENTENCE" not in _capture_expansion_prompt(monkeypatch)


def test_the_spine_results_survive_onto_the_returned_script(monkeypatch):
    """Stored on beats[0], which is never returned — scenes are, and they copy named fields only."""
    n_beats = 10

    class _Messages:
        def create(self, **call):
            prompt = call["messages"][0]["content"]
            if "Label the CAUSAL CHAIN" in prompt:
                payload = _spine(n_beats)
                payload["parallel_cases"] = [
                    {"domain": "d1", "problem": "p", "solution": "s", "result": "r"},
                    {"domain": "d2", "problem": "p", "solution": "s", "result": "r"}]
                return _reply(payload)
            return _reply(_route(prompt, n_beats))

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    script = ep._generate_script_chunked("Why did the plan fail?", 200, "engaging", "", n_beats,
                                         causal_lane=True)
    assert len(script["_parallel_cases"]) == 2
    assert isinstance(script["_causal_repairs"], list)


def test_the_hinge_carries_its_own_word_budget(monkeypatch):
    """A separate rule lost to "each narration is about N words" in two live runs.

    Stating the exception inside the budget sentence, and carrying the number on the beat itself,
    leaves nothing for the writer to reconcile.
    """
    expansion = _capture_expansion_prompt(monkeypatch, causal_lane=True)
    assert 'Use each assigned narration_words as its individual word budget' in expansion
    assert f'"narration_words": {cs.MAX_HINGE_WORDS}' in expansion.replace("'", '"')
    assert "narration_words" not in _capture_expansion_prompt(monkeypatch)


# --- fact-check flip ---------------------------------------------------------------------------

def test_sourcing_is_required_on_the_illustrated_lane_only():
    """The recovery profile demoted every gate so the default lane could finish.

    That was aimed at editorial opinion and missing reference art. Sourcing is a different claim:
    a causal story asserts one event caused the next, so this lane opts back in.
    """
    assert ep._ordinary_research_mode(True, illustrated_story_on=False) == "best_effort"
    assert ep._ordinary_research_mode(True, illustrated_story_on=True) == "required"
    # A lane that was never on the recovery profile is unaffected either way.
    assert ep._ordinary_research_mode(False, illustrated_story_on=False) == "required"


def test_editorial_gates_stay_advisory_while_sourcing_gates_rearm():
    """The split is the point: block on FALSE or BROKEN, score everything else.

    Guards the classification itself. If a later edit flips the retention contract or the
    rendered-opening approval onto the sourcing flag, the default lane silently stops finishing —
    which is the exact failure the recovery profile was written to end.
    """
    source = (Path(ep.__file__)).read_text(encoding="utf-8")
    assert source.count("not sourcing_advisory") == 9, "sourcing gate count changed"

    # Counting is not enough: a count-only assertion passed while the retention contract's
    # post-TTS twin had been swept onto the sourcing flag, because the total was still right.
    # Assert WHICH gates read which flag, inside the pipeline function where the flags exist.
    import re
    body_start = source.index("def run_explainer_pipeline(")
    body = source[body_start:]
    # Exclude the definition: the naive pattern also matched "def _longform_retention_hard()".
    retention_sites = [m.start() for m in re.finditer(r"_longform_retention_hard\(\)", body)
                       if "def " not in body[max(0, m.start() - 4):m.start()]]
    assert len(retention_sites) >= 2, "expected the pre-TTS and post-TTS retention twins"
    for start in retention_sites:
        # Strip comments before matching. A fixed window over raw source was already wrong once in
        # this file — a comment grew and failed a correct call site — and repeating it here would
        # make the test measure comment length instead of the condition.
        window = "\n".join(line for line in body[start:start + 900].splitlines()
                           if not line.strip().startswith("#"))[:220]
        assert "not stable_standard_longform" in window, (
            "a retention check inside the pipeline reads the sourcing flag; retention is "
            "editorial and stays advisory")

    # A THIRD retention check lives in a runtime-rewrite helper outside this function and reads
    # neither profile flag, because neither is in its scope. Found by strengthening this test.
    # Recorded rather than silently accepted: on the recovery profile it can still block on an
    # editorial contract that both siblings treat as advisory.
    helper_sites = [m.start() for m in re.finditer(r"_longform_retention_hard\(\)", source)
                    if m.start() < body_start
                    and "def " not in source[max(0, m.start() - 4):m.start()]]
    assert len(helper_sites) == 1, (
        "the profile-unaware retention check count changed; if one was added or removed, decide "
        "deliberately whether it should read the recovery flag")


def test_the_sourcing_flag_is_derived_not_hardcoded():
    source = (Path(ep.__file__)).read_text(encoding="utf-8")
    assert "sourcing_advisory = stable_standard_longform and not illustrated_story_on" in source


def test_the_hook_word_cap_reaches_the_field_that_defines_the_hook(monkeypatch):
    """Fourth instance of one bug class, so it gets its own guard.

    The cap lived in the story direction while the beat sheet defined the hook as "One-sentence
    YouTube description hook" with no limit, and a live run returned twenty words.
    """
    prompt = _capture_beat_prompt(monkeypatch, causal_lane=True)
    assert f"at most {cs.MAX_HOOK_WORDS} words" in prompt
    assert f"at most {cs.MAX_HOOK_WORDS} words" not in _capture_beat_prompt(monkeypatch)


def test_the_spine_prompt_offers_the_engines_and_demands_one(monkeypatch):
    import story_engines as se
    prompts = []

    class _Messages:
        def create(self, **call):
            prompt = call["messages"][0]["content"]
            prompts.append(prompt)
            if "Label the CAUSAL CHAIN" in prompt:
                raise _Abort
            return _reply(_route(prompt, 10))

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    with pytest.raises(_Abort):
        ep._generate_script_chunked("Why did the plan fail?", 200, "engaging", "", 10,
                                    causal_lane=True)
    spine = prompts[-1]
    for engine_id in se.ENGINES:
        assert engine_id in spine
    assert "Do not blend two" in spine
    assert "WALK YOUR LABELS ONCE MORE" in spine


def test_an_explicit_research_override_wins_on_every_lane(monkeypatch):
    """A lane may choose its own default; it may not quietly ignore the operator.

    The first version returned "required" for the illustrated lane before reading the
    environment, so a run started with LONGFORM_RESEARCH_MODE=off called the provider anyway —
    the override the docstring promised did nothing.
    """
    monkeypatch.setenv("LONGFORM_RESEARCH_MODE", "off")
    assert ep._ordinary_research_mode(True, illustrated_story_on=True) == "off"
    assert ep._ordinary_research_mode(True, illustrated_story_on=False) == "off"

    # But only WITHIN the recovery profile. A lane that was never in it promises sourced evidence
    # and stays fail-closed whatever is exported — an env var must not be able to turn sourcing
    # off for Evidence Mystery, social or controlled pilots.
    assert ep._ordinary_research_mode(False, illustrated_story_on=True) == "required"
    assert ep._ordinary_research_mode(False, illustrated_story_on=False) == "required"

    # With no override the lane defaults stand: required for illustrated, best-effort otherwise.
    monkeypatch.delenv("LONGFORM_RESEARCH_MODE", raising=False)
    assert ep._ordinary_research_mode(True, illustrated_story_on=True) == "required"
    assert ep._ordinary_research_mode(True, illustrated_story_on=False) == "best_effort"

    # A meaningless value is ignored rather than obeyed.
    monkeypatch.setenv("LONGFORM_RESEARCH_MODE", "banana")
    assert ep._ordinary_research_mode(True, illustrated_story_on=False) == "best_effort"


def _call_body(source, start):
    """The full argument list of a call, found by paren balance.

    A fixed character window was tried first and was immediately wrong: adding a comment inside
    the call pushed the argument past the window and failed a call site that was correct. A test
    that breaks when a comment grows is measuring the wrong thing.
    """
    depth, index = 0, source.index("(", start)
    for position in range(index, len(source)):
        if source[position] == "(":
            depth += 1
        elif source[position] == ")":
            depth -= 1
            if depth == 0:
                return source[start:position + 1]
    return source[start:]


def test_every_landscape_script_call_site_carries_the_lane():
    """A replan is still a script for the same lane.

    The flag was threaded into the first generate_script call and missed on the replan, so a
    contract score under threshold silently rebuilt all 22 scenes through the plain path with no
    causal_role, caused_by or chapter. The pilot got past research, fact-check and the runtime
    contract before failing on a blank role for every scene.

    The social call site is deliberately excluded: it hardcodes video_format="social" and this
    lane is landscape-only, so it can never serve an illustrated run.
    """
    import re
    source = Path(ep.__file__).read_text(encoding="utf-8")
    checked = 0
    for match in re.finditer(r"generate_script\(", source):
        start = match.start()
        if "def " in source[max(0, start - 40):start]:
            continue
        body = _call_body(source, start)
        if 'video_format="social"' in body or "question, duration_sec, style" not in body:
            continue
        checked += 1
        assert "causal_lane" in body, (
            f"a landscape generate_script call omits causal_lane:\n{body[:200]}")
    assert checked >= 2, f"expected the initial call and the replan, checked {checked}"


def test_the_research_cache_key_includes_the_request(tmp_path, monkeypatch):
    """Keying on the question alone meant a better research prompt changed nothing.

    Measured: the claim target was raised and comparable-case claims added, a fresh run produced
    16 verified claims, and the very next run silently reused an 8-claim dossier from before both
    changes and failed on six unbound scenes. Fingerprinting the request makes a prompt change
    invalidate its own cache without anyone bumping a version.
    """
    monkeypatch.setenv("RESEARCH_CACHE_DIR", str(tmp_path))
    same_q = "Why did the Aral Sea disappear?"
    assert ep._research_cache_path(same_q, "ask for 12-18 claims") != \
        ep._research_cache_path(same_q, "ask for 22-28 claims and comparable cases")
    # Same question and same request still hit the same entry, which is the point of the cache.
    assert ep._research_cache_path(same_q, "req") == ep._research_cache_path(same_q, "req")
    # And a different question still separates, as before.
    assert ep._research_cache_path(same_q, "req") != ep._research_cache_path("Other?", "req")


def _draft(mechanism_at_scene, hinge_words=6, scenes=12):
    """A causal-lane script whose mechanism position and hinge length are controllable.

    Scene lengths are NOT uniform, deliberately. The mechanism deadline is a fraction of runtime
    and runtime comes from word counts, so equal-length scenes push the mechanism past the first
    fifth no matter where it sits — the fixture would fail the check it exists to exercise. Shaped
    like the references instead: a brisk opening, then long escalations.
    """
    roles = ["setup", "intervention", "false_resolution", "hinge", "mechanism"] + \
            ["escalation"] * (scenes - 7) + ["reversal", "tool"]
    roles = roles[:scenes]
    # MOVE the mechanism rather than adding one: assigning the role without clearing the default
    # produced two mechanisms, so the draft failed on DUPLICATE_ROLE and never exercised the
    # deadline this fixture exists to test.
    roles = ["escalation" if role == "mechanism" else role for role in roles]
    roles[mechanism_at_scene] = "mechanism"
    seen_mechanism = False
    out = []
    for index, role in enumerate(roles):
        if role == "hinge":
            narration = " ".join(["turn"] * hinge_words) + "."
        elif role == "tool":
            narration = "So look back at the workshop table and ask what it was rewarding."
        else:
            # Short before the mechanism lands, long after: the shape the references use.
            words = 12 if not seen_mechanism else 60
            narration = " ".join((
                "the situation changes again because of the step before it here now "
            ).split() * 10)
            narration = " ".join(narration.split()[:words]) + "."
        if role == "mechanism":
            seen_mechanism = True
        out.append({"scene_id": f"scene_{index + 1:03d}", "causal_role": role,
                    "chapter": min(4, index // 3 + 1),
                    "caused_by": "" if index == 0 else f"scene_{index:03d}",
                    "narration": narration, "human_intention": "solve it",
                    "environment_type": "home"})
    return {"title": "T", "hook": "One sentence that promises the turn here.",
            "_story_contract": {"human_subject": "Alex", "subject_goal": "solve it",
                                "accepted_belief": "it should work",
                                "opening_object": "the workshop table"},
            "scenes": out}


def test_the_causal_report_is_non_mutating():
    """The replan compares two drafts; inspecting one must not mark a draft it may discard."""
    draft = _draft(4)
    before = json.dumps(draft, sort_keys=True)
    ep._causal_contract_report(draft, "why?")
    assert json.dumps(draft, sort_keys=True) == before


def test_the_causal_report_separates_a_sound_draft_from_a_late_mechanism():
    ok, _ = ep._causal_contract_report(_draft(4), "why?")
    assert ok is True
    late_ok, errors = ep._causal_contract_report(_draft(9), "why?")
    assert late_ok is False
    assert any("LATE_MECHANISM" in str(e) for e in errors)


def test_causal_validity_outranks_the_contract_score(monkeypatch):
    """The defect: a candidate scoring better on pacing replaced a causally sound draft.

    A replan told only about the long-form contract fixed pacing and pushed the mechanism from
    inside the deadline out to 82 seconds, so the run cleared the contract it was shown and died
    on the one it was not.
    """
    sound, broken = _draft(4), _draft(9)
    assert ep._causal_contract_report(sound, "why?")[0] is True
    assert ep._causal_contract_report(broken, "why?")[0] is False

    calls = {"n": 0}
    def fake_generate_script(*args, **kwargs):
        calls["n"] += 1
        return json.loads(json.dumps(sound if calls["n"] == 1 else broken))

    # The broken candidate is made to look BETTER on the long-form contract, which is exactly the
    # trade the old ranking accepted.
    def fake_validate(script, question):
        is_broken = script["scenes"][9]["causal_role"] == "mechanism"
        return {"passed": False, "score": 90 if is_broken else 40, "errors": []}

    monkeypatch.setattr(ep, "generate_script", fake_generate_script)
    monkeypatch.setattr(ep, "validate_longform_story", fake_validate)
    monkeypatch.setattr(ep, "validation_rank", lambda v: -v["score"])
    monkeypatch.setattr(ep, "grade_script", lambda *a, **k: None)
    monkeypatch.setattr(ep, "_LONGFORM_CONTRACT_RETRIES", 1)

    result = ep.generate_graded_script("why?", 200, "s", "", "landscape", "",
                                       causal_lane=True)
    # The higher-scoring but causally broken candidate must be refused.
    assert result["scenes"][4]["causal_role"] == "mechanism", "kept the late-mechanism draft"
    assert ep._causal_contract_report(result, "why?")[0] is True


# --- script cache -------------------------------------------------------------------------------

def test_the_script_cache_is_off_by_default_and_under_pytest(monkeypatch):
    """A script is the creative output, not evidence.

    The research cache is on by default because a question's evidence does not change between
    renders. Serving the same SCRIPT for every render of a topic is a product decision, so this
    one stays opt-in. And like the research cache it refuses to run under pytest, where a stubbed
    generator writes a valid script the cache would then serve instead of the thing under test.
    """
    monkeypatch.delenv("SCRIPT_CACHE", raising=False)
    assert ep._script_cache_enabled() is False
    monkeypatch.setenv("SCRIPT_CACHE", "1")
    assert ep._script_cache_enabled() is False, "must stay off while PYTEST_CURRENT_TEST is set"


def test_the_script_fingerprint_covers_what_would_make_a_reuse_wrong():
    base = dict(duration_sec=200, video_format="landscape", story_format="standard_explainer",
                causal_lane=True, operator_direction="", research_dossier={"claims": [{"claim_id": "c01"}]})
    same = ep._script_fingerprint(**base)
    assert same == ep._script_fingerprint(**base)

    for field, value in (("duration_sec", 300), ("video_format", "social"),
                         ("story_format", "evidence_led_mystery"), ("causal_lane", False),
                         ("operator_direction", "be funny")):
        assert ep._script_fingerprint(**{**base, field: value}) != same, field

    # A different evidence ledger is a different script.
    assert ep._script_fingerprint(**{**base, "research_dossier": {"claims": [{"claim_id": "c99"}]}}) != same
    # Claim ORDER is not meaningful, so it must not split the cache.
    reordered = {"claims": [{"claim_id": "c02"}, {"claim_id": "c01"}]}
    forward = {"claims": [{"claim_id": "c01"}, {"claim_id": "c02"}]}
    assert ep._script_fingerprint(**{**base, "research_dossier": reordered}) == \
        ep._script_fingerprint(**{**base, "research_dossier": forward})


def test_the_fingerprint_tracks_the_prompt_source():
    """Editing a prompt must invalidate scripts it produced — the lesson the dossier cache taught.

    Keyed on inputs alone, an improved beat-sheet prompt would keep serving scripts written before
    the change, exactly as an 8-claim dossier survived a raised claim target and cost a pilot run.
    """
    import inspect
    source = inspect.getsource(ep._script_fingerprint)
    assert "_generate_script_chunked" in source and "_assign_causal_spine" in source
    assert "inspect.getsource" in source


def test_the_sheets_planned_mechanism_slot_is_pinned(monkeypatch):
    """The sheet plans where the principle lands and the pin enforces it over loose beats.

    Pinning only overwrites connective tissue. Writing the mechanism onto a required singleton was
    measured destroying the chain — it left the story with no false resolution, so repair demoted
    the hinge that then had nothing to break.

    The spine pass sees beat text without runtime, so it cannot judge a deadline expressed as a
    fraction of runtime. Four measured runs of letting it choose put the mechanism near 35% every
    time. The sheet knows each beat's pct, so the sheet plans the slot and this enforces it.
    """
    n_beats = 10
    sheet = _sheet(n_beats)
    sheet["mechanism_beat"] = 6               # a beat the labeller left as connective tissue

    class _Messages:
        def create(self, **call):
            prompt = call["messages"][0]["content"]
            # Serve the sheet built ABOVE, not a fresh one. Falling through to _route rebuilt the
            # sheet without the mechanism_beat this test exists to set, so the pin had nothing to
            # act on and the test failed against working code.
            if ("Design a SCENE-BY-SCENE BEAT SHEET" in prompt
                    or "Plan the sourced factual events" in prompt):
                return _reply(sheet)
            if "Label the CAUSAL CHAIN" in prompt:
                # The labelling pass disagrees and puts the mechanism late.
                spine = _spine(n_beats)
                for row in spine["spine"]:
                    if row["causal_role"] == "mechanism":
                        row["causal_role"] = "escalation"
                spine["spine"][8]["causal_role"] = "mechanism"
                return _reply(spine)
            return _reply(_route(prompt, n_beats))

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    script = ep._generate_script_chunked("Why did the plan fail?", 200, "engaging", "", n_beats,
                                         causal_lane=True)
    roles = [scene["causal_role"] for scene in script["scenes"]]
    assert roles.count("mechanism") == 1, roles
    assert roles[5] == "mechanism", f"expected the planned beat 6 to be pinned, got {roles}"


def test_the_beat_sheet_declares_the_slot_only_on_this_lane(monkeypatch):
    factual = _capture_beat_prompt(monkeypatch, causal_lane=True)
    legacy = _capture_beat_prompt(monkeypatch, causal_lane=True, pinned_engine="accidental_invention")
    assert '"mechanism_beat"' not in factual
    assert '"mechanism_beat"' in legacy and "structural slot like peak_scene" in legacy
    assert '"mechanism_beat"' not in _capture_beat_prompt(monkeypatch)


def test_the_storyboard_gate_has_an_escape_hatch_like_its_siblings(monkeypatch):
    """Blocks by default; ILLUSTRATED_STORYBOARD_HARD=0 downgrades it to a report.

    Every other pre-spend gate here already has one. Without it, thirteen consecutive runs stopped
    before the renderer and no frame was ever produced, so the imagery and cadence questions the
    lane exists to answer stayed unexamined.
    """
    monkeypatch.delenv("ILLUSTRATED_STORYBOARD_HARD", raising=False)
    assert ep._illustrated_storyboard_hard() is True
    for value in ("0", "false", "off", "no"):
        monkeypatch.setenv("ILLUSTRATED_STORYBOARD_HARD", value)
        assert ep._illustrated_storyboard_hard() is False, value
    monkeypatch.setenv("ILLUSTRATED_STORYBOARD_HARD", "1")
    assert ep._illustrated_storyboard_hard() is True


# --- PR2: the acceptance filter ------------------------------------------------------------------

def test_the_illustrated_lane_judges_identity_by_silhouette_not_faces():
    """46 of 62 evidence images were rejected for having blank faces — the style working.

    Only accepted states become shots (longform_shots.compile_scene_shots), so those rejections
    collapsed a planned 3.5s cadence to 7.79s against references at 2.36s and 3.38s. The verifier
    was applying a photoreal standard to a deliberately non-photoreal lane.
    """
    import inspect
    source = inspect.getsource(ep.verify_evidence_asset)
    assert "identity_by_silhouette" in source

    # Simple facial detail remains compatible with the channel's own character design.
    assert "IDENTITY RULE FOR THIS IMAGE" in source
    assert "Simplified facial detail must not be a reason" in source
    assert "clothing colour, silhouette, headwear" in source

    # And it must be OFF by default, so the cinematic lane keeps its photoreal standard.
    signature = inspect.signature(ep.verify_evidence_asset)
    assert signature.parameters["identity_by_silhouette"].default is False


def test_every_verifier_call_site_passes_the_lane():
    """Threading a flag into one of two call sites is how the replan bug happened before."""
    import re
    source = Path(ep.__file__).read_text(encoding="utf-8")
    calls = [m.start() for m in re.finditer(r"verify_evidence_asset\(", source)
             if "def " not in source[max(0, m.start() - 4):m.start()]]
    assert len(calls) >= 2, "expected both evidence verification call sites"
    for start in calls:
        body = source[start:start + 400]
        assert "identity_by_silhouette=" in body, (
            f"a verify_evidence_asset call omits the lane flag:\n{body[:160]}")


def test_the_states_to_shots_collapse_is_reported():
    """It hid for an entire session: every log line read as success while cadence halved.

    "recovered on retry", "PASS", "Complete" — nothing printed the planned and delivered state
    counts next to each other, so a 62 -> 28 collapse was invisible.
    """
    source = Path(ep.__file__).read_text(encoding="utf-8")
    assert "planned -> " in source and "survived verification" in source
    assert "never reached the" in source, "the shortfall warning is missing"


def test_every_causal_replan_pins_the_engine():
    """A replan re-ran _assign_causal_spine and freely re-picked, so one render planned its story
    as an accumulating indictment, then an accidental invention (an engine with NO reference in the
    corpus), then back — each attempt fixing a different contract from the one that had just
    failed.

    Parsed, not string-windowed: two earlier tests in this repo scanned a fixed number of
    characters after an anchor and broke when a comment above the argument grew. Scanned across
    ALL call sites because causal_lane was once added to one of two, and every scene in that run
    came back with a blank role.
    """
    import ast

    source = (Path(__file__).resolve().parent.parent / "explainer_pipeline.py").read_text(
        encoding="utf-8")
    lane_calls = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        if getattr(node.func, "id", "") != "generate_script":
            continue
        keywords = {kw.arg for kw in node.keywords}
        if "causal_lane" in keywords:
            lane_calls.append((node.lineno, keywords))

    assert lane_calls, "no causal generate_script call site found — a refactor moved it"
    # The first draft is the one legitimately allowed to choose; every later one repairs a draft
    # that already has an engine and must keep it.
    replans = [(line, kw) for line, kw in lane_calls if "improve_note" in kw]
    assert replans, "no replan call site carries improve_note — anchor is stale"
    for line, keywords in replans:
        assert "pinned_engine" in keywords, (
            f"generate_script at line {line} replans without pinning the engine")


def test_the_pin_overrides_whatever_the_model_returns():
    source = (Path(__file__).resolve().parent.parent / "explainer_pipeline.py").read_text(
        encoding="utf-8")
    assert "engine_id = (pinned_engine if pinned_engine in _se.ENGINES" in source, \
        "the pin must win over the parsed engine, not merely be suggested in the prompt"


def _hook_script(hook, narration=None):
    return {"hook": hook,
            "scenes": [{"narration": narration if narration is not None else hook + " Step one."}]}


def test_a_hook_inside_the_budget_costs_nothing_and_changes_nothing():
    import explainer_pipeline as ep
    script = _hook_script("A short hook that promises the story.")
    out, cost = ep._ensure_hook_fits_budget(script)
    assert cost == 0.0 and out["hook"] == "A short hook that promises the story."


def test_an_over_long_hook_is_rewritten_in_BOTH_places(monkeypatch):
    """finalize_narration writes the hook into scene 1 verbatim, so rewriting only the field the
    validator reads would leave the narrator saying the old line while the contract passed."""
    import explainer_pipeline as ep
    long_hook = " ".join(["word"] * 25)
    monkeypatch.setattr(ep, "_ensure_hook_fits_budget_call",
                        None, raising=False)
    monkeypatch.setattr(ep, "_claude", lambda: _FakeClaude('{"hook":"A tight new promise."}'))
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)

    script = _hook_script(long_hook, narration=long_hook + " Step one. It begins.")
    out, _ = ep._ensure_hook_fits_budget(script)

    assert out["hook"] == "A tight new promise."
    assert out["scenes"][0]["narration"].startswith("A tight new promise.")
    assert "word word" not in out["scenes"][0]["narration"], "the spoken copy must change too"
    assert "It begins." in out["scenes"][0]["narration"], "replace the hook, not the scene"


def test_a_rewrite_that_is_still_too_long_leaves_the_original_alone(monkeypatch):
    """Fail closed. A truncated hook that no longer promises anything is the hinge-trim mistake."""
    import explainer_pipeline as ep
    long_hook = " ".join(["word"] * 25)
    monkeypatch.setattr(ep, "_claude",
                        lambda: _FakeClaude('{"hook":"%s"}' % " ".join(["still"] * 22)))
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: 0.01)

    out, _ = ep._ensure_hook_fits_budget(_hook_script(long_hook))
    assert out["hook"] == long_hook


def test_an_unavailable_model_leaves_the_script_unchanged(monkeypatch):
    import explainer_pipeline as ep
    long_hook = " ".join(["word"] * 25)

    def _boom():
        raise RuntimeError("no credits")
    monkeypatch.setattr(ep, "_claude", _boom)
    out, _ = ep._ensure_hook_fits_budget(_hook_script(long_hook))
    assert out["hook"] == long_hook


class _FakeClaude:
    def __init__(self, text):
        self._text = text

    @property
    def messages(self):
        import types
        return types.SimpleNamespace(create=lambda **kw: types.SimpleNamespace(
            content=[types.SimpleNamespace(text=self._text)], usage=None))


def test_the_sheet_is_written_in_the_chosen_engines_own_order(monkeypatch):
    """The sheet used to state ONE hardcoded order for all five engines:
    setup -> intervention -> false_resolution -> hinge -> mechanism. accumulating_indictment and
    power_reversal both run false_resolution BEFORE intervention and mechanism BEFORE hinge, and
    the labelling pass is forbidden to reorder what it labels. ENGINE_ORDER was therefore
    structurally guaranteed for the two engines the reference corpus backs best."""
    import event_functions as ef
    import story_engines as se

    for engine_id in se.ENGINES:
        prompt = _capture_beat_prompt(monkeypatch, causal_lane=True, pinned_engine=engine_id)
        order = se.expected_order(engine_id)
        # A MAPPED engine is not asked for roles at all -- it states what each fact IS and the
        # compiler assigns the order. So its prompt carries its own FUNCTIONS, and role order
        # would be the contract it was given a map to escape.
        if ef.map_for(engine_id) is not None:
            mapping = ef.map_for(engine_id)
            assert f"Engine: {engine_id}" in prompt and '"event_function"' in prompt
            for function in mapping.required:
                assert function in prompt, f"{engine_id}: {function} missing from its own prompt"
            assert " -> ".join(order) not in prompt, \
                f"{engine_id}: a mapped engine must not also be handed a role order"
            continue
        assert " -> ".join(order) in prompt, f"{engine_id}: sheet not written in its own order"
        assert se.get(engine_id)["name"].upper() in prompt


def test_an_engine_without_a_false_resolution_is_not_asked_for_one(monkeypatch):
    """accidental_invention has no false_resolution in its sequence -- 'many of these stories have
    no moment of apparent success to break' -- but the sheet demanded one EXACTLY ONCE."""
    import story_engines as se

    prompt = _capture_beat_prompt(monkeypatch, causal_lane=True,
                                  pinned_engine=se.ACCIDENTAL_INVENTION)
    assert "NO false_resolution" in prompt
    singletons = prompt.split("appear EXACTLY ONCE")[0]
    assert "false_resolution" not in singletons.split("A. This story runs")[1]


def test_a_pinned_engine_reaches_the_sheet(monkeypatch):
    """pinned_engine existed but only flowed to _assign_causal_spine and _retrieve_blueprint, so a
    replan rewrote the sheet in the same wrong order against the same hardcoded deadline."""
    import story_engines as se

    indictment = _capture_beat_prompt(monkeypatch, causal_lane=True,
                                      pinned_engine=se.ACCUMULATING_INDICTMENT)
    backfiring = _capture_beat_prompt(monkeypatch, causal_lane=True,
                                      pinned_engine=se.BACKFIRING_SOLUTION)
    assert indictment != backfiring, "the pin never reached the beat sheet"
    assert " -> ".join(se.expected_order(se.ACCUMULATING_INDICTMENT)) in indictment
    assert "Engine: backfiring_solution" in backfiring and '"event_function"' in backfiring


@pytest.mark.parametrize("pinned,expected", [("", "accumulating_indictment"),
                                              ("backfiring_solution", "backfiring_solution")])
def test_initial_preference_can_change_but_replan_pin_wins(monkeypatch, pinned, expected):
    payload = _spine(10)
    payload.update(engine="accumulating_indictment", engine_reason="The harm repeats as policy.")
    prompts = []
    def create(**call):
        prompts.append(call["messages"][0]["content"])
        return _reply(payload)
    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {
        "messages": type("M", (), {"create": staticmethod(create)})()})())
    beats, _ = ep._assign_causal_spine(_sheet(10)["beats"], "Why?", 170,
                                      pinned_engine=pinned, preferred_engine="backfiring_solution")
    assert beats[0]["_story_engine"] == expected
    assert beats[0]["_planned_story_engine"] == "backfiring_solution"
    assert beats[0]["_engine_reason"] == payload["engine_reason"]
    assert "fraction of SPOKEN RUNTIME, never the beat count" in prompts[0]
    assert "straight after the false_resolution" not in prompts[0]
    assert ("This is a REPLAN" in prompts[0]) == bool(pinned)


def test_reference_is_retrieved_before_planning(monkeypatch):
    seen = []
    def retrieve(*args):
        seen.append(args)
        return "NARRATION-REFERENCE"
    monkeypatch.setattr(ep, "_retrieve_blueprint", retrieve)
    prompt = _capture_beat_prompt(monkeypatch, causal_lane=True, pinned_engine="backfiring_solution")
    assert seen and seen[0][0] == "backfiring_solution"
    assert "NARRATION-REFERENCE" not in prompt  # editorial roles belong in expansion


def test_selector_uses_observed_runtime_without_banning_truthful_engine(monkeypatch):
    prompts = []
    def create(**call):
        prompts.append(call["messages"][0]["content"])
        return _reply({"engine": "backfiring_solution", "why": "Compress its opening by 2s."})
    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {
        "messages": type("M", (), {"create": staticmethod(create)})()})())
    costs = []
    assert ep._select_story_engine("A bounty backfires", 170, costs) == "backfiring_solution"
    assert "34" in prompts[0] and "36" in prompts[0]
    assert "Never change the facts" in prompts[0]
    assert len(costs) == 1 and costs[0] > 0


def test_causal_opening_budget_includes_hook_and_keeps_short_hinge():
    beats = _sheet(10)["beats"]
    hook = "A sensible bounty creates a bigger problem."
    budgets = ep._causal_word_budgets(beats, 440, "backfiring_solution", hook)
    prefix = len(hook.split()) + len(ep._CAUSAL_FORMAT_TAG.split())
    assert sum(budgets.values()) + prefix == 440
    assert sum(budgets[b["n"]] for b in beats[:4]) + prefix <= 440 * .2
    assert budgets[4] <= cs.MAX_HINGE_WORDS
    assert budgets[6] > budgets[1]


def test_short_causal_sheet_keeps_ending_and_all_required_beats(monkeypatch):
    class Messages:
        def create(self, **call):
            return _reply(_route(call["messages"][0]["content"], 10))
    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": Messages()})())
    monkeypatch.setattr(ep, "_dedupe_narration", lambda scenes, *a: (scenes, 0))
    # 75s, not 60s. backfiring_solution requires nine beats, which need 225 words at the 25-word
    # floor against the 176 a 60s runtime allows -- the pairing this fixture used to assert is the
    # one that killed job act_de546a5c at the storyboard three paid stages later. 75s is the
    # shortest runtime the engine actually fits, so the sheet under test is still the SHORT sheet
    # this test is about, only now it is one the pipeline is allowed to plan.
    script = ep._generate_script_chunked("Why?", 75, "s", "", 12, causal_lane=True,
                                         pinned_engine="backfiring_solution")
    assert len(script["scenes"]) == 10
    assert script["scenes"][-1]["causal_role"] == "tool"
    assert "intervention" in [scene["causal_role"] for scene in script["scenes"]]


def test_truncated_expansion_splits_batch_without_losing_or_repeating_beats(monkeypatch):
    expansions = []
    class Messages:
        def create(self, **call):
            prompt = call["messages"][0]["content"]
            matched = re.search(r"NOW WRITE scenes (\d+)-(\d+) ONLY", prompt)
            if not matched:
                return _reply(_route(prompt, 10))
            lo, hi = map(int, matched.groups())
            expansions.append((lo, hi))
            if len(expansions) == 1:
                response = _reply({})
                response.stop_reason = "max_tokens"
                return response
            return _reply({"scenes": [{"narration": f"Unique beat number {i}.",
                                       "environment_type": "city"} for i in range(lo, hi + 1)]})
    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": Messages()})())
    monkeypatch.setattr(ep, "_dedupe_narration", lambda scenes, *a: (scenes, 0))
    monkeypatch.setattr(ep, "_msg_cost", lambda usage: .1)
    script = ep._generate_script_chunked("Why?", 200, "s", "", 10, causal_lane=True,
                                         pinned_engine="backfiring_solution")
    assert expansions == [(1, 10), (1, 5), (6, 10)]
    assert [s["story_beat_n"] for s in script["scenes"]] == list(range(1, 11))
    assert script["_script_cost_usd"] >= .3


@pytest.mark.parametrize("first_errors,retry_errors,expected", [(1, 3, "first"), (3, 1, "retry")])
def test_fewer_causal_failures_win_before_pacing(monkeypatch, first_errors, retry_errors, expected):
    drafts = iter([{"name": "first", "scenes": []}, {"name": "retry", "scenes": []}])
    monkeypatch.setattr(ep, "generate_script", lambda *a, **k: next(drafts))
    monkeypatch.setattr(ep, "_causal_contract_report", lambda script, *a: (
        False, ["error"] * (first_errors if script["name"] == "first" else retry_errors)))
    monkeypatch.setattr(ep, "validate_longform_story", lambda script, *a: {
        "passed": False, "score": 40 if script["name"] == "first" else 90, "errors": []})
    monkeypatch.setattr(ep, "validation_rank", lambda report: -report["score"])
    monkeypatch.setattr(ep, "grade_script", lambda *a, **k: None)
    monkeypatch.setattr(ep, "_ensure_hook_names_subject", lambda script, *a, **k: (script, 0))
    monkeypatch.setattr(ep, "_LONGFORM_CONTRACT_RETRIES", 1)
    result = ep.generate_graded_script("Why?", 170, "s", "", "landscape", "", causal_lane=True)
    assert result["name"] == expected


def test_the_prompt_gives_exactly_one_instruction_about_naming_the_subject(monkeypatch):
    """The guard for the hook, mirroring the one that guards the mechanism deadline.

    story_direction and causal_rules both reach the beat sheet — the first through
    _operator_block, the second inline — and for a while they disagreed. story_direction said
    'describe the shape, not the topic: say "a problem" where you mean the specific thing' while
    causal_rules, in the same prompt, demanded concrete nouns and a named actor. Three of four
    measured drafts hedged the subject ("a menace", "a deadly animal"), which is what a model does
    when one instruction cancels another.

    Same failure the mechanism deadline had, and it cost twelve renders that time.
    """
    causal = _capture_beat_prompt(monkeypatch, causal_lane=True)

    # No instruction may ask for an abstraction in place of the subject.
    for evasive in ("shape, not the topic", "where you mean the specific thing",
                    "let the concrete subject arrive"):
        assert evasive not in causal, f"the prompt still asks the hook to hedge: {evasive!r}"

    # And the positive rule is stated once, not accreted into three overlapping paragraphs.
    assert causal.count("named actor") == 1, "the subject rule is stated more than once"

    # A retired instruction must not survive as a quotation. Naming the behaviour you are
    # forbidding still puts that phrasing in the context.
    assert "name the shape" not in causal


def test_the_hook_rule_does_not_quote_a_failed_hook(monkeypatch):
    """Bad examples prime. The corpus exemplars carry the rule; our own failures do not."""
    causal = _capture_beat_prompt(monkeypatch, causal_lane=True)
    for failure in ("a menace", "erase a menace", "more of it"):
        assert failure not in causal, f"the prompt quotes a hook it is trying to prevent: {failure!r}"
    assert "concrete title subject" in causal


# --- the fact model reaches the calls that plan and write it -------------------------------------

def test_the_beat_sheet_asks_for_events_and_provenance(monkeypatch):
    """The factual layer has to be PLANNED, not inferred from prose afterwards.

    Narration used to be the story, the evidence record, the binding key and the image instruction
    at once, and every pass that improved one damaged another.
    """
    causal = _capture_beat_prompt(monkeypatch, causal_lane=True)
    for token in ('"event"', '"claim_refs"', '"scope"', '"parallel_case_id"', '"changes_state"'):
        assert token in causal, f"the beat sheet never asks for {token}"
    assert "primary_story" in causal and "parallel_case" in causal
    assert "its own supporting claim_refs" in causal


def test_the_beat_sheet_permits_an_unsourced_connective(monkeypatch):
    factual = _capture_beat_prompt(monkeypatch, causal_lane=True)
    assert "Every event you supply needs a nonempty factual text" in factual
    assert "adds presentation transitions" in factual


def test_the_cinematic_lane_gains_no_fact_model(monkeypatch):
    """Strictly additive, like every other causal field."""
    plain = _capture_beat_prompt(monkeypatch)
    for token in ('"event"', '"scope"', '"changes_state"', "FACTUAL CEILING"):
        assert token not in plain, f"{token} leaked into the cinematic lane prompt"


def test_the_expansion_writes_narration_from_the_event(monkeypatch):
    """The ceiling has to reach the call that writes the words, and be shown the event itself."""
    expansions = []

    class _Messages:
        def create(self, **call):
            prompt = call["messages"][0]["content"]
            if "NOW WRITE scenes" in prompt:
                expansions.append(prompt)
                raise _Abort
            return _reply(_route(prompt, 10))

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    with pytest.raises(_Abort):
        ep._generate_script_chunked("Why?", 200, "s", "", 10, causal_lane=True)

    prompt = expansions[0]
    assert "FACTUAL CEILING" in prompt
    assert "event.text" in prompt
    # The rule is useless if the writer cannot see the event it must not exceed.
    assert '"event"' in prompt, "the expansion sheet does not carry the event"
    for invented in ("mud-brick", "overnight"):
        assert invented in prompt, "the prompt should show what exceeding the ceiling looks like"


def test_the_event_rules_do_not_excuse_the_roles_the_spine_requires():
    """F3 invites an empty event; coverage demands one for six roles. They must not disagree.

    Measured on Hanoi: the planner read F3, decided a mechanism "asserts no history" because it
    states a rule, returned event.text = "" -- and the spine failed for a missing mechanism while
    every sourced beat passed. Same class as the two mechanism deadlines that cost twelve renders.
    """
    source = Path(ep.__file__).read_text(encoding="utf-8")
    rule = source[source.index('"F3. A beat that asserts no history'):]
    rule = rule[:rule.index('"F4.')]
    assert "REQUIRED_SPINE_ROLES" in rule, \
        "F3 must exempt the required roles, naming them from the list that defines them"
    assert "MUST carry an event" in rule


def test_a_suspect_citation_is_repaired_and_re_judged_not_merely_refused_earlier(monkeypatch):
    """Rejecting five attempts earlier is cheaper and leaves the blocker exactly where it was."""
    claims = {"c08": {"claim": "Authorities announced a bounty on every dead rat."},
              "c09": {"claim": "The bounty was extended to anyone who brought a rat tail."}}
    beats = [{"beat_id": "beat_02", "incentive": {"rewarded_measure": "a severed rat tail",
                                                  "measure_claim_refs": ["c08"],
                                                  "actual_goal": "fewer rats",
                                                  "goal_claim_refs": ["c05"]}}]
    suspicions = [{"beat_id": "beat_02", "phrase": "a severed rat tail", "cited": ["c08"],
                   "candidates": ["c09: ..."], "code": "MEASURE_CITATION_SUSPECT",
                   "message": "..."}]
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 900, "output_tokens": 40})(),
                "content": [type("C", (), {"text": '{"measure_claim_refs":["c09"]}'})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, cost = ep._repair_incentive_citations(beats, suspicions, claims, "Why?")
    assert out[0]["incentive"]["measure_claim_refs"] == ["c09"]
    assert cost > 0, "the repair is charged like any other provider call"
    assert "ACCEPTED AS PROOF" in seen["prompt"] and "c09" in seen["prompt"]


def test_an_unusable_repair_leaves_the_original_citations_for_the_judge(monkeypatch):
    """The heuristic that raised the concern must never get to decide the outcome."""
    claims = {"c08": {"claim": "A bounty was announced."}}
    beats = [{"beat_id": "beat_02", "incentive": {"rewarded_measure": "a tail",
                                                  "measure_claim_refs": ["c08"]}}]
    suspicions = [{"beat_id": "beat_02", "phrase": "a tail", "cited": ["c08"], "candidates": []}]

    class _Messages:
        def create(self, **call):
            raise RuntimeError("provider down")

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, _ = ep._repair_incentive_citations(beats, suspicions, claims, "Why?")
    assert out[0]["incentive"]["measure_claim_refs"] == ["c08"], "unchanged, not dropped"


def test_a_repair_cannot_invent_a_claim_id(monkeypatch):
    claims = {"c08": {"claim": "A bounty was announced."}}
    beats = [{"beat_id": "beat_02", "incentive": {"rewarded_measure": "a tail",
                                                  "measure_claim_refs": ["c08"]}}]
    suspicions = [{"beat_id": "beat_02", "phrase": "a tail", "cited": ["c08"], "candidates": []}]

    class _Messages:
        def create(self, **call):
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 10, "output_tokens": 5})(),
                "content": [type("C", (), {"text": '{"measure_claim_refs":["c99"]}'})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, _ = ep._repair_incentive_citations(beats, suspicions, claims, "Why?")
    assert out[0]["incentive"]["measure_claim_refs"] == ["c08"], "a ref outside the ledger is refused"


def test_the_mechanism_repair_is_triggered_by_the_judge_not_by_stem_overlap():
    from test_story_planning_flow import factual_fixture, EvidenceFixture, recite
    import story_planning
    beats, claims = factual_fixture(wrong_citation=True)
    judge = EvidenceFixture()
    result = story_planning.prepare(beats, "backfiring_solution", claims, judge=judge, repair=recite)
    assert result["compiled"]["passed"]
    verdicts = [call for call in judge.calls if call["event"].startswith("The reward was paid")]
    assert [{c["claim_id"] for c in v["claims"]} for v in verdicts] == [{"c3"}, {"c7"}]


def test_the_repair_asks_for_both_halves_of_the_mechanism():
    """The goal citation was never checked at all, and it was wrong in every sampled sheet."""
    source = Path(ep.__file__).read_text(encoding="utf-8")
    block = source[source.index("def _repair_incentive_citations"):]
    block = block[:block.index("def _generate_script_chunked")]
    assert "measure_claim_refs" in block and "goal_claim_refs" in block
    assert "COUNTING how many were handed in" in block, "name the claim that keeps being cited"


def test_a_narration_that_overshoots_its_event_is_repaired_not_only_refused(monkeypatch):
    """The fidelity boundary returns the core to stop at and the details that overshot. Nothing
    consumed either, so a render was refused for "Rows of pens" against an event saying people
    bred rats -- a real image, no source, and cutting it costs the sentence nothing.
    """
    script = {"scenes": [
        {"scene_id": "event_07", "beat_id": "event_07", "narration": "Rows of pens. They bred rats.",
         "causal_role": "reversal", "evidence_id": "e07",
         "event": {"text": "People bred rats on the outskirts to earn the bounty."},
         "claim_refs": [{"claim_id": "c14", "evidence_id": "e07",
                         "narration_phrase": "They bred rats."}]}]}
    dossier = {"claims": [{"claim_id": "c14", "claim": "People bred rats to earn the bounty."}]}
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_07",
                          "message": "asserts more than its event",
                          "supported_core": "People bred rats on the outskirts.",
                          "unsupported_details": ["Rows of pens"]}]}
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["payload"] = call["messages"][0]["content"]
            seen["system"] = call["system"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 900, "output_tokens": 60})(),
                "content": [type("C", (), {"text": json.dumps({"scenes": [
                    {"scene": 1, "narration": "On the outskirts, they bred rats.",
                     "evidence_id": "e07",
                     "claim_refs": [{"claim_id": "c14", "evidence_id": "e07",
                                     "narration_phrase": "On the outskirts, they bred rats."}]}]})})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    repaired, cost = ep.repair_claim_join_failures(script, dossier, report)
    assert cost > 0 and "Rows of pens" not in repaired["scenes"][0]["narration"]
    # The repair is told what it MAY say, not only that it was wrong.
    assert "People bred rats on the outskirts to earn the bounty." in seen["payload"]
    assert "NARRATION_EXCEEDS_EVENT" in seen["system"] and "Imagery, rhythm and voice are free" in seen["system"]


def test_a_beat_id_addressed_failure_resolves_to_its_scene():
    """The fact model addresses scenes by beat_id; the older codes use a 1-based index."""
    script = {"scenes": [{"beat_id": "event_01", "narration": "One."},
                         {"beat_id": "event_07", "narration": "Two."}]}
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_07"}]}
    # An unresolvable id must refuse the repair rather than silently rewriting scene 0.
    ep.repair_claim_join_failures(script, {"claims": []}, report)
    assert report["errors"][0]["scene"] == 2
    ghost = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_99"}]}
    assert ep.repair_claim_join_failures(script, {"claims": []}, ghost) == (script, 0.0)


def test_the_repair_chooses_from_a_ranked_shortlist_not_the_whole_ledger(monkeypatch):
    """Handed the full ledger, a model picked the tail-COUNT claim three times running.

    Ranking by the stems that make the rewarded measure specific puts the claim describing what
    was ACCEPTED at the top, so the choice is made among a handful of plausible claims. It narrows
    the field; it does not make the choice, and whatever comes back still faces the judge.
    """
    claims = {
        "c03": {"claim": "The French installed modern sewers throughout Hanoi."},
        "c04": {"claim": "Invasive brown rats colonised the new sewer network."},
        "c05": {"claim": "Officials wanted the rat population reduced to hold off plague."},
        "c06": {"claim": "Researchers had linked plague to fleas carried by rodents."},
        "c08": {"claim": "In April 1902 the authorities announced a bounty on every dead rat."},
        "c09": {"claim": "The bounty was extended to anyone in the city who brought a rat tail "
                         "to the authorities after civil servants declined to handle corpses."},
        "c10": {"claim": "The number of tails handed in climbed into the thousands within days."},
        "c14": {"claim": "Entrepreneurs on the outskirts bred rats to profit from the bounty."},
    }
    beats = [{"beat_id": "event_04",
              "incentive": {"rewarded_measure": "a severed rat tail",
                            "measure_claim_refs": ["c08"],
                            "actual_goal": "fewer rats", "goal_claim_refs": ["c05"]}}]
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 400, "output_tokens": 30})(),
                "content": [type("C", (), {"text": '{"measure_claim_refs":["c09"]}'})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, cost = ep._repair_incentive_citations(
        beats, [{"beat_id": "event_04", "phrase": "a severed rat tail", "cited": ["c08"]}],
        claims, "Why?")

    assert "c09" in seen["prompt"], "the claim that fits must be on the shortlist"
    assert "c08" in seen["prompt"] and "c05" in seen["prompt"], \
        "what the planner already cited is always offered, so it can be kept"
    assert "c03" not in seen["prompt"], "the whole dossier is not dumped in"
    assert out[0]["incentive"]["measure_claim_refs"] == ["c09"]
    assert cost > 0


def test_an_unrankable_measure_still_offers_the_model_the_whole_ledger(monkeypatch):
    """Ranking that separates nothing must widen the field, never hand over an empty one."""
    claims = {"c08": {"claim": "A bounty was announced."}}
    beats = [{"beat_id": "event_04",
              "incentive": {"rewarded_measure": "", "measure_claim_refs": ["c08"],
                            "actual_goal": "fewer rats", "goal_claim_refs": []}}]
    called = []

    class _Messages:
        def create(self, **call):
            called.append(call)
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 100, "output_tokens": 20})(),
                "content": [type("C", (), {"text": '{"goal_claim_refs":["c08"]}'})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    ep._repair_incentive_citations(
        beats, [{"beat_id": "event_04", "phrase": "", "cited": ["c08"]}], claims, "Why?")
    assert called, "an empty measure gives the ranking nothing to work with; the model still runs"
    assert "c08" in called[0]["messages"][0]["content"]


def test_the_shortlist_covers_the_goal_as_well_as_the_measure(monkeypatch):
    """A shortlist for one half of a two-part claim only moves the failure.

    Measured: with the measure ranked and the goal not, the repair kept citing the bounty
    announcement for a goal the announcement never states, and the boundary said so -- "the claim
    shows a bounty to kill rats but does not mention plague as the reason". Every fix until then
    had been about the measure.
    """
    claims = {
        "c02": {"claim": "Colonial Hanoi was crowded and its sanitation was poor."},
        "c05": {"claim": "French medical experts feared the Third Plague Pandemic reaching Hanoi."},
        "c06": {"claim": "Researchers had shown rat fleas transmit plague to people."},
        "c08": {"claim": "In April 1902 the authorities announced a bounty on every dead rat."},
        "c09": {"claim": "The bounty was extended to anyone who brought a rat tail in."},
        "c10": {"claim": "The number of tails handed in climbed into the thousands."},
        "c14": {"claim": "Entrepreneurs bred rats on the outskirts to earn the bounty."},
    }
    beats = [{"beat_id": "event_04",
              "incentive": {"rewarded_measure": "a severed rat tail",
                            "measure_claim_refs": ["c08"],
                            "actual_goal": "fewer plague-carrying rats",
                            "goal_claim_refs": ["c08"]}}]
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 400, "output_tokens": 30})(),
                "content": [type("C", (), {"text": '{"measure_claim_refs":["c09"],'
                                                   '"goal_claim_refs":["c05","c06"]}'})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    out, _ = ep._repair_incentive_citations(
        beats, [{"beat_id": "event_04", "phrase": "a severed rat tail", "cited": ["c08"]}],
        claims, "Why?")
    assert "c09" in seen["prompt"], "a candidate for what was accepted as proof"
    assert "c05" in seen["prompt"], "and one for why the policy existed at all"
    assert out[0]["incentive"]["goal_claim_refs"] == ["c05", "c06"]


def test_the_goal_is_read_under_the_name_the_schema_actually_uses():
    """`stated_policy_goal` is the schema's name; `actual_goal` is the older alias.

    Reading only the old name gave the goal ranking an empty phrase, so the shortlist carried no
    plague claim and the repair kept citing the bounty announcement for a goal about plague. The
    boundary said so four times: "the claim mentions a bounty on dead rats but does not specify
    Hanoi or state that plague risk was the motivation."
    """
    source = Path(ep.__file__).read_text(encoding="utf-8")
    block = source[source.index("def _repair_incentive_citations"):]
    block = block[:block.index("def _generate_script_chunked")]
    assert 'block.get("stated_policy_goal")' in block, \
        "the ranking must read the field the planner is actually asked to fill"
    # And story_compiler must accept both, since it is the one that builds the sentence.
    import story_compiler as sc
    for field in ("stated_policy_goal", "actual_goal"):
        got = sc.incentive_of({"incentive": {"rewarded_measure": "a tail", field: "fewer rats",
                                             "measure_claim_refs": ["c1"],
                                             "goal_claim_refs": ["c2"]}})
        assert got["actual_goal"] == "fewer rats", f"{field} must resolve"


def test_a_two_word_hook_overage_trims_the_hook_instead_of_replanning_the_story():
    """A replan returns a DIFFERENT story whose evidence must be re-established from scratch.

    Measured: a draft whose spine had just passed in full -- every required causal role supported,
    the derived mechanism among them -- was replanned because its hook ran 20 words against an
    18-word budget. The replacement sheet failed the spine. Two words cost a validated story, and
    `_ensure_hook_fits_budget` already existed to fix exactly this.
    """
    assert ep._only_hook_length_blocks({"errors": [{"code": "LONG_HOOK"}]}, [])
    assert ep._only_hook_length_blocks({"errors": []}, [{"code": "LONG_HOOK"}])
    # Anything else still replans: a hook that is too long AND a mechanism that is too late is a
    # story problem, and trimming the hook would leave the run failing on the other contract.
    assert not ep._only_hook_length_blocks(
        {"errors": [{"code": "LONG_HOOK"}]}, [{"code": "LATE_MECHANISM"}])
    assert not ep._only_hook_length_blocks({"errors": []}, []), "nothing blocking is not this case"


def test_the_hook_trim_is_wired_ahead_of_the_replan():
    source = Path(ep.__file__).read_text(encoding="utf-8")
    block = source[source.index("TRIM THE HOOK BEFORE THROWING THE STORY AWAY"):]
    block = block[:block.index("cand = generate_script(")]
    assert "_ensure_hook_fits_budget" in block
    assert "_causal_contract_report" in block, "re-checked after trimming, not assumed fixed"
    assert "break" in block, "a draft that now passes must not be replanned anyway"


def test_repairing_an_overreaching_hook_updates_the_hook_field_too(monkeypatch):
    """The hook lives twice: in script["hook"] and prepended to the scene it opens.

    Repairing only the narration leaves the over-reaching sentence in the field the description,
    the thumbnail and the next finalize_narration all read -- and finalize_narration would put it
    straight back into the narration it was just cut from.
    """
    script = {"hook": "Officials paid a cent per rat tail and bred more rats.",
              "scenes": [{"scene_id": "event_01", "beat_id": "event_01", "evidence_id": "e01",
                          "narration": "Officials paid a cent per rat tail and bred more rats. "
                                       "The sewers filled.",
                          "event": {"text": "Officials paid a bounty per rat tail."},
                          "claim_refs": [{"claim_id": "c08", "evidence_id": "e01",
                                          "narration_phrase": "The sewers filled."}]}]}
    dossier = {"claims": [{"claim_id": "c08", "claim": "A bounty was paid per rat tail."}]}
    report = {"errors": [{"code": "HOOK_EXCEEDS_STORY", "scene": "hook",
                          "message": "promises more than the events deliver",
                          "unsupported_details": ["a cent per rat tail (specific amount)"]}]}

    class _Messages:
        def create(self, **call):
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 300, "output_tokens": 40})(),
                "content": [type("C", (), {"text": json.dumps({"scenes": [
                    {"scene": 1, "evidence_id": "e01",
                     "narration": "Officials paid a bounty per rat tail and bred more rats. "
                                  "The sewers filled.",
                     "claim_refs": [{"claim_id": "c08", "evidence_id": "e01",
                                     "narration_phrase": "The sewers filled."}]}]})})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    repaired, cost = ep.repair_claim_join_failures(script, dossier, report)
    assert cost > 0
    assert "a cent" not in repaired["scenes"][0]["narration"]
    assert repaired["hook"] == "Officials paid a bounty per rat tail and bred more rats.", \
        "the hook field follows the repaired sentence, not the old one"


def test_the_claim_repair_runs_again_while_it_is_still_converging():
    """One pass took a render from five narration overshoots to one, then refused for the survivor.

    Each pass rewrites only the scenes still failing, so a second pass on a shrinking list is a
    smaller job rather than a retry of the one that just ran. Gated on the count going DOWN: a
    repair that fixes nothing, or trades one overshoot for another, stops immediately.
    """
    source = Path(ep.__file__).read_text(encoding="utf-8")
    block = source[source.index("REPAIR WHILE IT IS CONVERGING"):]
    block = block[:block.index("claim_validation = _validate_claims(script, research_dossier",
                               block.index("_after_count"))]
    assert "_CLAIM_REPAIR_PASSES" in block, "bounded by a named ceiling, not an open loop"
    assert "if _after_count >= _before_count:" in block and "break" in block, \
        "a pass that does not reduce the failures must be the last one"
    assert ep._CLAIM_REPAIR_PASSES >= 2 and ep._CLAIM_REPAIR_PASSES <= 4, \
        "a ceiling, and a small one — each pass is a paid provider call"


def test_state_once_stays_off_on_a_sourced_script():
    """Enabled once, measured, reverted. Kept as a test so it is not re-enabled from theory.

    On the same topic and dossier it moved repetition 58 -> 52 (the axis it was turned on to fix),
    the overall grade 74 -> 69 (back under the floor), and the runtime 79.9s -> 73.4s, under the
    76.5s contract floor. The hook lost its mechanism -- "residents bred rats to be paid" became
    "only made the rat problem worse" -- while scoring HIGHER for saying less.
    """
    source = Path(ep.__file__).read_text(encoding="utf-8")
    gate = source[source.index("OFF on a sourced script"):]
    gate = gate[:gate.index("for i, s in enumerate(all_scenes):")]
    assert "if research_dossier:" in gate and "dc = 0.0" in gate
    assert "58 -> 52" in gate, "the measurement stays next to the decision it justifies"


def test_the_dedupe_tags_each_line_with_the_event_it_may_not_exceed(monkeypatch):
    beats = [{"beat": "b1", "event": {"text": "Officials paid a bounty per rat tail."}},
             {"beat": "b2", "event": {"text": "People bred rats to earn it."}},
             {"beat": "b3", "event": {}}, {"beat": "b4", "event": {"text": "Tails poured in."}}]
    scenes = [{"narration": f"Line {i}."} for i in range(1, 5)]
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["prompt"] = call["messages"][0]["content"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 100, "output_tokens": 20})(),
                "content": [type("C", (), {"text": json.dumps(
                    {"narration": [f"Line {i}." for i in range(1, 5)]})})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    ep._dedupe_narration(scenes, beats, "throughline")
    assert "may assert nothing beyond: Officials paid a bounty per rat tail." in seen["prompt"]
    # A beat with no event carries no tag rather than an empty one.
    assert "[may assert nothing beyond: ]" not in seen["prompt"]


def test_the_repair_is_told_that_actors_and_intervals_are_facts():
    """Four survivors after a repair pass on Macquarie, and every one was an actor or a time hedge.

    "Managers carried out the eradication", "Conservationists" as the ones doing the killing,
    "Decades earlier". The subtractive rule was already there; the model kept the attribution
    anyway, because naming a doer reads as clarity rather than as a new fact.
    """
    system = ep._CLAIM_REPAIR_SYSTEM
    assert "if the event does not say who did a thing" in system
    assert "'the cats were shot', not " in system
    assert "'decades " in system and "assert an interval" in system


def test_actors_the_event_does_not_name_are_handed_over_by_name():
    """Three rounds of instruction did not stop this.

    The repair prompt says "if the event does not say who did a thing, the narration must not name
    them either", gives 'the cats were shot', not 'managers shot the cats' as the worked example,
    and a run came back asserting "Managers began killing cats". Naming a doer reads as clarity
    rather than as a new fact, so the rule keeps losing to the instinct to write a clear sentence.
    """
    assert ep.unsupported_actors("The cats were shot from 1985.",
                                 "Managers began killing cats.") == ["managers"]
    # Supported by the event, so not flagged.
    assert ep.unsupported_actors("Managers shot the cats.", "Managers began killing cats.") == []
    assert ep.unsupported_actors("The cats were shot.", "The cats were shot.") == []
    # It proposes only: it cannot know whether the event says the same thing in other words.
    assert ep.unsupported_actors("", "Conservationists acted.") == ["conservationists"]


def test_the_repair_payload_carries_the_flagged_actors(monkeypatch):
    script = {"scenes": [
        {"scene_id": "event_04", "beat_id": "event_04", "evidence_id": "e04",
         "narration": "Managers began killing cats in 1985.",
         "event": {"text": "A programme shot the island's cats from 1985."},
         "claim_refs": [{"claim_id": "c1", "evidence_id": "e04",
                         "narration_phrase": "Managers began killing cats in 1985."}]}]}
    dossier = {"claims": [{"claim_id": "c1", "claim": "The cats were shot from 1985."}]}
    report = {"errors": [{"code": "NARRATION_EXCEEDS_EVENT", "scene": "event_04",
                          "message": "asserts more than its event",
                          "unsupported_details": ["Managers"]}]}
    seen = {}

    class _Messages:
        def create(self, **call):
            seen["payload"] = call["messages"][0]["content"]
            return type("R", (), {
                "usage": type("U", (), {"input_tokens": 200, "output_tokens": 40})(),
                "content": [type("C", (), {"text": json.dumps({"scenes": [
                    {"scene": 1, "narration": "The cats were shot from 1985.",
                     "evidence_id": "e04",
                     "claim_refs": [{"claim_id": "c1", "evidence_id": "e04",
                                     "narration_phrase": "The cats were shot from 1985."}]}]})})()]})()

    monkeypatch.setattr(ep, "_claude", lambda: type("C", (), {"messages": _Messages()})())
    ep.repair_claim_join_failures(script, dossier, report)
    assert "actors_the_event_does_not_name" in seen["payload"]
    assert "managers" in seen["payload"]
