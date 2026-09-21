"""Stage 2: the role rules count story moves, not screen time -- and are no weaker for it.

Each of these rules was written against a world where a beat and a scene were the same object, so
each counted scenes while meaning beats. Splitting a beat across scenes makes the difference
visible: three scenes of one mechanism are one mechanism, not three.

Every test here comes in a pair. One proves a continuation is allowed through; the other proves
the rule still fires on the thing it was written to catch. A rule that only has the first half is
not rescoped, it is disabled.
"""
import causal_story as cs
import story_fact_model as sfm


def _step(step_id, role, caused_by="", continues="", situation="Something happened."):
    return {"step_id": step_id, "role": role, "caused_by": caused_by, "continues": continues,
            "situation": situation, "label": step_id, "start_sec": 0.0, "chapter": 0,
            "event_function": "", "index": 0}


def _codes(issues):
    return {issue["code"] for issue in issues}


# ── DUPLICATE_ROLE ───────────────────────────────────────────────────────────────────────────

def test_three_scenes_of_one_mechanism_are_one_mechanism():
    issues = []
    cs._check_roles([
        _step("s1", cs.SETUP),
        _step("s2", cs.MECHANISM, caused_by="s1"),
        _step("s3", cs.MECHANISM, caused_by="s2", continues="s2"),
        _step("s4", cs.MECHANISM, caused_by="s3", continues="s3"),
        _step("s5", cs.REVERSAL, caused_by="s4"),
    ], issues)
    assert "DUPLICATE_ROLE" not in _codes(issues)


def test_two_different_beats_claiming_mechanism_still_fail():
    """The case the rule exists for. Its own docstring: the story broke its own move twice."""
    issues = []
    cs._check_roles([
        _step("s1", cs.SETUP),
        _step("s2", cs.MECHANISM, caused_by="s1"),
        _step("s3", cs.MECHANISM, caused_by="s2"),   # no `continues` -- a second assertion
        _step("s4", cs.REVERSAL, caused_by="s3"),
    ], issues)
    assert "DUPLICATE_ROLE" in _codes(issues)


# ── CAUSED_SETUP versus ORPHAN_STEP ──────────────────────────────────────────────────────────

def test_a_split_setup_satisfies_both_chain_rules_at_once():
    """Unscoped these are mutually unsatisfiable: parts 2..n need a cause to avoid ORPHAN_STEP,
    and having one trips CAUSED_SETUP. Measured on the cobra fixture before the fix."""
    issues = []
    cs._check_chain([
        _step("s1", cs.SETUP),
        _step("s2", cs.SETUP, caused_by="s1", continues="s1"),
        _step("s3", cs.MECHANISM, caused_by="s2"),
    ], issues)
    assert "CAUSED_SETUP" not in _codes(issues)
    assert "ORPHAN_STEP" not in _codes(issues)


def test_the_story_first_step_still_cannot_be_caused():
    issues = []
    cs._check_chain([_step("s1", cs.SETUP, caused_by="s0"),
                     _step("s2", cs.MECHANISM, caused_by="s1")], issues)
    assert "CAUSED_SETUP" in _codes(issues)


def test_a_continuation_that_names_no_cause_is_still_an_orphan():
    """The continuation must actually chain. Exempting it from CAUSED_SETUP must not exempt it
    from saying what it follows."""
    issues = []
    cs._check_chain([
        _step("s1", cs.SETUP),
        _step("s2", cs.SETUP, caused_by="", continues="s1"),
    ], issues)
    assert "ORPHAN_STEP" in _codes(issues)


# ── SOFT_HINGE ───────────────────────────────────────────────────────────────────────────────

def test_the_hinge_budget_is_spent_once_not_per_scene():
    """MAX_HINGE_WORDS budgets the TURN, and the turn happens once."""
    long_tail = "and the consequences kept arriving for years afterwards in every county affected"
    issues = []
    cs._check_hinge([
        _step("s1", cs.HINGE, situation="Except the problem was not solved."),
        _step("s2", cs.HINGE, continues="s1", situation=long_tail),
    ], issues)
    assert "SOFT_HINGE" not in _codes(issues)


def test_an_over_long_hinge_still_fails_on_the_part_that_turns():
    issues = []
    cs._check_hinge([_step("s1", cs.HINGE, situation=" ".join(["word"] * 40))], issues)
    assert "SOFT_HINGE" in _codes(issues)


# ── duplicate causal job ─────────────────────────────────────────────────────────────────────

def _beat(beat_id, role, text, continues=""):
    return {"beat_id": beat_id, "role": role, "continues": continues,
            "event": {"text": text, "claim_refs": ["c01"]}}


SAME = "The Soil Conservation Service paid farmers by the acre to plant kudzu across the South."


def test_a_beat_continuing_itself_is_not_two_beats_doing_one_job():
    """Overlap is 1.0 by construction -- the continuation shares the event text exactly."""
    dupes = sfm.duplicate_event_functions(
        [_beat("event_08", "mechanism", SAME),
         _beat("event_08b", "mechanism", SAME, continues="event_08")], "backfiring_solution")
    assert dupes == []


def test_two_real_beats_sharing_one_sentence_are_still_caught():
    """The measured case: a sheet using one sentence for both its mechanism and its reversal."""
    dupes = sfm.duplicate_event_functions(
        [_beat("event_08", "mechanism", SAME),
         _beat("event_11", "reversal", SAME)], "backfiring_solution")
    assert dupes, "a genuine duplicate causal job must still be reported"


def test_a_continuation_cannot_shield_a_later_genuine_duplicate():
    """Skipped BEFORE being recorded, so it cannot become the thing a later beat matches against."""
    dupes = sfm.duplicate_event_functions(
        [_beat("event_08", "mechanism", SAME),
         _beat("event_08b", "mechanism", SAME, continues="event_08"),
         _beat("event_11", "reversal", SAME)], "backfiring_solution")
    flagged = {issue.get("beat_id") for issue in dupes}
    assert "event_11" in flagged
    assert "event_08b" not in flagged
